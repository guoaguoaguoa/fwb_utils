# Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and Contributors
# See license.txt
"""钉钉「月度汇总」导入 + 加班自动结算（设计文档 §7.6.2）。

规则（用户 2026-05-31 确认）：
- 加班：某日**下班打卡 ≥ 20:30**（=17:00 + 3.5h）记 **0.5 天**；不分工作日/休息日/节假日（一口价半天工资）。
- 半天工资 = 总月薪/30/2；总月薪 = SSA(base + 工龄/等级/证书基数)。
- 加班金额 = Σ(每日加班天) × 总月薪/30，由 doc_event 写进工资单「加班」行。

纯逻辑（parse_day_cell / overtime_half_days / parse_monthly_summary）不依赖 DB，可沙箱单测。
"""
from __future__ import annotations

import re

import frappe
from frappe.utils import add_days, flt, getdate

OT_CUTOFF = "20:30"  # 17:00 + 3.5h
HALF_DAY = 0.5
OVERTIME_COMPONENT = "加班"


def _to_minutes(hhmm: str) -> int:
	h, m = hhmm.split(":")
	return int(h) * 60 + int(m)


def overtime_half_days(out_time, is_absent: bool = False, cutoff: str = OT_CUTOFF) -> float:
	"""下班打卡 ≥ cutoff(默认 20:30) 记 0.5 天，否则 0；旷工 / 无下班卡 = 0。"""
	if is_absent or not out_time:
		return 0.0
	try:
		return HALF_DAY if _to_minutes(out_time) >= _to_minutes(cutoff) else 0.0
	except (ValueError, AttributeError):
		return 0.0


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
		overtime_days=overtime_half_days(times[-1] if times else None, is_absent),
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


@frappe.whitelist()
def import_monthly_summary(file_url=None, rows=None, company=None):
	"""从钉钉月度汇总建/更 Attendance（状态+in/out+打卡串+加班天）。返回统计。"""
	if rows is None:
		rows = _read_xlsx_rows(file_url)
	start_date, end_date, records = parse_monthly_summary(rows)
	stat = frappe._dict(start=str(start_date), end=str(end_date), created=0, updated=0, unmatched=[])
	for rec in records:
		emp = _match_employee(rec.user_id, rec.name)
		if not emp:
			stat.unmatched.append(rec.name)
			continue
		emp_company = company or frappe.db.get_value("Employee", emp, "company")
		for d in rec.days:
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
