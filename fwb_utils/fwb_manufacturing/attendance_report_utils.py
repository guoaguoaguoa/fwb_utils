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


def _normalize_result_labels(labels):
	labels = [label for label in labels if label]
	if "正常" in labels:
		non_normal_labels = [label for label in labels if label != "正常"]
		if non_normal_labels:
			if len(non_normal_labels) == 1 and non_normal_labels[0] == "缺卡":
				return ["缺卡", "出勤"]
			return non_normal_labels
	return labels


def _leave_result_label(row):
	return row.get("custom_dingtalk_leave_name") or "请假"


def _normalize_result_summary_text(text, row=None):
	for sep in (":", "："):
		if sep not in text:
			continue
		source, result = text.split(sep, 1)
		labels = [label.strip() for label in re.split(r"[、,，/]+", result) if label.strip()]
		if row and row.get("status") == "On Leave" and labels and all(label == "缺卡" for label in labels):
			return f"{source}{sep}{_leave_result_label(row)}"
		normalized_labels = _normalize_result_labels(labels)
		if normalized_labels != labels:
			return f"{source}{sep}{'、'.join(normalized_labels)}"
		return text
	return text


def attendance_result_summary(row) -> str:
	"""明细表展示用：保留考勤结果口径，不重复展示每次打卡时间。"""
	text = _punch(row)
	without_times = re.sub(r"\s*\([^)]*\)", "", text).strip()
	without_times = _normalize_result_summary_text(without_times, row)
	if without_times in ("钉钉API", "钉钉API:", "钉钉API："):
		without_times = f"钉钉API · {status_label(row)}"
	if not without_times:
		without_times = status_label(row)

	flags = []
	if row.get("late_entry") and "迟到" not in without_times:
		flags.append("迟到")
	if row.get("early_exit") and "早退" not in without_times:
		flags.append("早退")
	return without_times + (f" · {'/'.join(flags)}" if flags else "")


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


def department_filter_names(department):
	"""部门树过滤展开：返回该部门及其所有子孙部门名（含自身）。

	`Department` 是 ERPNext 树（nested set，有 lft/rgt）。员工/考勤只挂在叶子部门，
	group 父节点（如「办公职能 - 富锐」）本身没有任何 Attendance；若对父节点做精确匹配会得到空表。
	这里用 nested set 把父节点展开成整段子树（采购/运营/财务/行政/销售/内贸/外贸…），
	按父节点查询即可显示其全部下属（含多层嵌套，如「销售部」下的内贸/外贸）。
	叶子节点的子树只有自身 → 等价于精确匹配，向后兼容。
	查不到 lft/rgt（部门不存在或树未构建）时回退为 [department]，保持旧的精确匹配行为。
	"""
	if not department:
		return []
	bounds = frappe.db.get_value("Department", department, ["lft", "rgt"])
	if not bounds or bounds[0] is None or bounds[1] is None:
		return [department]
	lft, rgt = bounds
	names = frappe.db.get_all(
		"Department",
		filters={"lft": [">=", lft], "rgt": ["<=", rgt]},
		pluck="name",
	)
	return names or [department]


def get_attendance_rows(filters):
	"""薄查询层：按筛选取 Attendance(+自定义字段)，按 员工→日期 排序；可选只看异常/加班。"""
	filters = frappe._dict(filters or {})
	conds = ["docstatus < 2"]
	params = {}
	for field in ("from_date", "to_date", "employee", "shift", "company"):
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

	# 部门按树展开：选 group 父节点（如「办公职能」）时含其全部子孙部门，
	# 否则父节点上没有任何 Attendance（只挂叶子部门）会查不到任何人。详见 department_filter_names。
	dept_names = department_filter_names(filters.get("department"))
	if dept_names:
		dept_keys = []
		for i, name in enumerate(dept_names):
			key = f"dept_{i}"
			params[key] = name
			dept_keys.append(f"%({key})s")
		conds.append(f"department in ({', '.join(dept_keys)})")

	rows = frappe.db.sql(
		f"""
		select employee, employee_name, department, shift, attendance_date, status,
		       in_time, out_time, working_hours, late_entry, early_exit,
		       custom_punch_summary, custom_overtime_days, custom_dingtalk_leave_name
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
