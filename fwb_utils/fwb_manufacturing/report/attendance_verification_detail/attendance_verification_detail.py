# Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and Contributors
# See license.txt
"""考勤校对表（明细）：一天一行，逐日对钉钉。设计文档 §8。着色/小计见 .js。"""
from __future__ import annotations

from frappe.utils import flt

from fwb_utils.fwb_manufacturing.attendance_report_utils import (
	attendance_result_summary,
	dept_short,
	get_attendance_rows,
	split_punches,
	status_label,
	weekday_cn,
)


def execute(filters=None):
	filters = filters or {}
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": "日期", "fieldname": "attendance_date", "fieldtype": "Date", "width": 90},
		{"label": "星期", "fieldname": "weekday", "fieldtype": "Data", "width": 50},
		{"label": "员工姓名", "fieldname": "employee_name", "fieldtype": "Data", "width": 100},
		{"label": "状态", "fieldname": "status_label", "fieldtype": "Data", "width": 70},
		{"label": "考勤结果", "fieldname": "attendance_result", "fieldtype": "Data", "width": 190},
		{"label": "上班1", "fieldname": "punch1", "fieldtype": "Data", "width": 62},
		{"label": "下班1", "fieldname": "punch2", "fieldtype": "Data", "width": 62},
		{"label": "上班2", "fieldname": "punch3", "fieldtype": "Data", "width": 62},
		{"label": "下班2", "fieldname": "punch4", "fieldtype": "Data", "width": 62},
		{"label": "工时", "fieldname": "working_hours", "fieldtype": "Float", "width": 60, "precision": 1},
		{"label": "加班时长(时)", "fieldname": "overtime_hours", "fieldtype": "Float", "width": 90, "precision": 1},
		{"label": "加班天", "fieldname": "custom_overtime_days", "fieldtype": "Float", "width": 70, "precision": 2},
		{"label": "迟到", "fieldname": "late", "fieldtype": "Data", "width": 60},
		{"label": "早退", "fieldname": "early", "fieldtype": "Data", "width": 60},
		{"label": "部门", "fieldname": "department", "fieldtype": "Data", "width": 72},
	]


def _hhmm(dt):
	# in_time/out_time 是 Datetime → 取 HH:MM
	return str(dt)[11:16] if dt else ""


def _map_row(r):
	p = split_punches(r.get("custom_punch_summary"))
	return {
		"attendance_date": r.get("attendance_date"),
		"weekday": weekday_cn(r.get("attendance_date")),
		"employee_name": r.get("employee_name"),
		"status_label": status_label(r),
		"attendance_result": attendance_result_summary(r),
		"punch1": p[0],
		"punch2": p[1],
		"punch3": p[2],
		"punch4": p[3],
		"working_hours": r.get("working_hours"),
		"overtime_hours": flt(r.get("custom_overtime_days")) * 7,
		"custom_overtime_days": r.get("custom_overtime_days"),
		"late": "⚠迟到" if r.get("late_entry") else "",
		"early": "⚠早退" if r.get("early_exit") else "",
		"department": dept_short(r.get("department")),
	}


def get_data(filters):
	rows = get_attendance_rows(filters)
	out, cur, agg = [], None, None

	def flush():
		if agg:
			out.append(
				{
					"status_label": "小计",
					"employee_name": agg["name"],
					"attendance_result": f"实出勤 {agg['present']} 天 · 缺勤 {agg['absent']} 天 · 半天 {agg['half']} · 加班 {agg['ot_day_count']} 日 / {agg['ot_hours']:.1f} 时",
					"overtime_hours": agg["ot_hours"],
					"custom_overtime_days": agg["ot_day_count"],
					"is_summary": 1,
				}
			)

	for r in rows:
		if r.get("employee") != cur:
			flush()
			cur = r.get("employee")
			agg = {
				"name": r.get("employee_name"),
				"present": 0,
				"absent": 0,
				"half": 0,
				"ot_day_count": 0,
				"ot_days": 0.0,
				"ot_hours": 0.0,
			}
		st = r.get("status")
		if st == "Present":
			agg["present"] += 1
		elif st == "Absent":
			agg["absent"] += 1
		elif st == "Half Day":
			agg["half"] += 1
		ot_d = flt(r.get("custom_overtime_days") or 0)
		if ot_d > 0:
			agg["ot_day_count"] += 1
			agg["ot_days"] += ot_d
			agg["ot_hours"] += ot_d * 7
		out.append(_map_row(r))
	flush()
	return out
