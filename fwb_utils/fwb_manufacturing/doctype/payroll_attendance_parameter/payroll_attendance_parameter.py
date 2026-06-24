# Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and contributors
# For license information, please see license.txt

import re
from datetime import timedelta

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt

DEFAULT_OVERTIME_START_TIME = "17:00:00"
DEFAULT_SYNC_LEAVE_NAMES = "年假,丧假,事假,病假,调休"
DEFAULT_HOUR_BASED_LEAVE_NAMES = "事假,病假,调休"
DEFAULT_NON_WORKER_REST_CALCULATION_MODE = "ISO单双休"
DEFAULT_NON_WORKER_DOUBLE_REST_WEEK_PARITY = "单数周"
NON_WORKER_REST_CALCULATION_MODES = ("ISO单双休", "固定月休天数")
NON_WORKER_DOUBLE_REST_WEEK_PARITIES = ("单数周", "双数周")
LEAVE_NAME_MAX_LENGTH = 20
TIME_RE = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d{1,6})?)?")


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


def _is_blank(value):
	return value is None or str(value).strip() == ""


def _time_parts(value):
	if _is_blank(value):
		return None
	if isinstance(value, timedelta):
		total_seconds = int(value.total_seconds())
		if total_seconds < 0 or total_seconds >= 24 * 60 * 60:
			return None
		hours = total_seconds // 3600
		minutes = (total_seconds % 3600) // 60
		seconds = total_seconds % 60
		return hours, minutes, seconds
	if hasattr(value, "hour") and hasattr(value, "minute"):
		hours = cint(value.hour)
		minutes = cint(value.minute)
		seconds = cint(getattr(value, "second", 0))
		if hours > 23 or minutes > 59 or seconds > 59:
			return None
		return hours, minutes, seconds
	text = str(value).strip()
	match = TIME_RE.fullmatch(text)
	if not match:
		return None
	hours = cint(match.group(1))
	minutes = cint(match.group(2))
	seconds = cint(match.group(3) or 0)
	if hours > 23 or minutes > 59 or seconds > 59:
		return None
	return hours, minutes, seconds


def normalize_time_string(value, default=None):
	parts = _time_parts(value)
	if parts is None:
		return default
	return f"{parts[0]:02d}:{parts[1]:02d}:{parts[2]:02d}"


def _time_to_minutes(value):
	parts = _time_parts(value)
	if parts is None:
		return None
	return parts[0] * 60 + parts[1]


class PayrollAttendanceParameter(Document):
	def onload(self):
		self._set_defaults()

	def validate(self):
		self._set_defaults()
		self._validate_numbers()
		self._validate_leave_names()
		self._validate_schedule_profiles()

	def _set_defaults(self):
		if _is_blank(self.get("meal_unit_price")):
			self.meal_unit_price = 14
		if _is_blank(self.get("non_worker_rest_calculation_mode")):
			self.non_worker_rest_calculation_mode = DEFAULT_NON_WORKER_REST_CALCULATION_MODE
		if _is_blank(self.get("non_worker_double_rest_week_parity")):
			self.non_worker_double_rest_week_parity = DEFAULT_NON_WORKER_DOUBLE_REST_WEEK_PARITY
		if _is_blank(self.get("non_worker_monthly_rest_days")):
			self.non_worker_monthly_rest_days = 6
		if _is_blank(self.get("deduction_threshold_minutes")):
			self.deduction_threshold_minutes = 30
		if _is_blank(self.get("regular_daily_divisor")):
			self.regular_daily_divisor = 30
		if _is_blank(self.get("paid_leave_names")):
			self.paid_leave_names = "年假,丧假"
		if _is_blank(self.get("sync_leave_names")):
			self.sync_leave_names = DEFAULT_SYNC_LEAVE_NAMES
		if _is_blank(self.get("hour_based_leave_names")):
			self.hour_based_leave_names = DEFAULT_HOUR_BASED_LEAVE_NAMES
		if _is_blank(self.get("overtime_start_time")):
			self.overtime_start_time = DEFAULT_OVERTIME_START_TIME
		else:
			normalized_time = normalize_time_string(self.overtime_start_time)
			if normalized_time:
				self.overtime_start_time = normalized_time
		if _is_blank(self.get("overtime_min_minutes")):
			self.overtime_min_minutes = 60
		if _is_blank(self.get("overtime_step_minutes")):
			self.overtime_step_minutes = 30
		if _is_blank(self.get("overtime_cap_hours")):
			self.overtime_cap_hours = 5
		if _is_blank(self.get("overtime_hours_per_day")):
			self.overtime_hours_per_day = 7
		if _is_blank(self.get("overtime_daily_divisor")):
			self.overtime_daily_divisor = 30
		if not self.get("schedule_profiles"):
			for profile in DEFAULT_PROFILES:
				self.append("schedule_profiles", dict(profile))

	def _validate_numbers(self):
		if self.get("non_worker_rest_calculation_mode") not in NON_WORKER_REST_CALCULATION_MODES:
			frappe.throw("非普工休息日计算方式只能选择 ISO单双休 或 固定月休天数。")
		if self.get("non_worker_double_rest_week_parity") not in NON_WORKER_DOUBLE_REST_WEEK_PARITIES:
			frappe.throw("双休周类型只能选择 单数周 或 双数周。")

		non_negative_fields = (
			("meal_unit_price", "餐补单价"),
			("non_worker_monthly_rest_days", "固定月休息日"),
			("deduction_threshold_minutes", "迟到早退起扣阈值"),
			("overtime_min_minutes", "加班起步分钟"),
			("overtime_cap_hours", "单日加班封顶小时"),
		)
		for fieldname, label in non_negative_fields:
			if flt(self.get(fieldname)) < 0:
				frappe.throw(f"{label}不能小于 0。")

		positive_fields = (
			("regular_daily_divisor", "普工单日工资分母"),
			("overtime_step_minutes", "加班阶梯分钟"),
			("overtime_hours_per_day", "加班小时折天分母"),
			("overtime_daily_divisor", "加班工资日分母"),
		)
		for fieldname, label in positive_fields:
			if flt(self.get(fieldname)) <= 0:
				frappe.throw(f"{label}必须大于 0。")

		if _time_to_minutes(self.overtime_start_time) is None:
			frappe.throw("加班起算时刻必须是 HH:MM、HH:MM:SS 或 HH:MM:SS.ffffff 格式。")

	def _validate_leave_names(self):
		for fieldname, label in (
			("paid_leave_names", "带薪假名称"),
			("sync_leave_names", "同步请假名称"),
			("hour_based_leave_names", "按小时统计的请假名称"),
		):
			names = [name.strip() for name in re.split(r"[,，\s]+", str(self.get(fieldname) or "")) if name.strip()]
			too_long = [name for name in names if len(name) > LEAVE_NAME_MAX_LENGTH]
			if too_long:
				frappe.throw(f"{label}中的单个名称不能超过 {LEAVE_NAME_MAX_LENGTH} 个字符：{too_long[0]}")

	def _validate_schedule_profiles(self):
		counts = {0: 0, 1: 0}
		for row in self.get("schedule_profiles"):
			is_regular = 1 if cint(row.is_regular) else 0
			counts[is_regular] += 1
			times = {
				"上班时刻": _time_to_minutes(row.work_start),
				"午休起": _time_to_minutes(row.lunch_start),
				"午休止": _time_to_minutes(row.lunch_end),
				"下班时刻": _time_to_minutes(row.work_end),
			}
			if any(value is None for value in times.values()):
				frappe.throw(f"排班档案第 {row.idx} 行时间必须是 HH:MM 或 HH:MM:SS 格式。")
			if not (times["上班时刻"] < times["午休起"] < times["午休止"] < times["下班时刻"]):
				frappe.throw(f"排班档案第 {row.idx} 行时间顺序必须为：上班 < 午休起 < 午休止 < 下班。")
			work_minutes = (times["下班时刻"] - times["上班时刻"]) - (times["午休止"] - times["午休起"])
			expected_hours = work_minutes / 60.0
			if flt(row.daily_hours) <= 0:
				frappe.throw(f"排班档案第 {row.idx} 行日工作小时必须大于 0。")
			if abs(flt(row.daily_hours) - expected_hours) > 0.01:
				frappe.throw(f"排班档案第 {row.idx} 行日工作小时应为 {expected_hours:.2f}。")

		if counts[1] != 1 or counts[0] != 1:
			frappe.throw("排班档案必须且只能包含 1 行普工档案、1 行综合岗档案。")
