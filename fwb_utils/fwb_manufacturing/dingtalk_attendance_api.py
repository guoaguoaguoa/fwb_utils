# Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and Contributors
# See license.txt
"""钉钉考勤 API 同步。

双接口口径：
- 获取打卡结果 -> Attendance（工资唯一依据，提交态；变更走取消 + 修订）。
- 获取打卡详情 -> Employee Checkin（原始流水证据；device_id 保存 401/402 门或 WiFi）。
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import datetime, timezone

import frappe
import requests
from frappe import _
from frappe.utils import (
	add_days,
	add_months,
	cint,
	convert_utc_to_system_timezone,
	flt,
	get_datetime,
	get_first_day,
	get_last_day,
	getdate,
	now_datetime,
	nowdate,
)

from fwb_utils.fwb_manufacturing.dingtalk_attendance import (
	EARLY_DEDUCTION_COMPONENT,
	LATE_DEDUCTION_COMPONENT,
	REGULAR_WORKER_STRUCTURE,
	_employee_structure,
	_has_complete_punches,
	_leave_suppresses_minutes,
	_load_attendance_params,
	_meal_allowance_days_for_attendance,
	_minutes_to_time_string,
	_paid_leave_names,
	_schedule_profile_for,
	_time_string_from_value,
	apply_attendance_payroll_adjustments_to_salary_slip,
	calculate_late_early_minutes,
	daily_overtime_days,
	get_attendance_payroll_factors,
	is_paid_dingtalk_leave,
)
from fwb_utils.fwb_manufacturing.attendance_report_utils import department_filter_names
from fwb_utils.fwb_manufacturing.rmb_capital import set_rmb_total_in_words

ACCESS_TOKEN_URL = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
ATTENDANCE_RESULT_URL = "https://oapi.dingtalk.com/attendance/list"
ATTENDANCE_DETAIL_URL = "https://oapi.dingtalk.com/attendance/listRecord"
ATTENDANCE_GROUP_QUERY_URL = "https://oapi.dingtalk.com/topapi/attendance/group/query"
ATTENDANCE_LEAVE_TIME_URL = "https://oapi.dingtalk.com/topapi/attendance/getleavetimebynames"

MAX_USERS_PER_CALL = 50
MAX_DAYS_PER_CALL = 7
DEFAULT_RESULT_LIMIT = 50
LEAVE_NAMES_MAX_LENGTH = 20
RECALCULATION_SAMPLE_LIMIT = 50

GATE_RE = re.compile(r"(?<!\d)(401|402)(?!\d)")
WIFI_LABEL = "WiFi"
MAKEUP_LABEL = "补卡"
KNOWN_CHECKIN_DEVICE_LABELS = {"401", "402", WIFI_LABEL, MAKEUP_LABEL}
GATE_CANDIDATE_FIELDS = (
	"deviceName",
	"device_name",
	"deviceNick",
	"deviceLabel",
	"terminalName",
	"terminal_name",
	"locationName",
	"deviceId",
	"deviceSN",
)

TIME_RESULT_LABELS = {
	"Normal": "正常",
	"Late": "迟到",
	"SeriousLate": "严重迟到",
	"Early": "早退",
	"Absenteeism": "旷工",
	"Leave": "请假",
	"NotSigned": "缺卡",
	"NotSignedIn": "缺卡",
	"NotSignedOff": "缺卡",
}

MISSING_TIME_RESULTS = {"NotSigned", "NotSignedIn", "NotSignedOff"}


def _new_stat():
	return frappe._dict(
		api_calls=0,
		created_attendance=0,
		updated_draft_attendance=0,
		amended_attendance=0,
		unchanged_attendance=0,
		created_checkins=0,
		skipped_duplicate_checkins=0,
		skipped_locked_attendance=0,
		unmatched_user_ids=[],
		no_structure=[],
		missing_gate_device_samples=[],
		updated_checkin_device_ids=0,
		group_name_api_calls=0,
		group_name_lookup_errors=[],
		leave_api_calls=0,
		leave_lookup_errors=[],
		skipped_leave_lookup_user_ids=[],
		ambiguous_leave_dates=[],
		paid_leave_api_calls=0,
		paid_leave_lookup_errors=[],
	)


def _merge_stat(target, source):
	for key, value in source.items():
		if isinstance(value, list):
			target.setdefault(key, [])
			target[key].extend(value)
		elif isinstance(value, (int, float)):
			target[key] = target.get(key, 0) + value
		else:
			target[key] = value
	return target


def _as_list(value):
	if not value:
		return []
	if isinstance(value, str):
		try:
			parsed = frappe.parse_json(value)
			return parsed if isinstance(parsed, list) else [value]
		except Exception:
			return [value]
	return value if isinstance(value, list) else list(value)


def _split_mapping_values(value):
	text = str(value or "")
	return {item.strip() for item in re.split(r"[\s,，;；|]+", text) if item.strip()}


def _chunked(values, size):
	values = list(values)
	for start in range(0, len(values), size):
		yield values[start : start + size]


def _date_windows(from_date, to_date, max_days=MAX_DAYS_PER_CALL):
	current = getdate(from_date)
	end = getdate(to_date)
	while current <= end:
		window_end = min(add_days(current, max_days - 1), end)
		yield current, window_end
		current = add_days(window_end, 1)


def _format_api_datetime(date_value, end_of_day=False):
	suffix = "23:59:59" if end_of_day else "00:00:00"
	return f"{getdate(date_value)} {suffix}"


def _datetime_from_dingtalk_ms(value):
	if value in (None, "", 0, "0"):
		return None
	try:
		ms = int(value)
	except (TypeError, ValueError):
		return None
	utc_dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
	return convert_utc_to_system_timezone(utc_dt).replace(tzinfo=None, microsecond=0)


def _record_user_id(record):
	return str(record.get("userId") or record.get("user_id") or record.get("userid") or "").strip()


def _check_type_to_log_type(check_type):
	check_type = str(check_type or "")
	if check_type in {"OnDuty", "On", "上班"} or "OnDuty" in check_type or "上班" in check_type:
		return "IN"
	if check_type in {"OffDuty", "Off", "下班"} or "OffDuty" in check_type or "下班" in check_type:
		return "OUT"
	return None


def _is_on_duty(check_type):
	return _check_type_to_log_type(check_type) == "IN"


def _is_off_duty(check_type):
	return _check_type_to_log_type(check_type) == "OUT"


def _is_late_result(time_result):
	text = str(time_result or "").lower()
	return "late" in text or "迟到" in text


def _is_early_result(time_result):
	text = str(time_result or "").lower()
	return "early" in text or "早退" in text


def _is_absent_or_missing_result(time_result):
	text = str(time_result or "").lower()
	return any(key in text for key in ("absent", "notsigned", "not signed", "旷工", "缺卡"))


def _is_missing_result(time_result):
	text = str(time_result or "")
	return text in MISSING_TIME_RESULTS or "notsigned" in text.lower() or "缺卡" in text


def _is_leave_result(time_result):
	text = str(time_result or "")
	return "leave" in text.lower() or "请假" in text


def _hhmm(dt):
	return dt.strftime("%H:%M") if dt else None


def _record_group_id(record):
	value = record.get("groupId") or record.get("group_id") or record.get("groupid")
	return str(value).strip() if value not in (None, "") else ""


def _record_sort_dt(record):
	return (
		_datetime_from_dingtalk_ms(record.get("baseCheckTime"))
		or _datetime_from_dingtalk_ms(record.get("planCheckTime"))
		or _datetime_from_dingtalk_ms(record.get("userCheckTime"))
		or _datetime_from_dingtalk_ms(record.get("workDate"))
		or datetime.min
	)


def _configured_gate_device_map(settings=None):
	if not settings:
		return {}
	device_map = {}
	for raw in _split_mapping_values(settings.get("gate_401_device_ids")):
		device_map[raw] = "401"
	for raw in _split_mapping_values(settings.get("gate_402_device_ids")):
		device_map[raw] = "402"
	for raw in _split_mapping_values(settings.get("wifi_device_ids")):
		device_map[raw] = WIFI_LABEL
	return device_map


def _is_wifi_record(record):
	for fieldname in ("locationMethod", "sourceType", "source_type", "deviceName", "device_name"):
		text = str(record.get(fieldname) or "").strip().lower()
		if text in {"wifi", "wi-fi"} or "wifi" in text or "wi-fi" in text or "无线" in text:
			return True
	return False


def _is_makeup_record(record):
	for fieldname, value in record.items():
		if not value:
			continue
		field_text = str(fieldname or "").lower()
		value_text = str(value or "").strip()
		value_lower = value_text.lower()
		if "补卡" in value_text:
			return True
		if "approve" in field_text and value_text:
			return True
		if any(token in value_lower for token in ("approve", "approval", "correction", "makeup")):
			return True
	return False


def _configured_paid_leave_names(settings=None):
	return _paid_leave_names(settings)


def _configured_sync_leave_names(settings=None):
	params = _load_attendance_params()
	names = list(params.get("sync_leave_names") or [])
	for name in _configured_paid_leave_names(settings):
		if name not in names:
			names.append(name)
	return names


def _configured_hour_based_leave_names():
	return list(_load_attendance_params().get("hour_based_leave_names") or [])


def _leave_name_batches(leave_names):
	batches = []
	current = []
	current_length = 0
	seen = set()
	for raw_name in leave_names or []:
		name = str(raw_name or "").strip()
		if not name or name in seen:
			continue
		if len(name) > LEAVE_NAMES_MAX_LENGTH:
			frappe.throw(_("单个钉钉请假名称不能超过 {0} 个字符：{1}").format(LEAVE_NAMES_MAX_LENGTH, name))
		added_length = len(name) + (1 if current else 0)
		if current and current_length + added_length > LEAVE_NAMES_MAX_LENGTH:
			batches.append(current)
			current = []
			current_length = 0
		current.append(name)
		seen.add(name)
		current_length += len(name) + (1 if len(current) > 1 else 0)
	if current:
		batches.append(current)
	return batches


def extract_gate_device_label(record, gate_device_map=None):
	"""从钉钉打卡详情 payload 提取 401/402 门名、WiFi 或补卡；找不到则不写原始 ID/SN。"""
	if _is_makeup_record(record):
		return MAKEUP_LABEL
	if _is_wifi_record(record):
		return WIFI_LABEL
	for fieldname in GATE_CANDIDATE_FIELDS:
		value = record.get(fieldname)
		if not value:
			continue
		text = str(value).strip()
		match = GATE_RE.search(text)
		if match:
			return match.group(1)
		if gate_device_map and text in gate_device_map:
			return gate_device_map[text]
	return None


def _gate_sample(record):
	check_dt = _datetime_from_dingtalk_ms(record.get("userCheckTime"))
	sample = {
		"userId": _record_user_id(record),
		"checkTime": str(check_dt) if check_dt else None,
		"checkType": record.get("checkType"),
	}
	sample.update({
		fieldname: record.get(fieldname)
		for fieldname in GATE_CANDIDATE_FIELDS
		if record.get(fieldname)
	})
	return {key: value for key, value in sample.items() if value}


def _existing_checkin_name(employee, check_dt, log_type, device_id=None, match_device=True):
	conditions = ["employee=%s", "`time`=%s"]
	params = [employee, check_dt]
	if log_type:
		conditions.append("log_type=%s")
		params.append(log_type)
	else:
		conditions.append("(log_type is null or log_type='')")

	if match_device:
		if device_id:
			conditions.append("device_id=%s")
			params.append(device_id)
		else:
			conditions.append("(device_id is null or device_id='')")

	rows = frappe.db.sql(
		f"""select name from `tabEmployee Checkin`
		where {' and '.join(conditions)}
		limit 1""",
		params,
		as_dict=True,
	)
	return rows[0].name if rows else None


def _existing_checkin_device_id(employee, check_dt, log_type):
	conditions = ["employee=%s", "`time`=%s"]
	params = [employee, check_dt]
	if log_type:
		conditions.append("log_type=%s")
		params.append(log_type)
	else:
		conditions.append("(log_type is null or log_type='')")

	rows = frappe.db.sql(
		f"""select name, device_id from `tabEmployee Checkin`
		where {' and '.join(conditions)}
		order by
			case when device_id in ('401', '402', 'WiFi') then 0 else 1 end,
			creation desc
		limit 1""",
		params,
		as_dict=True,
	)
	return rows[0] if rows else None


def _employee_map(employee_names=None):
	filters = {"status": "Active"}
	names = _as_list(employee_names)
	if names:
		filters["name"] = ["in", names]
	rows = frappe.get_all(
		"Employee",
		filters=filters,
		fields=["name", "employee_name", "attendance_device_id", "company"],
	)
	rows = [row for row in rows if row.attendance_device_id]
	return {str(row.attendance_device_id).strip(): row.name for row in rows}, rows


def _company_for(employee, default_company=None):
	return default_company or frappe.db.get_value("Employee", employee, "company")


def _attendance_values_equal(doc, values):
	for fieldname in (
		"status",
		"late_entry",
		"early_exit",
		"custom_dingtalk_leave_name",
		"custom_dingtalk_scheduled_in_time",
		"custom_dingtalk_scheduled_out_time",
	):
		if str(doc.get(fieldname) or "") != str(values.get(fieldname) or ""):
			return False
	if _summary_body(doc.get("custom_punch_summary")) != _summary_body(values.get("custom_punch_summary")):
		return False
	for fieldname in ("in_time", "out_time"):
		doc_value = get_datetime(doc.get(fieldname)).replace(microsecond=0) if doc.get(fieldname) else None
		new_value = get_datetime(values.get(fieldname)).replace(microsecond=0) if values.get(fieldname) else None
		if doc_value != new_value:
			return False
	for fieldname in (
		"custom_overtime_days",
		"custom_dingtalk_paid_leave_days",
		"custom_dingtalk_unpaid_leave_days",
		"custom_actual_attendance_days",
		"custom_meal_allowance_days",
		"custom_late_minutes",
		"custom_early_minutes",
	):
		if flt(doc.get(fieldname), 6) != flt(values.get(fieldname), 6):
			return False
	return True


def _summary_body(summary):
	text = str(summary or "")
	return text.split(":", 1)[1] if ":" in text else text


def _submit_new_attendance(employee, attendance_date, company, values, amended_from=None):
	doc = frappe.get_doc(
		{
			"doctype": "Attendance",
			"employee": employee,
			"attendance_date": attendance_date,
			"company": company,
			"amended_from": amended_from,
			**values,
		}
	)
	doc.flags.ignore_validate = True
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc


def _sync_attendance_with_amend(employee, attendance_date, company, values, force_locked=False):
	existing_name = frappe.db.exists(
		"Attendance",
		{"employee": employee, "attendance_date": str(attendance_date), "docstatus": ["<", 2]},
	)
	if not existing_name:
		_submit_new_attendance(employee, attendance_date, company, values)
		return "created_attendance"

	existing = frappe.get_doc("Attendance", existing_name)
	if cint(existing.get("custom_dingtalk_sync_locked")) and not force_locked:
		return "skipped_locked_attendance"
	if _attendance_values_equal(existing, values):
		return "unchanged_attendance"

	if existing.docstatus == 0:
		existing.update(values)
		existing.flags.ignore_validate = True
		existing.save(ignore_permissions=True)
		existing.submit()
		return "updated_draft_attendance"

	existing.flags.ignore_permissions = True
	existing.cancel()
	_submit_new_attendance(employee, attendance_date, company, values, amended_from=existing.name)
	return "amended_attendance"


def _aggregate_result_records(records):
	grouped = defaultdict(list)
	for record in records:
		user_id = _record_user_id(record)
		work_dt = _datetime_from_dingtalk_ms(record.get("workDate"))
		check_dt = _datetime_from_dingtalk_ms(record.get("userCheckTime"))
		if not user_id:
			continue
		date_value = getdate(work_dt or check_dt) if (work_dt or check_dt) else None
		if not date_value:
			continue
		grouped[(user_id, date_value)].append(record)
	return grouped


def _attendance_source_label(records, group_name_map=None):
	group_name_map = group_name_map or {}
	for record in records:
		group_name = group_name_map.get(_record_group_id(record))
		if group_name:
			return group_name
	return "钉钉API"


def _build_attendance_values(employee, attendance_date, records, group_name_map=None, leave_info=None):
	actual_times = []
	on_times = []
	off_times = []
	scheduled_on_times = []
	scheduled_off_times = []
	punch_parts = []
	late = False
	early = False
	absent_or_missing = False
	has_leave_result = False
	result_labels = []

	for record in sorted(records, key=_record_sort_dt):
		check_dt = _datetime_from_dingtalk_ms(record.get("userCheckTime"))
		scheduled_dt = _datetime_from_dingtalk_ms(record.get("baseCheckTime")) or _datetime_from_dingtalk_ms(
			record.get("planCheckTime")
		)
		time_result = record.get("timeResult")
		check_type = record.get("checkType")
		is_missing = _is_missing_result(time_result)
		label = _time_result_label(time_result)
		if label and label not in result_labels:
			result_labels.append(label)
		if _is_leave_result(time_result):
			has_leave_result = True
		if _is_late_result(time_result) and _is_on_duty(check_type):
			late = True
		if _is_early_result(time_result) and _is_off_duty(check_type):
			early = True
		if _is_absent_or_missing_result(time_result):
			absent_or_missing = True
		if scheduled_dt:
			if _is_on_duty(check_type):
				scheduled_on_times.append(scheduled_dt)
			elif _is_off_duty(check_type):
				scheduled_off_times.append(scheduled_dt)
		if is_missing:
			punch_parts.append("-")
			continue
		if not check_dt:
			continue
		punch_parts.append(_hhmm(check_dt))
		actual_times.append(check_dt)
		if _is_on_duty(check_type):
			on_times.append(check_dt)
		elif _is_off_duty(check_type):
			off_times.append(check_dt)

	if on_times or off_times:
		in_time = min(on_times) if on_times else None
		out_time = max(off_times) if off_times else None
	else:
		in_time = min(actual_times) if actual_times else None
		out_time = max(actual_times) if actual_times else None

	leave_info = leave_info or frappe._dict()
	paid_leave_days = flt(leave_info.get("paid_days"))
	unpaid_leave_days = flt(leave_info.get("unpaid_days"))
	leave_name = str(leave_info.get("leave_name") or "").strip()
	if has_leave_result and not (paid_leave_days or unpaid_leave_days):
		unpaid_leave_days = 0.5 if actual_times else 1.0
		leave_name = leave_name or "请假"
	leave_days = paid_leave_days + unpaid_leave_days

	structure = _employee_structure(employee, attendance_date)
	is_regular = structure == REGULAR_WORKER_STRUCTURE
	profile = _schedule_profile_for(is_regular)

	# 无薪假完整双卡只按迟到/早退分钟结算；单边卡仍缺勤，等待员工补卡。
	both_punches = _has_complete_punches(in_time, out_time)
	if paid_leave_days:
		status = "Half Day" if actual_times and paid_leave_days < 1 else "On Leave"
		actual_attendance_days = max(0.0, 1.0 - min(paid_leave_days, 1.0)) if actual_times else 0.0
	elif unpaid_leave_days and both_punches:
		status = "Present"
		actual_attendance_days = 1.0
	elif unpaid_leave_days:
		status = "On Leave" if unpaid_leave_days >= 1 and not actual_times else "Absent"
		actual_attendance_days = 0.0
	elif both_punches:
		status = "Present"
		actual_attendance_days = 1.0
	else:
		status = "Absent"
		actual_attendance_days = 0.0
	scheduled_in_time = _time_string_from_value(
		min(scheduled_on_times) if scheduled_on_times else None
	) or _minutes_to_time_string(profile.work_start)
	scheduled_out_time = _time_string_from_value(
		max(scheduled_off_times) if scheduled_off_times else None
	) or _minutes_to_time_string(profile.work_end)
	meal_days = _meal_allowance_days_for_attendance(
		is_regular=is_regular,
		actual_attendance_days=actual_attendance_days,
		leave_days=leave_days,
		in_time=in_time,
		out_time=out_time,
		profile=profile,
	)
	minute_factors = calculate_late_early_minutes(
		in_time=in_time,
		out_time=out_time,
		scheduled_in=scheduled_in_time,
		scheduled_out=scheduled_out_time,
		has_leave=_leave_suppresses_minutes(
			paid_leave_days,
			unpaid_leave_days,
			in_time,
			out_time,
		),
		profile=profile,
	)
	overtime_days = daily_overtime_days(_hhmm(out_time), status == "Absent", is_regular)
	result_text = _attendance_result_text(result_labels) or status
	if leave_days:
		leave_label = leave_name or "请假"
		result_text = f"{leave_label}、出勤" if actual_times else leave_label
	source_label = _attendance_source_label(records, group_name_map=group_name_map)
	punch_summary = (
		f"{source_label}:{result_text} ({','.join(punch_parts)})"
		if punch_parts
		else f"{source_label}:{result_text or '缺卡/旷工'}"
	)

	return {
		"status": status,
		"in_time": in_time,
		"out_time": out_time,
		"late_entry": 1 if late or minute_factors.late_minutes else 0,
		"early_exit": 1 if early or minute_factors.early_minutes else 0,
		"custom_punch_summary": punch_summary,
		"custom_overtime_days": overtime_days,
		"custom_dingtalk_leave_name": leave_name,
		"custom_dingtalk_paid_leave_days": paid_leave_days,
		"custom_dingtalk_unpaid_leave_days": unpaid_leave_days,
		"custom_actual_attendance_days": actual_attendance_days,
		"custom_meal_allowance_days": meal_days,
		"custom_dingtalk_scheduled_in_time": scheduled_in_time,
		"custom_dingtalk_scheduled_out_time": scheduled_out_time,
		"custom_late_minutes": minute_factors.late_minutes,
		"custom_early_minutes": minute_factors.early_minutes,
		"leave_type": None,
		"leave_application": None,
		"half_day_status": None,
	}


def _attendance_result_text(result_labels):
	labels = [label for label in result_labels if label]
	if "正常" in labels:
		non_normal_labels = [label for label in labels if label != "正常"]
		if non_normal_labels:
			if len(non_normal_labels) == 1 and non_normal_labels[0] == "缺卡":
				return "缺卡、出勤"
			return "、".join(non_normal_labels)
	return "、".join(labels)


def sync_result_records(
	records,
	employee_map,
	default_company=None,
	force_locked=False,
	group_name_map=None,
	leave_time_map=None,
):
	"""把“获取打卡结果”返回记录写入 Attendance。用于测试和 API 主流程。"""
	stat = _new_stat()
	leave_time_map = leave_time_map or {}
	for (user_id, attendance_date), day_records in _aggregate_result_records(records).items():
		employee = employee_map.get(user_id)
		if not employee:
			stat.unmatched_user_ids.append(user_id)
			continue
		structure = _employee_structure(employee, attendance_date)
		if not structure:
			stat.no_structure.append(employee)
		leave_info = _normalize_leave_info(
			employee,
			attendance_date,
			leave_time_map.get((user_id, attendance_date)),
			is_regular=structure == REGULAR_WORKER_STRUCTURE,
		)
		paid_days = flt((leave_info or {}).get("paid_days"))
		unpaid_days = flt((leave_info or {}).get("unpaid_days"))
		if (paid_days and unpaid_days) or paid_days + unpaid_days > 1.0001:
			stat.ambiguous_leave_dates.append(
				{
					"user_id": user_id,
					"employee": employee,
					"attendance_date": str(attendance_date),
					"leave_name": (leave_info or {}).get("leave_name"),
					"paid_days": paid_days,
					"unpaid_days": unpaid_days,
				}
			)
			continue
		values = _build_attendance_values(
			employee,
			attendance_date,
			day_records,
			group_name_map=group_name_map,
			leave_info=leave_info,
		)
		key = _sync_attendance_with_amend(
			employee,
			attendance_date,
			_company_for(employee, default_company),
			values,
			force_locked=force_locked,
		)
		stat[key] += 1
	return stat


def _time_result_label(time_result):
	if not time_result:
		return ""
	text = str(time_result)
	return TIME_RESULT_LABELS.get(text, text)


def sync_checkin_records(records, employee_map, gate_device_map=None):
	"""把“获取打卡详情”返回记录写入 Employee Checkin。"""
	stat = _new_stat()
	for record in records:
		user_id = _record_user_id(record)
		employee = employee_map.get(user_id)
		if not employee:
			stat.unmatched_user_ids.append(user_id)
			continue

		check_dt = _datetime_from_dingtalk_ms(record.get("userCheckTime"))
		if not check_dt:
			continue
		log_type = _check_type_to_log_type(record.get("checkType"))
		device_id = extract_gate_device_label(record, gate_device_map=gate_device_map)
		if not device_id:
			existing_checkin = _existing_checkin_device_id(employee, check_dt, log_type)
			if existing_checkin and existing_checkin.get("device_id") in KNOWN_CHECKIN_DEVICE_LABELS:
				stat.skipped_duplicate_checkins += 1
				continue
			sample = _gate_sample(record)
			if sample and sample not in stat.missing_gate_device_samples:
				stat.missing_gate_device_samples.append(sample)

		if device_id:
			existing_name = _existing_checkin_name(employee, check_dt, log_type, device_id)
			if existing_name:
				stat.skipped_duplicate_checkins += 1
				continue
			blank_existing_name = _existing_checkin_name(employee, check_dt, log_type)
			if blank_existing_name:
				frappe.db.set_value(
					"Employee Checkin",
					blank_existing_name,
					"device_id",
					device_id,
					update_modified=False,
				)
				stat.updated_checkin_device_ids += 1
				stat.skipped_duplicate_checkins += 1
				continue
			if _existing_checkin_name(employee, check_dt, log_type, match_device=False):
				stat.skipped_duplicate_checkins += 1
				continue
		elif _existing_checkin_name(employee, check_dt, log_type, match_device=False):
			stat.skipped_duplicate_checkins += 1
			continue

		doc = frappe.get_doc(
			{
				"doctype": "Employee Checkin",
				"employee": employee,
				"time": check_dt,
				"log_type": log_type,
				"device_id": device_id,
				"skip_auto_attendance": 1,
				"latitude": record.get("latitude") or record.get("lat"),
				"longitude": record.get("longitude") or record.get("lng"),
			}
		)
		doc.insert(ignore_permissions=True)
		stat.created_checkins += 1
	return stat


def _collect_group_names(client, records, group_name_map, stat):
	for record in records:
		group_id = _record_group_id(record)
		user_id = _record_user_id(record)
		if not group_id or group_id in group_name_map:
			continue
		name, calls, error = client.get_attendance_group_name(group_id, user_id)
		stat.api_calls += calls
		stat.group_name_api_calls += calls
		if name:
			group_name_map[group_id] = name
		elif error and error not in stat.group_name_lookup_errors:
			stat.group_name_lookup_errors.append(error)
	return group_name_map


def _collect_leave_times(
	client,
	user_ids,
	from_date,
	to_date,
	leave_names,
	stat,
	hour_based_leave_names=None,
):
	leave_time_map = {}
	failed_user_ids = []
	batches = _leave_name_batches(leave_names)
	if not batches:
		return leave_time_map, failed_user_ids
	for user_id in user_ids:
		user_leave_time_map = {}
		failed = False
		for batch in batches:
			try:
				result, calls = client.list_leave_time_by_names(user_id, batch, from_date, to_date)
				stat.api_calls += calls
				stat.leave_api_calls += calls
				stat.paid_leave_api_calls += calls
			except Exception as exc:
				frappe.log_error(
					title="Dingtalk Leave Lookup Failed",
					message=frappe.get_traceback(),
				)
				error = f"{user_id}: {str(exc)[:120]}"
				if error not in stat.leave_lookup_errors:
					stat.leave_lookup_errors.append(error)
				if error not in stat.paid_leave_lookup_errors:
					stat.paid_leave_lookup_errors.append(error)
				failed = True
				break
			_merge_leave_time_map(
				user_leave_time_map,
				user_id,
				result,
				hour_based_leave_names=hour_based_leave_names,
			)
		if failed:
			failed_user_ids.append(str(user_id))
			if str(user_id) not in stat.skipped_leave_lookup_user_ids:
				stat.skipped_leave_lookup_user_ids.append(str(user_id))
			continue
		for key, info in user_leave_time_map.items():
			target = leave_time_map.setdefault(
				key,
				frappe._dict(
					leave_name="",
					paid_days=0.0,
					unpaid_days=0.0,
					paid_hours=0.0,
					unpaid_hours=0.0,
				),
			)
			target.leave_name = info.leave_name
			target.paid_days += info.paid_days
			target.unpaid_days += info.unpaid_days
			target.paid_hours += info.paid_hours
			target.unpaid_hours += info.unpaid_hours
	return leave_time_map, failed_user_ids


def _merge_leave_time_map(target, user_id, result, hour_based_leave_names=None):
	hour_based_leave_names = set(hour_based_leave_names or [])
	for column in (result.get("columns") or []):
		column_info = column.get("columnvo") or {}
		leave_name = str(column_info.get("name") or "").strip()
		if not leave_name:
			continue
		for value_row in column.get("columnvals") or []:
			amount = flt(value_row.get("value"))
			if not amount:
				continue
			date_value = getdate(value_row.get("date"))
			key = (str(user_id), date_value)
			info = target.setdefault(
				key,
				frappe._dict(
					leave_name="",
					paid_days=0.0,
					unpaid_days=0.0,
					paid_hours=0.0,
					unpaid_hours=0.0,
				),
			)
			info.leave_name = "、".join([name for name in (info.leave_name, leave_name) if name])
			is_paid = is_paid_dingtalk_leave(leave_name)
			if leave_name in hour_based_leave_names:
				fieldname = "paid_hours" if is_paid else "unpaid_hours"
			else:
				fieldname = "paid_days" if is_paid else "unpaid_days"
			info[fieldname] += amount


def _normalize_leave_info(employee, attendance_date, leave_info, is_regular=None):
	if not leave_info:
		return frappe._dict()
	paid_days = flt(leave_info.get("paid_days"))
	unpaid_days = flt(leave_info.get("unpaid_days"))
	paid_hours = flt(leave_info.get("paid_hours"))
	unpaid_hours = flt(leave_info.get("unpaid_hours"))
	if not (paid_hours or unpaid_hours):
		return frappe._dict(leave_name=leave_info.get("leave_name"), paid_days=paid_days, unpaid_days=unpaid_days)
	if is_regular is None:
		is_regular = _employee_structure(employee, attendance_date) == REGULAR_WORKER_STRUCTURE
	profile = _schedule_profile_for(is_regular)
	daily_hours = flt(profile.daily_hours)
	if daily_hours <= 0:
		frappe.throw(_("排班档案的日工作小时必须大于 0，无法换算按小时统计的请假。"))
	return frappe._dict(
		leave_name=leave_info.get("leave_name"),
		paid_days=paid_days + paid_hours / daily_hours,
		unpaid_days=unpaid_days + unpaid_hours / daily_hours,
	)


class DingtalkAttendanceClient:
	def __init__(self, app_key, app_secret, timeout=20, result_limit=DEFAULT_RESULT_LIMIT):
		self.app_key = app_key
		self.app_secret = app_secret
		self.timeout = cint(timeout) or 20
		self.result_limit = min(cint(result_limit) or DEFAULT_RESULT_LIMIT, DEFAULT_RESULT_LIMIT)
		self.session = requests.Session()

	def get_access_token(self):
		cache_key = f"fwb_utils:dingtalk_attendance:access_token:{self.app_key}"
		cached = frappe.cache().get_value(cache_key)
		if cached:
			return cached

		response = self.session.post(
			ACCESS_TOKEN_URL,
			json={"appKey": self.app_key, "appSecret": self.app_secret},
			timeout=self.timeout,
		)
		data = _safe_json(response)
		if response.status_code >= 400 or not data.get("accessToken"):
			frappe.throw(_("钉钉 accessToken 获取失败，请检查 AppKey/AppSecret 与应用权限。"))
		token = data["accessToken"]
		expires_in = max(cint(data.get("expireIn") or 7200) - 300, 60)
		frappe.cache().set_value(cache_key, token, expires_in_sec=expires_in)
		return token

	def _post_oapi(self, url, payload):
		token = self.get_access_token()
		response = self.session.post(
			url,
			params={"access_token": token},
			json=payload,
			timeout=self.timeout,
		)
		data = _safe_json(response)
		errcode = cint(data.get("errcode")) if "errcode" in data else 0
		if response.status_code >= 400 or errcode:
			errmsg = data.get("errmsg") or data.get("message") or response.text[:200]
			frappe.throw(_("钉钉考勤 API 调用失败：{0}").format(errmsg))
		return data

	def list_attendance_results(self, user_ids, from_date, to_date):
		records = []
		calls = 0
		offset = 0
		while True:
			payload = {
				"workDateFrom": _format_api_datetime(from_date),
				"workDateTo": _format_api_datetime(to_date, end_of_day=True),
				"userIdList": list(user_ids),
				"offset": offset,
				"limit": self.result_limit,
				"isI18n": False,
			}
			data = self._post_oapi(ATTENDANCE_RESULT_URL, payload)
			calls += 1
			page_records = data.get("recordresult") or data.get("recordResult") or []
			records.extend(page_records)
			if not data.get("hasMore"):
				break
			offset += self.result_limit
		return records, calls

	def list_attendance_details(self, user_ids, from_date, to_date):
		payload = {
			"checkDateFrom": _format_api_datetime(from_date),
			"checkDateTo": _format_api_datetime(to_date, end_of_day=True),
			"userIds": list(user_ids),
			"isI18n": False,
		}
		data = self._post_oapi(ATTENDANCE_DETAIL_URL, payload)
		records = data.get("recordresult") or data.get("recordResult") or []
		return records, 1

	def list_leave_time_by_names(self, user_id, leave_names, from_date, to_date):
		payload = {
			"from_date": _format_api_datetime(from_date),
			"to_date": _format_api_datetime(to_date, end_of_day=True),
			"leave_names": ",".join(leave_names) if isinstance(leave_names, (list, tuple)) else str(leave_names or ""),
			"userid": user_id,
		}
		data = self._post_oapi(ATTENDANCE_LEAVE_TIME_URL, payload)
		return data.get("result") or {}, 1

	def get_attendance_group_name(self, group_id, op_user_id):
		if not group_id or not op_user_id:
			return None, 0, ""
		cache_key = f"fwb_utils:dingtalk_attendance:group_name:{group_id}"
		cached = frappe.cache().get_value(cache_key)
		if cached:
			return cached, 0, ""
		try:
			data = self._post_oapi(
				ATTENDANCE_GROUP_QUERY_URL,
				{
					"op_user_id": op_user_id,
					"group_id": cint(group_id) or group_id,
				},
			)
		except Exception as exc:
			frappe.log_error(
				title="Dingtalk Attendance Group Name Lookup Failed",
				message=frappe.get_traceback(),
			)
			return None, 1, f"{group_id}: {str(exc)[:120]}"
		name = ((data.get("result") or {}).get("name") or "").strip()
		if name:
			frappe.cache().set_value(cache_key, name, expires_in_sec=30 * 24 * 60 * 60)
		return name or None, 1, ""


def _safe_json(response):
	try:
		return response.json()
	except Exception:
		frappe.throw(_("钉钉接口返回非 JSON 响应：{0}").format(response.text[:200]))


def _get_settings():
	return frappe.get_single("Dingtalk Attendance Settings")


def _client_from_settings(settings):
	app_key = (settings.app_key or "").strip()
	app_secret = settings.get_password("app_secret") if hasattr(settings, "get_password") else settings.app_secret
	if not app_key or not app_secret:
		frappe.throw(_("请先在钉钉考勤设置配置 AppKey 和 AppSecret。"))
	return DingtalkAttendanceClient(
		app_key=app_key,
		app_secret=app_secret,
		timeout=settings.timeout_seconds,
		result_limit=settings.result_page_limit,
	)


def _require_hr_manager():
	if frappe.session.user == "Administrator":
		return
	roles = set(frappe.get_roles())
	if not ({"System Manager", "HR Manager"} & roles):
		frappe.throw(_("只有 System Manager 或 HR Manager 可以同步钉钉考勤。"), frappe.PermissionError)


def _require_system_manager():
	if frappe.session.user == "Administrator":
		return
	roles = set(frappe.get_roles())
	if "System Manager" not in roles:
		frappe.throw(_("只有 System Manager 可以重算考勤结算字段。"), frappe.PermissionError)


def _month_bounds(month):
	month_text = str(month or "").strip()
	if not re.fullmatch(r"\d{4}-\d{2}", month_text):
		frappe.throw(_("月份必须使用 YYYY-MM 格式。"))
	from_date = getdate(f"{month_text}-01")
	return month_text, from_date, get_last_day(from_date)


def _normalize_scope(scope):
	scope = str(scope or "").strip()
	aliases = {
		"employee": "指定员工",
		"employees": "指定员工",
		"department": "指定部门",
		"all": "全员",
	}
	scope = aliases.get(scope.lower(), scope)
	if scope not in {"指定员工", "指定部门", "全员"}:
		frappe.throw(_("重算范围必须是：指定员工、指定部门、全员。"))
	return scope


def _normalize_employee_names(employees):
	values = _as_list(employees)
	names = []
	for value in values:
		if isinstance(value, dict):
			value = value.get("value") or value.get("name") or value.get("employee")
		for part in re.split(r"[,，\n]+", str(value or "")):
			name = part.strip()
			if name and name not in names:
				names.append(name)
	return names


def _attendance_rows_for_recalculation(month, scope, employees=None, department=None):
	month_text, from_date, to_date = _month_bounds(month)
	scope = _normalize_scope(scope)
	params = {"from_date": from_date, "to_date": to_date}
	conditions = [
		"a.docstatus = 1",
		"a.attendance_date between %(from_date)s and %(to_date)s",
		"e.status = 'Active'",
	]

	if scope == "指定员工":
		employee_names = _normalize_employee_names(employees)
		if not employee_names:
			frappe.throw(_("请选择需要重算的员工。"))
		conditions.append("a.employee in %(employees)s")
		params["employees"] = tuple(employee_names)
	elif scope == "指定部门":
		if not department:
			frappe.throw(_("请选择需要重算的部门。"))
		department_names = department_filter_names(department)
		conditions.append("e.department in %(departments)s")
		params["departments"] = tuple(department_names or [department])

	rows = frappe.db.sql(
		"""
		select
			a.name,
			a.employee,
			e.employee_name,
			e.department,
			a.attendance_date,
			a.status,
			a.in_time,
			a.out_time,
			a.custom_actual_attendance_days,
			a.custom_overtime_days,
			a.custom_meal_allowance_days,
			a.custom_dingtalk_paid_leave_days,
			a.custom_dingtalk_unpaid_leave_days,
			a.custom_dingtalk_scheduled_in_time,
			a.custom_dingtalk_scheduled_out_time,
			a.custom_late_minutes,
			a.custom_early_minutes,
			a.custom_dingtalk_sync_locked
		from `tabAttendance` a
		inner join `tabEmployee` e on e.name = a.employee
		where {conditions}
		order by a.attendance_date, e.employee_name, a.name
		""".format(conditions=" and ".join(conditions)),
		params,
		as_dict=True,
	)
	return month_text, from_date, to_date, rows


def _actual_attendance_days_from_row(row):
	if row.custom_actual_attendance_days is not None:
		return flt(row.custom_actual_attendance_days)
	if row.status == "Present":
		return 1.0
	if row.status == "Half Day":
		return 0.5
	return 0.0


def _recalculated_meal_days(row, is_regular):
	leave_days = flt(row.custom_dingtalk_paid_leave_days) + flt(row.custom_dingtalk_unpaid_leave_days)
	profile = _schedule_profile_for(False)
	actual_attendance_days = _actual_attendance_days_from_row(row)
	if flt(row.custom_dingtalk_unpaid_leave_days) and not flt(row.custom_dingtalk_paid_leave_days):
		if _has_complete_punches(row.in_time, row.out_time):
			actual_attendance_days = 1.0
	return _meal_allowance_days_for_attendance(
		is_regular=is_regular,
		actual_attendance_days=actual_attendance_days,
		leave_days=leave_days,
		in_time=row.in_time,
		out_time=row.out_time,
		profile=profile,
	)


def _attendance_payroll_recalculation(row):
	structure = _employee_structure(row.employee, row.attendance_date)
	is_regular = structure == REGULAR_WORKER_STRUCTURE
	overtime_days = daily_overtime_days(_hhmm(row.out_time), row.status == "Absent", is_regular)
	meal_days = _recalculated_meal_days(row, is_regular)
	# 迟到/早退分钟：按存量打卡 + 排班 + 当前起扣阈值重算，使「改阈值 → 点重算按钮」即可生效，
	# 不必重新同步钉钉。仅带薪假（年假/丧假）抑制分钟；无薪假/事假/普通早退一律按实际分钟扣
	# （口径见设计文档 §7.6.3；与 calculate_late_early_minutes 同函数，保证与同步口径一致）。
	profile = _schedule_profile_for(is_regular)
	threshold = _load_attendance_params().deduction_threshold_minutes
	minute_factors = calculate_late_early_minutes(
		in_time=_hhmm(row.in_time),
		out_time=_hhmm(row.out_time),
		scheduled_in=row.custom_dingtalk_scheduled_in_time,
		scheduled_out=row.custom_dingtalk_scheduled_out_time,
		has_leave=_leave_suppresses_minutes(
			row.custom_dingtalk_paid_leave_days,
			row.custom_dingtalk_unpaid_leave_days,
			row.in_time,
			row.out_time,
		),
		profile=profile,
		threshold=threshold,
	)
	return frappe._dict(
		structure=structure,
		is_regular=is_regular,
		overtime_days=flt(overtime_days),
		meal_allowance_days=flt(meal_days),
		late_minutes=flt(minute_factors.late_minutes),
		early_minutes=flt(minute_factors.early_minutes),
	)


def _attendance_payroll_fields_changed(row, values):
	return (
		abs(flt(row.custom_overtime_days) - flt(values.overtime_days)) > 0.0001
		or abs(flt(row.custom_meal_allowance_days) - flt(values.meal_allowance_days)) > 0.0001
		or abs(flt(row.custom_late_minutes) - flt(values.late_minutes)) > 0.0001
		or abs(flt(row.custom_early_minutes) - flt(values.early_minutes)) > 0.0001
	)


def _recalculation_sample(row, values):
	return {
		"attendance": row.name,
		"employee": row.employee,
		"employee_name": row.employee_name,
		"department": row.department,
		"attendance_date": str(getdate(row.attendance_date)),
		"salary_structure": values.structure,
		"is_regular_worker": 1 if values.is_regular else 0,
		"old_overtime_days": flt(row.custom_overtime_days),
		"new_overtime_days": flt(values.overtime_days),
		"old_meal_allowance_days": flt(row.custom_meal_allowance_days),
		"new_meal_allowance_days": flt(values.meal_allowance_days),
		"old_late_minutes": flt(row.custom_late_minutes),
		"new_late_minutes": flt(values.late_minutes),
		"old_early_minutes": flt(row.custom_early_minutes),
		"new_early_minutes": flt(values.early_minutes),
	}


def _new_recalculation_change_summary():
	return {
		fieldname: {"changed_count": 0, "old_total": 0.0, "new_total": 0.0, "delta": 0.0}
		for fieldname in ("overtime_days", "meal_allowance_days", "late_minutes", "early_minutes")
	}


def _update_recalculation_change_summary(summary, row, values):
	for fieldname in summary:
		old_value = flt(row.get(f"custom_{fieldname}"))
		new_value = flt(values.get(fieldname))
		if abs(old_value - new_value) <= 0.0001:
			continue
		field_summary = summary[fieldname]
		field_summary["changed_count"] += 1
		field_summary["old_total"] += old_value
		field_summary["new_total"] += new_value
		field_summary["delta"] = field_summary["new_total"] - field_summary["old_total"]


@frappe.whitelist()
def recalculate_attendance_payroll_fields(
	month=None,
	scope="指定员工",
	employees=None,
	department=None,
	include_locked=0,
	dry_run=1,
):
	"""重算已提交 Attendance 的工资结算字段；只处理本地数据，不调用钉钉 API。"""
	_require_system_manager()
	scope = _normalize_scope(scope)
	month_text, from_date, to_date, rows = _attendance_rows_for_recalculation(
		month,
		scope,
		employees=employees,
		department=department,
	)
	include_locked = cint(include_locked)
	dry_run = cint(dry_run)
	employee_names = {row.employee for row in rows}
	stat = frappe._dict(
		month=month_text,
		from_date=str(from_date),
		to_date=str(to_date),
		scope=scope,
		employee_count=len(employee_names),
		attendance_count=len(rows),
		changed_count=0,
		updated_count=0,
		unchanged_count=0,
		skipped_count=0,
		skipped_locked_count=0,
		sample_limit=RECALCULATION_SAMPLE_LIMIT,
		samples_truncated=False,
		change_summary=_new_recalculation_change_summary(),
		samples=[],
	)

	for row in rows:
		if cint(row.custom_dingtalk_sync_locked) and not include_locked:
			stat.skipped_count += 1
			stat.skipped_locked_count += 1
			continue

		values = _attendance_payroll_recalculation(row)
		if not _attendance_payroll_fields_changed(row, values):
			stat.unchanged_count += 1
			continue

		stat.changed_count += 1
		_update_recalculation_change_summary(stat.change_summary, row, values)
		if len(stat.samples) < RECALCULATION_SAMPLE_LIMIT:
			stat.samples.append(_recalculation_sample(row, values))

		if dry_run:
			continue

		frappe.db.set_value(
			"Attendance",
			row.name,
			{
				"custom_overtime_days": values.overtime_days,
				"custom_meal_allowance_days": values.meal_allowance_days,
				"custom_late_minutes": values.late_minutes,
				"custom_early_minutes": values.early_minutes,
			},
			update_modified=True,
		)
		stat.updated_count += 1

	stat.samples_truncated = stat.changed_count > len(stat.samples)
	return stat


@frappe.whitelist()
def sync_dingtalk_attendance(from_date=None, to_date=None, employees=None, force_locked=0):
	"""手动同步指定日期范围。employees 可传 Employee name 列表；为空则同步所有有考勤设备 ID 的员工。"""
	_require_hr_manager()
	settings = _get_settings()
	from_date = getdate(from_date) if from_date else add_days(nowdate(), -1)
	to_date = getdate(to_date) if to_date else from_date
	if to_date < from_date:
		frappe.throw(_("结束日期不能早于开始日期。"))

	employee_map, employee_rows = _employee_map(employees)
	if not employee_rows:
		frappe.throw(_("没有找到已填写考勤设备 ID 的在职员工。"))

	client = _client_from_settings(settings)
	return _sync_date_range(client, settings, from_date, to_date, employee_map, force_locked=cint(force_locked))


def _sync_date_range(client, settings, from_date, to_date, employee_map, force_locked=False):
	stat = _new_stat()
	user_ids = list(employee_map.keys())
	gate_device_map = _configured_gate_device_map(settings)
	sync_leave_names = _configured_sync_leave_names(settings)
	hour_based_leave_names = _configured_hour_based_leave_names()
	group_name_map = {}
	for window_from, window_to in _date_windows(from_date, to_date):
		for user_chunk in _chunked(user_ids, MAX_USERS_PER_CALL):
			if cint(settings.enable_result_sync):
				records, calls = client.list_attendance_results(user_chunk, window_from, window_to)
				stat.api_calls += calls
				_collect_group_names(client, records, group_name_map, stat)
				leave_time_map, failed_leave_user_ids = _collect_leave_times(
					client,
					user_chunk,
					window_from,
					window_to,
					sync_leave_names,
					stat,
					hour_based_leave_names=hour_based_leave_names,
				)
				if failed_leave_user_ids:
					failed_leave_user_ids = set(failed_leave_user_ids)
					records = [record for record in records if _record_user_id(record) not in failed_leave_user_ids]
				_merge_stat(
					stat,
					sync_result_records(
						records,
						employee_map,
						settings.default_company,
						force_locked=force_locked,
						group_name_map=group_name_map,
						leave_time_map=leave_time_map,
					),
				)
			if cint(settings.enable_detail_sync):
				records, calls = client.list_attendance_details(user_chunk, window_from, window_to)
				stat.api_calls += calls
				_merge_stat(stat, sync_checkin_records(records, employee_map, gate_device_map=gate_device_map))
	return stat


def sync_rolling_dingtalk_attendance():
	"""Scheduler 入口：每天同步最近 N 天内已结束日期，默认昨天或最近 7 天。"""
	settings = _get_settings()
	if not cint(settings.enable_auto_sync):
		return {"skipped": "auto sync disabled"}

	to_date = add_days(nowdate(), -1)
	rolling_days = max(cint(settings.rolling_days) or MAX_DAYS_PER_CALL, 1)
	from_date = add_days(to_date, -(rolling_days - 1))
	employee_map, _employee_rows = _employee_map()
	client = _client_from_settings(settings)
	return _sync_date_range(client, settings, from_date, to_date, employee_map)


def _resolve_monthly_sync_window(settings, now):
	"""纯逻辑：按设置 + 当前时间判断月度核对是否该跑，并算上个自然月范围。

	settings 用 .get 取值（Document 或 dict 均可）。返回 run/reason/from_date/to_date/target。
	不预制值：未开启、或触发日不在 1-28、或触发时不在 0-23 → run=False（安全 no-op）。"""
	if not cint(settings.get("enable_monthly_sync")):
		return frappe._dict(run=False, reason="月度同步未开启")
	day = cint(settings.get("monthly_sync_day"))
	hour = cint(settings.get("monthly_sync_hour"))
	if not (1 <= day <= 28):
		return frappe._dict(run=False, reason="月度触发日未配置(应为 1-28)")
	if not (0 <= hour <= 23):
		return frappe._dict(run=False, reason="月度触发时未配置(应为 0-23)")
	if now.day != day:
		return frappe._dict(run=False, reason=f"今天({now.day})非触发日({day})")
	if now.hour != hour:
		return frappe._dict(run=False, reason=f"当前({now.hour}时)非触发时({hour}时)")
	from_date = get_first_day(add_months(getdate(now), -1))
	to_date = get_last_day(from_date)
	target = from_date.strftime("%Y-%m")
	if str(settings.get("last_monthly_sync_for") or "") == target:
		return frappe._dict(run=False, reason=f"{target} 本月已执行")
	return frappe._dict(run=True, reason="ok", from_date=from_date, to_date=to_date, target=target)


def _collect_monthly_recipients(settings):
	"""去重收集月度通知收件人(User.name)，跳过空行。"""
	recipients = []
	for row in settings.get("monthly_sync_recipients") or []:
		user = (row.get("user") or "").strip()
		if user and user not in recipients:
			recipients.append(user)
	return recipients


def _build_monthly_sync_message(target, stat=None, error=None, now_text=None, duration=None):
	"""纯逻辑：构造月度核对站内通知的 (subject, html)。成功给明细，失败给告警。"""
	if error:
		safe = str(error).replace("<", "&lt;").replace(">", "&gt;")
		subject = f"月度考勤核对失败：{target}"
		html = (
			f"<b>月度考勤核对失败</b><br>核对月份：{target}<br>"
			f"触发时间：{now_text or ''}<br>错误：{safe}<br>详情见 Error Log。"
		)
		return subject, html
	stat = stat or {}

	def g(key):
		return cint(stat.get(key) or 0)

	created = g("created_attendance")
	amended = g("updated_draft_attendance") + g("amended_attendance")
	unmatched = stat.get("unmatched_user_ids") or []
	no_structure = stat.get("no_structure") or []
	skipped_leave_users = stat.get("skipped_leave_lookup_user_ids") or []
	ambiguous_leave_dates = stat.get("ambiguous_leave_dates") or []
	subject = f"月度考勤核对完成：{target}（新建{created} 修订{amended}）"
	rows = [
		"<b>月度考勤核对完成</b>",
		f"核对月份：{target}",
		f"触发时间：{now_text or ''}",
		f"耗时：{cint(duration or 0)} 秒",
		f"API 调用：{g('api_calls')} 次（含考勤组 {g('group_name_api_calls')} / 请假 {g('leave_api_calls')}）",
		f"新建考勤：{created}",
		f"修订考勤：{amended}（草稿 {g('updated_draft_attendance')} / 提交修订 {g('amended_attendance')}）",
		f"无变化：{g('unchanged_attendance')}",
		f"锁定跳过：{g('skipped_locked_attendance')}",
		f"新建签到流水：{g('created_checkins')}",
		f"未匹配员工：{len(unmatched)}" + (f"（{', '.join(map(str, unmatched))}）" if unmatched else ""),
		f"无SSA结构员工：{len(no_structure)}" + (f"（{', '.join(map(str, no_structure))}）" if no_structure else ""),
		f"请假查询失败跳过员工：{len(skipped_leave_users)}"
		+ (f"（{', '.join(map(str, skipped_leave_users))}）" if skipped_leave_users else ""),
		f"异常请假日期：{len(ambiguous_leave_dates)}",
	]
	return subject, "<br>".join(rows)


def _notify_monthly_sync(settings, target, stat=None, error=None, now_text=None, duration=None):
	"""给配置的收件人发月度核对站内通知。收件人空=不发；逐人 try/except 互不影响、不影响同步。"""
	recipients = _collect_monthly_recipients(settings)
	if not recipients:
		return 0
	subject, html = _build_monthly_sync_message(target, stat=stat, error=error, now_text=now_text, duration=duration)
	sent = 0
	for user in recipients:
		try:
			note = frappe.new_doc("Notification Log")
			note.subject = subject
			note.email_content = html
			note.for_user = user
			note.type = "Alert"
			note.insert(ignore_permissions=True)
			sent += 1
		except Exception:
			frappe.log_error(frappe.get_traceback(), "月度核对站内通知失败")
	return sent


def sync_monthly_dingtalk_attendance():
	"""Scheduler hourly 入口：到配置的(日,时)时，整月核对上个自然月、全员（只刷新 Attendance），并给收件人发站内通知。

	每小时触发，未开启/未到点/本月已执行均立即 no-op、不调 API。锁定考勤由 force_locked=False 自动不覆盖。"""
	settings = _get_settings()
	window = _resolve_monthly_sync_window(settings, now_datetime())
	if not window.run:
		return {"skipped": window.reason}
	started = now_datetime()
	started_text = started.strftime("%Y-%m-%d %H:%M")
	try:
		employee_map, _employee_rows = _employee_map()
		client = _client_from_settings(settings)
		stat = _sync_date_range(client, settings, window.from_date, window.to_date, employee_map)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "月度考勤核对同步失败")
		_notify_monthly_sync(settings, window.target, error="同步异常，详见 Error Log", now_text=started_text)
		return {"error": "monthly sync failed; see Error Log"}
	frappe.db.set_single_value("Dingtalk Attendance Settings", "last_monthly_sync_for", window.target)
	duration = int((now_datetime() - started).total_seconds())
	_notify_monthly_sync(settings, window.target, stat=stat, now_text=started_text, duration=duration)
	return stat


def _regular_worker_display_factors(start_date, payment_days):
	"""普工弹窗展示口径（仅供「重新计算考勤与工资单」按钮返回前端显示，不参与工资计算）。

	`get_attendance_payroll_factors` 的 rest_days / expected_work_days / unpaid_absence_days
	是非普工 ISO 单双休口径，对普工无意义——普工底薪由结构公式按「应出勤 = 本月天数 − 1」
	折算。这里按普工口径还原展示值（基础休息固定 1 天、应出勤 = 本月天数 − 1、
	无薪缺勤 = max(0, 应出勤 − 记薪)），使弹窗与实际底薪自洽。
	"""
	month_days = get_last_day(start_date).day
	expected = month_days - 1
	return frappe._dict(
		rest_days=month_days - expected,
		expected_work_days=expected,
		unpaid_absence_days=max(0.0, flt(expected) - flt(payment_days)),
	)


@frappe.whitelist()
def recalculate_salary_slip_attendance(salary_slip):
	"""草稿工资单按钮：重新读取 Attendance 并重算工资单。"""
	_require_hr_manager()
	doc = frappe.get_doc("Salary Slip", salary_slip)
	if doc.docstatus != 0:
		frappe.throw(_("只能重算草稿工资单；已提交工资单请取消并修订。"))
	if not doc.employee or not doc.start_date or not doc.end_date:
		frappe.throw(_("工资单缺少员工或起止日期。"))

	doc.get_working_days_details(lwp=doc.leave_without_pay)
	doc.set_salary_structure_assignment()
	doc.calculate_net_pay()
	adjustment_result = apply_attendance_payroll_adjustments_to_salary_slip(doc) or frappe._dict()
	doc.compute_year_to_date()
	doc.compute_month_to_date()
	doc.compute_component_wise_year_to_date()
	set_rmb_total_in_words(doc)
	doc.flags.ignore_validate = True
	doc.save(ignore_permissions=True)
	factors = get_attendance_payroll_factors(doc.employee, doc.start_date, doc.end_date)
	late_deduction_amount = next(
		(flt(row.amount) for row in doc.get("deductions", []) if row.salary_component == LATE_DEDUCTION_COMPONENT),
		0,
	)
	early_deduction_amount = next(
		(flt(row.amount) for row in doc.get("deductions", []) if row.salary_component == EARLY_DEDUCTION_COMPONENT),
		0,
	)
	# 普工弹窗口径修正（仅展示，不影响任何工资计算）：普工底薪用结构公式「应出勤=本月天数−1」，
	# 故展示用 _regular_worker_display_factors，避免显示非普工 ISO 休息日/应出勤口径而误导核对。
	if (doc.salary_structure or "") == REGULAR_WORKER_STRUCTURE:
		display = _regular_worker_display_factors(doc.start_date, doc.payment_days)
	else:
		display = frappe._dict(
			rest_days=factors.rest_days,
			expected_work_days=factors.expected_work_days,
			unpaid_absence_days=factors.unpaid_absence_days,
		)
	return {
		"salary_slip": doc.name,
		"payment_days": doc.payment_days,
		"absent_days": doc.absent_days,
		"actual_attendance_days": factors.actual_attendance_days,
		"paid_leave_days": factors.paid_leave_days,
		"unpaid_leave_days": factors.unpaid_leave_days,
		"legal_holiday_days": factors.legal_holiday_days,
		"rest_days": display.rest_days,
		"expected_work_days": display.expected_work_days,
		"unpaid_absence_days": display.unpaid_absence_days,
		"late_minutes": factors.late_minutes,
		"early_minutes": factors.early_minutes,
		"meal_days": factors.meal_days,
		"meal_amount": factors.meal_days * flt(_load_attendance_params().meal_unit_price),
		"late_deduction_amount": late_deduction_amount,
		"early_deduction_amount": early_deduction_amount,
		"social_security_personal_amount": flt(adjustment_result.get("social_security_personal_amount")),
		"social_security_warning": adjustment_result.get("social_security_warning") or "",
		"gross_pay": doc.gross_pay,
		"net_pay": doc.net_pay,
	}


def estimate_monthly_api_calls(employee_count, days=31, punches_per_day=2):
	"""粗估调用量：结果接口按 50 条分页；详情接口按 50 人 × 7 天拆批。"""
	employee_count = cint(employee_count)
	days = cint(days)
	result_rows = employee_count * days * cint(punches_per_day or 2)
	result_calls = math.ceil(result_rows / DEFAULT_RESULT_LIMIT)
	detail_calls = math.ceil(employee_count / MAX_USERS_PER_CALL) * math.ceil(days / MAX_DAYS_PER_CALL)
	return {
		"result_calls": result_calls,
		"detail_calls": detail_calls,
		"total_calls": result_calls + detail_calls,
	}
