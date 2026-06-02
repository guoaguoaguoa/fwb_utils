# Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and Contributors
# See license.txt
"""钉钉「月度汇总」导入 + 加班自动结算（设计文档 §7.6.2）。

加班规则（用户 2026-06 确认，仅「普工结构」适用）：
- 起算点：当天下班打卡时刻 − 17:00（标准下班）。
- 1 小时起步：不足 1 小时不计（17:30=0、18:00=1 小时起）。
- 30 分钟阶梯：向下取整到 30 分钟整档，零头舍去（1:15→1.0h、1:30→1.5h、1:45→1.5h）。
- 封顶 5 小时（不提倡通宵、无两班制）。
- 折算：7 小时 = 1 天（3.5h=0.5天）→ overtime_days = 记为小时 / 7。
- 加班金额 = Σ(每日 overtime_days) × 总月薪/30，由 doc_event 写进工资单「加班」行。
- **非普工**：不计加班费（钉钉端按调休处理），overtime_days 一律 0。

纯逻辑（parse_day_cell / overtime_days_for_regular / daily_overtime_days /
parse_monthly_summary）不依赖 DB，可沙箱单测。
"""
from __future__ import annotations

import re

import frappe
from frappe.utils import add_days, flt, getdate

OT_START = "17:00"  # 标准下班，加班起算点
OT_MIN_MINUTES = 60  # 1 小时起步
OT_STEP_MIN = 30  # 30 分钟一个阶梯
OT_CAP_HOURS = 5.0  # 封顶 5 小时
HOURS_PER_DAY = 7.0  # 7 小时 = 1 天（3.5h=0.5天）
OVERTIME_COMPONENT = "加班"
REGULAR_WORKER_STRUCTURE = "普工结构"  # 仅此结构计加班费


def _to_minutes(hhmm: str) -> int:
	h, m = hhmm.split(":")
	return int(h) * 60 + int(m)


def overtime_days_for_regular(out_time, is_absent: bool = False) -> float:
	"""普工加班：下班打卡 − 17:00 → 1 小时起步、30 分钟向下取整、封顶 5 小时 → ÷7 折天。
	旷工 / 无下班卡 = 0。例：18:00→1.0h、18:15→1.0h、18:30→1.5h、22:00+→封顶5h。"""
	if is_absent or not out_time:
		return 0.0
	try:
		minutes = _to_minutes(out_time) - _to_minutes(OT_START)
	except (ValueError, AttributeError):
		return 0.0
	if minutes < OT_MIN_MINUTES:
		return 0.0
	steps = minutes // OT_STEP_MIN  # 30 分钟整档数，零头舍去
	hours = min(steps * (OT_STEP_MIN / 60.0), OT_CAP_HOURS)
	return hours / HOURS_PER_DAY


def daily_overtime_days(out_time, is_absent: bool, is_regular: bool) -> float:
	"""按岗位分流：普工走阶梯算法，非普工一律 0（调休处理，不计加班费）。"""
	if not is_regular:
		return 0.0
	return overtime_days_for_regular(out_time, is_absent)


def parse_day_cell(cell):
	"""解析钉钉每日格 '车间工人班次:正常\\n(07:18,11:30,12:28,20:31)'；空/非当月 → None。"""
	if cell is None or not str(cell).strip():
		return None
	text = str(cell).strip()
	status_line, _, punch_line = text.partition("\n")
	statuses = [seg.split(":")[-1] for seg in status_line.split(",")]
	is_absent = any("旷工" in s for s in statuses)
	is_leave = any(k in status_line for k in ("请假", "年假", "事假", "病假", "调休"))
	is_late = "迟到" in status_line  # 含「严重迟到」
	is_early = "早退" in status_line
	m = re.search(r"\(([^)]*)\)", punch_line)
	punches = [p.strip() for p in m.group(1).split(",")] if m else []
	times = [p for p in punches if p and p != "-"]
	return frappe._dict(
		status_text=status_line,
		punch_summary=text.replace("\n", " "),
		in_time=(times[0] if times else None),
		out_time=(times[-1] if times else None),
		is_absent=is_absent,
		is_leave=is_leave,
		is_late=is_late,
		is_early=is_early,
		overtime_days=0.0,  # 占位；真实值在 import_monthly_summary 按岗位(是否普工)覆盖
	)


def parse_monthly_summary(rows):
	"""rows = list(ws.iter_rows(values_only=True))。返回 (start_date, end_date, [record])。
	record = _dict(name, user_id, days=[_dict(date, **parse_day_cell)])。"""
	title = " ".join(str(c) for c in rows[0] if c)
	m = re.search(r"(\d{4}-\d{2}-\d{2})\D+(\d{4}-\d{2}-\d{2})", title)
	start_date, end_date = (getdate(m.group(1)), getdate(m.group(2))) if m else (None, None)
	hdr = rows[2]

	def col(label):
		for i, c in enumerate(hdr):
			if c and label in str(c):
				return i
		return None

	name_c, uid_c, day_start = col("姓名"), col("UserId"), col("考勤结果")
	if name_c is None or day_start is None or start_date is None:
		frappe.throw("无法识别钉钉月度汇总表头（姓名/UserId/考勤结果/统计日期）")
	n_days = (end_date - start_date).days + 1
	records = []
	for r in rows[4:]:
		if name_c >= len(r) or not r[name_c]:
			continue
		days = []
		for k in range(n_days):
			ci = day_start + k
			parsed = parse_day_cell(r[ci] if ci < len(r) else None)
			if parsed:
				parsed.date = add_days(start_date, k)
				days.append(parsed)
		records.append(
			frappe._dict(
				name=str(r[name_c]).strip(),
				user_id=(str(r[uid_c]).strip() if uid_c is not None and uid_c < len(r) and r[uid_c] else ""),
				days=days,
			)
		)
	return start_date, end_date, records


# --------------------------------------------------------------------------- #
# 以下依赖 DB
# --------------------------------------------------------------------------- #
def _read_xlsx_rows(file_url: str):
	import openpyxl

	path = frappe.get_site_path(file_url.lstrip("/")) if file_url.startswith("/files") else frappe.utils.get_files_path(
		file_url.split("/")[-1]
	)
	wb = openpyxl.load_workbook(path, data_only=True)
	return list(wb.worksheets[0].iter_rows(values_only=True))


def _match_employee(user_id: str, name: str):
	if user_id:
		emp = frappe.db.get_value("Employee", {"attendance_device_id": user_id}, "name")
		if emp:
			return emp
	if name:
		return frappe.db.get_value("Employee", {"employee_name": name, "status": "Active"}, "name")
	return None


def _upsert_attendance(emp, date, status, parsed, company):
	in_dt = f"{date} {parsed.in_time}:00" if parsed.in_time else None
	out_dt = f"{date} {parsed.out_time}:00" if parsed.out_time else None
	vals = {
		"status": status,
		"in_time": in_dt,
		"out_time": out_dt,
		"late_entry": 1 if parsed.get("is_late") else 0,
		"early_exit": 1 if parsed.get("is_early") else 0,
		"custom_punch_summary": parsed.punch_summary,
		"custom_overtime_days": parsed.overtime_days,
	}
	existing = frappe.db.exists("Attendance", {"employee": emp, "attendance_date": str(date), "docstatus": ["<", 2]})
	if existing:
		frappe.db.set_value("Attendance", existing, vals, update_modified=False)
		return "updated"
	doc = frappe.get_doc(
		dict(doctype="Attendance", employee=emp, attendance_date=str(date), company=company, **vals)
	)
	doc.flags.ignore_validate = True
	doc.insert(ignore_permissions=True)
	doc.submit()
	return "created"


def _employee_structure(emp, on_date):
	"""员工在 on_date 生效的最新 SSA 工资结构名（与 get_overtime_amount 同口径）。无则 None。"""
	return frappe.db.get_value(
		"Salary Structure Assignment",
		{"employee": emp, "from_date": ("<=", on_date), "docstatus": 1},
		"salary_structure",
		order_by="from_date desc",
	)


@frappe.whitelist()
def import_monthly_summary(file_url=None, rows=None, company=None):
	"""从钉钉月度汇总建/更 Attendance（状态+in/out+打卡串+加班天）。返回统计。
	加班天仅对「普工结构」员工按阶梯算（非普工=0，调休处理）；无 SSA 的员工记入 no_structure。"""
	if rows is None:
		rows = _read_xlsx_rows(file_url)
	start_date, end_date, records = parse_monthly_summary(rows)
	stat = frappe._dict(
		start=str(start_date), end=str(end_date), created=0, updated=0,
		unmatched=[], no_structure=[],
	)
	for rec in records:
		emp = _match_employee(rec.user_id, rec.name)
		if not emp:
			stat.unmatched.append(rec.name)
			continue
		structure = _employee_structure(emp, start_date)
		if not structure:
			stat.no_structure.append(rec.name)
		is_regular = structure == REGULAR_WORKER_STRUCTURE
		emp_company = company or frappe.db.get_value("Employee", emp, "company")
		for d in rec.days:
			d.overtime_days = daily_overtime_days(d.out_time, d.is_absent, is_regular)
			status = "Absent" if d.is_absent else ("On Leave" if d.is_leave else "Present")
			stat[_upsert_attendance(emp, d.date, status, d, emp_company)] += 1
	return stat


def get_overtime_amount(employee, start_date, end_date):
	"""返回 (加班天合计, 加班金额)。金额 = Σ加班天 × 总月薪/30；总月薪 = SSA base+工龄+等级+证书。"""
	total_days = flt(
		frappe.db.sql(
			"""select coalesce(sum(custom_overtime_days),0) from `tabAttendance`
			where employee=%s and attendance_date between %s and %s and docstatus=1""",
			(employee, start_date, end_date),
		)[0][0]
	)
	if not total_days:
		return 0.0, 0.0
	ssa = frappe.db.get_value(
		"Salary Structure Assignment",
		{"employee": employee, "from_date": ("<=", start_date), "docstatus": 1},
		["base", "custom_seniority_base", "custom_grade_base", "custom_cert_base"],
		order_by="from_date desc",
		as_dict=True,
	)
	if not ssa:
		return total_days, 0.0
	monthly = flt(ssa.base) + flt(ssa.custom_seniority_base) + flt(ssa.custom_grade_base) + flt(ssa.custom_cert_base)
	return total_days, total_days * monthly / 30.0


def apply_overtime_to_salary_slip(doc, method=None):
	"""doc_event: Salary Slip validate。有加班数据则把金额写进「加班」行并修正 gross/net。
	无加班数据(=0)则不动该行（保留手填）。加班行须在该结构里（董事无则跳过）。"""
	if doc.docstatus == 2 or not doc.get("employee") or not doc.get("start_date"):
		return
	_, amount = get_overtime_amount(doc.employee, doc.start_date, doc.end_date)
	if not amount:
		return
	row = next((e for e in doc.get("earnings", []) if e.salary_component == OVERTIME_COMPONENT), None)
	if row is None:
		return
	old = flt(row.amount)
	new_amt = flt(amount, row.precision("amount"))
	if new_amt == old:
		return
	delta = new_amt - old
	row.amount = row.default_amount = new_amt
	doc.gross_pay = flt(doc.gross_pay) + delta
	doc.base_gross_pay = flt(doc.base_gross_pay) + delta * flt(doc.exchange_rate or 1)
	doc.set_net_pay()
