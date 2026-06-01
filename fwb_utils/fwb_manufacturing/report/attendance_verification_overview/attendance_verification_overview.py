# Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and Contributors
# See license.txt
"""考勤校对表（总览）：一员工一行、当月每天一列、紧凑码热力图。设计文档 §8。

着色/冻结在 .js（格子按紧凑码填色 + 左 2 列 sticky 冻结）。
"""
from __future__ import annotations

import frappe
from frappe.utils import flt, get_first_day, get_last_day, getdate, today

from fwb_utils.fwb_manufacturing.attendance_report_utils import (
	WEEKDAY_CN,
	compact_code,
	dept_short,
	get_attendance_rows,
	pivot_to_matrix,
)


def _day_field(d) -> str:
	return "day_" + getdate(d).strftime("%Y%m%d")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.get("from_date"):
		filters.from_date = str(get_first_day(today()))
	if not filters.get("to_date"):
		filters.to_date = str(get_last_day(today()))
	rows = get_attendance_rows(filters)
	days, emp_rows = pivot_to_matrix(rows, filters.from_date, filters.to_date)
	return get_columns(days), get_data(days, emp_rows)


def get_columns(days):
	cols = [
		{"label": "员工", "fieldname": "employee_name", "fieldtype": "Data", "width": 70},
		{"label": "部门", "fieldname": "department", "fieldtype": "Data", "width": 56},
	]
	for d in days:
		d = getdate(d)
		cols.append(
			{
				"label": f"{d.day} {WEEKDAY_CN[d.weekday()]}",
				"fieldname": _day_field(d),
				"fieldtype": "Data",
				"width": 70,
			}
		)
	cols.append({"label": "加班日数", "fieldname": "ot_total", "fieldtype": "Int", "width": 72})
	return cols


def get_data(days, emp_rows):
	out = []
	for e in emp_rows:
		row = {"employee_name": e.get("employee_name"), "department": dept_short(e.get("department")), "ot_total": 0}
		ot_days = 0
		for d in days:
			cell = e.get(str(getdate(d)))
			if cell:
				row[_day_field(d)] = compact_code(cell)
				if flt(cell.get("custom_overtime_days") or 0) > 0:
					ot_days += 1
		row["ot_total"] = ot_days
		out.append(row)
	return out
