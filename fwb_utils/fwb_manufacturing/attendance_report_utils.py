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
	"Absent": "未到",  # 没来/全缺卡/单边卡（无薪，非违规）；旷工另由 status_label 判为「旷工」
	"Half Day": "半天",
	"On Leave": "请假",
	"Work From Home": "居家",
}
STATUS_CODE = {
	"Present": "出",
	"Absent": "未",  # 同上；旷工 → 「旷」
	"Half Day": "半",
	"On Leave": "假",
	"Work From Home": "家",
}
# 填充色（浅色底 + 深色字）
COLOR_GREEN = "#e6f4ea"  # 出勤
COLOR_RED = "#fde7e9"  # 旷工 / 迟到早退被扣（用户口径：红色只留给旷工和被扣）
COLOR_YELLOW = "#fff4d6"  # 半天
COLOR_BLUE = "#e7f0fd"  # 请假
COLOR_NEUTRAL = "#faf4e6"  # 未到：没来/全缺卡（无薪，非违规）—— 真·米色，中性不报警，区别于灰
COLOR_GRAY = "#f2f2f2"  # 休息 / 无记录（当天无考勤行）

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
	"""明细「状态」列短词：旷工→旷工(红)，没来/全缺卡→未到(中性)，其余按 STATUS_LABEL。"""
	if is_kuanggong(row):
		return "旷工"
	return STATUS_LABEL.get(row.get("status"), row.get("status") or "")


def _leave_result_label(row):
	return row.get("custom_dingtalk_leave_name") or "请假"


def attendance_result_summary(row) -> str:
	"""明细「考勤结果」列：简约结果词（列宽有限，禁长文案）。

	去打卡时间与来源前缀(车间工人班次/钉钉API/考勤组名)；
	缺卡 → 漏卡(出勤) / 未到(缺勤)；旷工 → 旷工；请假 → 假名；迟到/早退附短标。
	"""
	body = re.sub(r"\s*\([^)]*\)", "", _punch(row)).strip()  # 去 (07:25,...) 打卡时间
	for sep in (":", "："):  # 去来源前缀
		if sep in body:
			body = body.split(sep, 1)[1].strip()
			break

	if row.get("status") == "On Leave" and not is_kuanggong(row):
		core = _leave_result_label(row)  # 年假/事假/...
	else:
		labels = [x.strip() for x in re.split(r"[、,，/]+", body) if x.strip()]
		out = []
		for x in labels:
			if x in ("正常", "出勤"):
				continue  # 正向标签冗余，状态列已表达
			elif "旷工" in x:
				out.append("旷工")
			elif "缺卡" in x:
				out.append("漏卡" if row.get("status") == "Present" else "未到")
			else:
				out.append(x)
		out = list(dict.fromkeys(out))  # 去重保序
		core = "、".join(out) if out else status_label(row)

	flags = []
	if row.get("late_entry") and "迟到" not in core:
		flags.append("迟到")
	if row.get("early_exit") and "早退" not in core:
		flags.append("早退")
	return core + (f"·{'/'.join(flags)}" if flags else "")


def compact_code(row) -> str:
	"""总览格子紧凑码：出/未/半/假，旷工→旷；迟到早退被扣→⚠、漏卡不扣→△、加班→💪。

	⚠ 与 △ 互斥：被扣(late/early)的漏卡用 ⚠，免扣的漏卡(缺中间卡)用 △，
	让总览能区分「被扣半天的漏卡」与「免扣的漏卡」。
	"""
	if is_kuanggong(row):
		code = "旷"
	else:
		code = STATUS_CODE.get(row.get("status"), "")
	if row.get("late_entry") or row.get("early_exit"):
		code += "⚠"  # 漏边缘卡被扣 / 迟到早退
	elif is_missing_punch(row) and row.get("status") == "Present":
		code += "△"  # 漏卡但不扣（缺中间卡）
	if row.get("custom_overtime_days"):
		code += "💪"
	return code


def color_for(row) -> str:
	"""格子填充色：旷工/迟到早退被扣=红、没来=中性米、半天=黄、请假=蓝、出勤=绿、无记录=灰。

	红色只留给旷工和迟到/早退被扣（用户口径）；没来/全缺卡是无薪非违规，用中性米色不报警。
	"""
	if is_kuanggong(row) or row.get("late_entry") or row.get("early_exit"):
		return COLOR_RED
	if row.get("status") == "Absent":
		return COLOR_NEUTRAL
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
		       in_time, out_time, late_entry, early_exit,
		       custom_punch_summary, custom_overtime_days, custom_dingtalk_leave_name,
		       custom_late_minutes, custom_early_minutes
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
