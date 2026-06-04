# Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and contributors
# For license information, please see license.txt

import re

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt


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


def _time_to_minutes(value):
	if _is_blank(value):
		return None
	if hasattr(value, "hour") and hasattr(value, "minute"):
		return cint(value.hour) * 60 + cint(value.minute)
	text = str(value).strip()
	match = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", text)
	if not match:
		return None
	hours = cint(match.group(1))
	minutes = cint(match.group(2))
	seconds = cint(match.group(3) or 0)
	if hours > 23 or minutes > 59 or seconds > 59:
		return None
	return hours * 60 + minutes


class PayrollAttendanceParameter(Document):
	def onload(self):
		self._set_defaults()

	def validate(self):
		self._set_defaults()
		self._validate_numbers()
		self._validate_schedule_profiles()

	def _set_defaults(self):
		if _is_blank(self.meal_unit_price):
			self.meal_unit_price = 14
		if _is_blank(self.non_worker_monthly_rest_days):
			self.non_worker_monthly_rest_days = 6
		if _is_blank(self.deduction_threshold_minutes):
			self.deduction_threshold_minutes = 30
		if _is_blank(self.regular_daily_divisor):
			self.regular_daily_divisor = 30
		if _is_blank(self.paid_leave_names):
			self.paid_leave_names = "年假,丧假"
		if _is_blank(self.overtime_start_time):
			self.overtime_start_time = "17:00:00"
		if _is_blank(self.overtime_min_minutes):
			self.overtime_min_minutes = 60
		if _is_blank(self.overtime_step_minutes):
			self.overtime_step_minutes = 30
		if _is_blank(self.overtime_cap_hours):
			self.overtime_cap_hours = 5
		if _is_blank(self.overtime_hours_per_day):
			self.overtime_hours_per_day = 7
		if _is_blank(self.overtime_daily_divisor):
			self.overtime_daily_divisor = 30
		if not self.get("schedule_profiles"):
			for profile in DEFAULT_PROFILES:
				self.append("schedule_profiles", dict(profile))

	def _validate_numbers(self):
		non_negative_fields = (
			("meal_unit_price", "餐补单价"),
			("non_worker_monthly_rest_days", "非普工月休息日"),
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
			frappe.throw("加班起算时刻必须是 HH:MM 或 HH:MM:SS 格式。")

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
