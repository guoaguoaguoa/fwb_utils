# Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and Contributors
# See license.txt
"""「考勤校对表」两张报表(明细 + 横向总览)的共享逻辑（设计文档 §8）。

纯函数（is_abnormal / compact_code / color_for / status_label / pivot_to_matrix）
不依赖 DB，可沙箱单测；get_attendance_rows 是薄查询层。两报表共用，避免口径漂移。
"""
from __future__ import annotations

import frappe
import re

from frappe.utils import add_days, getdate

# 状态 → 中文标签 / 总览紧凑码
STATUS_LABEL = {
	"Present": "出勤",
	"Absent": "缺勤",
	"Half Day": "半天",
	"On Leave": "请假",
	"Work From Home": "居家",
}
STATUS_CODE = {
	"Present": "出",
	"Absent": "缺",
	"Half Day": "半",
	"On Leave": "假",
	"Work From Home": "家",
}
# 填充色（浅色底 + 深色字；口径与 attendance_calendar.js get_css_class 对齐）
COLOR_GREEN = "#e6f4ea"  # 出勤
COLOR_RED = "#fde7e9"  # 缺勤 / 旷工
COLOR_YELLOW = "#fff4d6"  # 半天
COLOR_BLUE = "#e7f0fd"  # 请假
COLOR_GRAY = "#f2f2f2"  # 休息 / 无记录

WEEKDAY_CN = ["一", "二", "三", "四", "五", "六", "日"]  # Monday=0


def weekday_cn(d) -> str:
	return WEEKDAY_CN[getdate(d).weekday()]


def split_punches(punch_summary, n=4):
	"""从打卡串取 n 个签到点 '(07:18,11:30,12:28,20:31)' → ['07:18','11:30','12:28','20:31']；缺卡/不足补空。"""
	m = re.search(r"\(([^)]*)\)", punch_summary or "")
	parts = [p.strip() for p in m.group(1).split(",")] if m else []
	parts = ["" if (not p or p == "-") else p for p in parts]
	parts += [""] * (n - len(parts))
	return parts[:n]


def dept_short(department):
	"""'普工 - 富锐' → '普工'（去掉 ERPNext 部门名的 ' - 公司缩写' 后缀）。"""
	return department.rsplit(" - ", 1)[0] if department else ""


def _punch(row) -> str:
	return (row.get("custom_punch_summary") or "") if hasattr(row, "get") else ""


def is_missing_punch(row) -> bool:
	return "缺卡" in _punch(row)


def is_kuanggong(row) -> bool:
	return "旷工" in _punch(row)


def is_abnormal(row) -> bool:
	"""缺勤/半天/请假，或迟到/早退，或打卡串含「缺卡/旷工」。"""
	if row.get("status") in ("Absent", "Half Day", "On Leave"):
		return True
	if row.get("late_entry") or row.get("early_exit"):
		return True
	ps = _punch(row)
	return ("缺卡" in ps) or ("旷工" in ps)


def status_label(row) -> str:
	return STATUS_LABEL.get(row.get("status"), row.get("status") or "")


def compact_code(row) -> str:
	"""总览格子紧凑码：出/缺/半/假，旷工→旷；加班加 💪，缺卡加 △。"""
	code = STATUS_CODE.get(row.get("status"), "")
	if is_kuanggong(row):
		code = "旷"
	if row.get("custom_overtime_days"):
		code += "💪"
	if is_missing_punch(row):
		code += "△"
	return code


def color_for(row) -> str:
	"""格子填充色：缺勤/旷工=红、半天=黄、请假=蓝、出勤=绿、其余=灰。"""
	if row.get("status") == "Absent" or is_kuanggong(row):
		return COLOR_RED
	if row.get("status") == "Half Day":
		return COLOR_YELLOW
	if row.get("status") == "On Leave":
		return COLOR_BLUE
	if row.get("status") == "Present":
		return COLOR_GREEN
	return COLOR_GRAY


def pivot_to_matrix(rows, start_date, end_date):
	"""每日 dict 列表 → (days, emp_rows)。
	days = [date,...]（整段连续）；emp_rows = [{employee, employee_name, department, <'YYYY-MM-DD'>: row, ...}]。"""
	start, end = getdate(start_date), getdate(end_date)
	days, d = [], start
	while d <= end:
		days.append(d)
		d = add_days(d, 1)
	emps = {}
	for r in rows:
		key = r.get("employee")
		if key not in emps:
			emps[key] = frappe._dict(
				employee=r.get("employee"),
				employee_name=r.get("employee_name"),
				department=r.get("department"),
			)
		emps[key][str(getdate(r.get("attendance_date")))] = r
	return days, list(emps.values())


def get_attendance_rows(filters):
	"""薄查询层：按筛选取 Attendance(+自定义字段)，按 员工→日期 排序；可选只看异常/加班。"""
	filters = frappe._dict(filters or {})
	conds = ["docstatus < 2"]
	params = {}
	for field in ("from_date", "to_date", "employee", "department", "shift", "company"):
		val = filters.get(field)
		if not val:
			continue
		if field == "from_date":
			conds.append("attendance_date >= %(from_date)s")
		elif field == "to_date":
			conds.append("attendance_date <= %(to_date)s")
		else:
			conds.append(f"{field} = %({field})s")
		params[field] = val
	rows = frappe.db.sql(
		f"""
		select employee, employee_name, department, shift, attendance_date, status,
		       in_time, out_time, working_hours, late_entry, early_exit,
		       custom_punch_summary, custom_overtime_days
		from `tabAttendance`
		where {" and ".join(conds)}
		order by employee_name, attendance_date
		""",
		params,
		as_dict=True,
	)
	if int(filters.get("only_abnormal") or 0):
		rows = [r for r in rows if is_abnormal(r)]
	if int(filters.get("only_overtime") or 0):
		rows = [r for r in rows if r.get("custom_overtime_days")]
	return rows
