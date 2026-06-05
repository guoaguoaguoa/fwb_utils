import frappe
from frappe.utils import cint, flt

from fwb_utils.fwb_manufacturing.doctype.payroll_attendance_parameter.payroll_attendance_parameter import (
	DEFAULT_OVERTIME_START_TIME,
	normalize_time_string,
)
from fwb_utils.patches.v15_0.non_worker_fixed_salary_hourly_deductions import _ensure_structure_row

REGULAR_STRUCTURE = "普工结构"
EARLY_DEDUCTION_COMPONENT = "早退扣款"

DEFAULT_PROFILES = (
	{
		"profile_name": "普工",
		"is_regular": 1,
		"work_start": "07:30:00",
		"lunch_start": "11:30:00",
		"lunch_end": "12:30:00",
		"work_end": "17:00:00",
		"daily_hours": 8.5,
	},
	{
		"profile_name": "综合岗",
		"is_regular": 0,
		"work_start": "08:30:00",
		"lunch_start": "11:30:00",
		"lunch_end": "13:00:00",
		"work_end": "17:30:00",
		"daily_hours": 7.5,
	},
)


def execute():
	"""薪资考勤参数默认值 + 普工/综合岗排班档案；普工结构补「早退扣款」常驻扣除行。"""
	_seed_attendance_params()
	_ensure_regular_early_deduction_row()


def _seed_attendance_params():
	doc = frappe.get_single("Payroll Attendance Parameter")
	changed = _set_defaults(doc)
	if not doc.get("schedule_profiles"):
		for profile in DEFAULT_PROFILES:
			doc.append("schedule_profiles", dict(profile))
		changed = True
	if changed:
		doc.save(ignore_permissions=True)


def _is_blank(value):
	return value is None or str(value).strip() == ""


def _set_if_changed(doc, fieldname, value):
	if doc.get(fieldname) == value:
		return False
	if callable(getattr(doc, "set", None)):
		doc.set(fieldname, value)
	else:
		doc[fieldname] = value
	return True


def _set_defaults(doc):
	changed = False
	if _is_blank(doc.get("meal_unit_price")):
		changed = _set_if_changed(doc, "meal_unit_price", 14) or changed
	if _is_blank(doc.get("non_worker_monthly_rest_days")):
		changed = _set_if_changed(doc, "non_worker_monthly_rest_days", 6) or changed
	if _is_blank(doc.get("deduction_threshold_minutes")):
		changed = _set_if_changed(doc, "deduction_threshold_minutes", 30) or changed
	if cint(doc.get("regular_daily_divisor")) <= 0:
		changed = _set_if_changed(doc, "regular_daily_divisor", 30) or changed

	normalized_time = normalize_time_string(doc.get("overtime_start_time"), DEFAULT_OVERTIME_START_TIME)
	changed = _set_if_changed(doc, "overtime_start_time", normalized_time) or changed
	if _is_blank(doc.get("paid_leave_names")):
		changed = _set_if_changed(doc, "paid_leave_names", "年假,丧假") or changed
	if _is_blank(doc.get("overtime_min_minutes")):
		changed = _set_if_changed(doc, "overtime_min_minutes", 60) or changed
	if cint(doc.get("overtime_step_minutes")) <= 0:
		changed = _set_if_changed(doc, "overtime_step_minutes", 30) or changed
	if _is_blank(doc.get("overtime_cap_hours")):
		changed = _set_if_changed(doc, "overtime_cap_hours", 5) or changed
	if flt(doc.get("overtime_hours_per_day")) <= 0:
		changed = _set_if_changed(doc, "overtime_hours_per_day", 7) or changed
	if cint(doc.get("overtime_daily_divisor")) <= 0:
		changed = _set_if_changed(doc, "overtime_daily_divisor", 30) or changed
	return changed


def _ensure_regular_early_deduction_row():
	if not frappe.db.exists("Salary Structure", REGULAR_STRUCTURE):
		return
	if not frappe.db.exists("Salary Component", EARLY_DEDUCTION_COMPONENT):
		return
	_ensure_structure_row(REGULAR_STRUCTURE, "deductions", EARLY_DEDUCTION_COMPONENT)
