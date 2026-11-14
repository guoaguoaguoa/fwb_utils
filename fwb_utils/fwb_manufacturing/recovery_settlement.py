"""回补结算：生产事实留在原报工，核定后的计件回补按确认日期补发。"""

from collections import defaultdict

import frappe
from frappe.utils import flt, get_datetime, getdate, now_datetime

CONFIRMED_FIELD = "custom_piece_wage_confirmed_at"


def check_recovery_limit(deducted, recovered, requested):
	remaining = flt(deducted) - flt(recovered)
	if flt(requested) < 0 or flt(requested) > max(0, remaining):
		frappe.throw(f"回补数量超过原扣除数量：累计扣除 {flt(deducted):g}，已回补 {flt(recovered):g}，本次最多回补 {max(0, remaining):g}。")


def confirmation_time(slip):
	return slip.get(CONFIRMED_FIELD)


def is_after_confirmation(recovery_time, salary_time):
	return bool(recovery_time and salary_time and get_datetime(recovery_time) > get_datetime(salary_time))


def stamp_salary_confirmation(doc, method=None):
	if doc.salary_structure != "无底薪计件工结构" or not doc.meta.has_field(CONFIRMED_FIELD):
		return
	# 草稿中暂存最近生成时间；提交后才是不可变核定时间。未重新生成的历史草稿不启用。
	generated_at = doc.get(CONFIRMED_FIELD)
	if not generated_at:
		if any(row.get("source_work_report") for row in doc.get("custom_piece_wage_details") or []):
			frappe.throw("请先点击“从报工生成明细”刷新本单，再提交核定工资；复制或修订单不能沿用旧核定时间。")
		return
	changed = frappe.db.sql("""select r.name from `tabRework Record` r
		join `tabFWB Work Report` w on w.name=r.from_work_report
		where r.docstatus=1 and r.confirmed_at>%s and w.employee=%s
		and date(w.created_at) between %s and %s limit 1""",
		(generated_at,doc.employee,doc.start_date,doc.end_date))
	if changed:
		frappe.throw("明细生成后又有质检扣除或回补，请先点击“从报工生成明细”刷新，再提交核定工资。")
	doc.set(CONFIRMED_FIELD, now_datetime())


def clear_new_salary_confirmation(doc, method=None):
	# 普通复制、Python copy_doc 默认选项和 amend 对 no_copy 的处理并不相同。
	# 新单明确清空，不能依赖客户端复制行为。
	if doc.meta.has_field(CONFIRMED_FIELD):
		doc.set(CONFIRMED_FIELD, None)


def mark_salary_details_generated(doc):
	if doc.meta.has_field(CONFIRMED_FIELD):
		doc.set(CONFIRMED_FIELD, now_datetime())


def protect_original_salary_cancellation(doc, method=None):
	if not confirmation_time(doc) or not schema_ready():
		return
	used = frappe.db.sql("""select distinct s.name from `tabSalary Slip` s
		join `tabEmployee Wage Sheet Detail` d on d.parent=s.name
		join `tabFWB Work Report` w on w.name=d.source_work_report
		where s.docstatus=1 and s.name!=%s and s.employee=%s and d.parenttype='Salary Slip'
		and ifnull(d.source_rework_record,'')!='' and date(w.created_at) between %s and %s limit 1""",
		(doc.name,doc.employee,doc.start_date,doc.end_date))
	if used:
		frappe.throw(f"后续核定工资单 {used[0][0]} 已引用本期回补，不能直接取消原核定工资。")


def schema_ready():
	return (
		frappe.get_meta("Salary Slip").has_field(CONFIRMED_FIELD)
		and frappe.get_meta("Rework Record").has_field("confirmed_at")
		and frappe.get_meta("Employee Wage Sheet Detail").has_field("source_rework_record")
	)


def make_recovery_row(event, original):
	return frappe._dict(
		work_report=event.from_work_report, work_order=event.work_order,
		workstation=event.workstation, product_name=event.product_name,
		size_l="", size_w="", size_h="", total_valid_qty=flt(event.reworked_qty),
		total_defect_qty=0, defect_rate=0, total_duration_seconds=0,
		rate=flt(original.rate), is_penalty=0,
		source_rework_record=event.name, settlement_date=getdate(event.confirmed_at),
		remarks=f"往期计件工资回补；原报工 {event.from_work_report}；回补单 {event.name}；原工资单 {original.name}；{flt(event.reworked_qty):g} × 原结算单价 {flt(original.rate):g}。" + (event.get("remark") or ""),
	)


def apply_recovery_settlement(rows, employee, from_date, to_date):
	"""同一事件只出现在确认期间；核定前回补已包含原工资，不另外生成。历史无时间不启用。"""
	if not schema_ready():
		return rows
	events = frappe.db.sql("""
		select r.name, r.from_work_report, r.reworked_qty, r.confirmed_at, r.remark,
		       w.created_at as report_date, w.work_order, w.workstation, w.product_name
		from `tabRework Record` r join `tabFWB Work Report` w on w.name=r.from_work_report
		where r.docstatus=1 and r.rework_action='良品回补' and r.confirmed_at is not null
		  and w.docstatus=1 and w.employee=%s and ifnull(w.wage_type,'计件')!='计时'
		  and (date(w.created_at) between %s and %s or date(r.confirmed_at) between %s and %s)
		order by r.confirmed_at,r.name
	""", (employee, from_date, to_date, from_date, to_date), as_dict=True)
	if not events:
		return rows
	names = tuple({e.from_work_report for e in events})
	originals = frappe.db.sql(f"""
		select s.name, s.{CONFIRMED_FIELD}, d.source_work_report, d.rate, d.duration_seconds,
		       s.start_date,s.end_date,
		       exists(select 1 from `tabRework Record` q where q.from_work_report=d.source_work_report
		           and q.docstatus=1 and q.rework_action='次品扣除'
		           and ifnull(q.defective_qty,0)>0 and q.confirmed_at>s.{CONFIRMED_FIELD}) as has_late_deduction
		from `tabSalary Slip` s join `tabEmployee Wage Sheet Detail` d on d.parent=s.name
		join `tabFWB Work Report` w on w.name=d.source_work_report
		where s.docstatus=1 and s.employee=%s and s.salary_structure='无底薪计件工结构'
		  and s.{CONFIRMED_FIELD} is not null and d.parenttype='Salary Slip'
		  and d.parentfield='custom_piece_wage_details' and ifnull(d.is_penalty,0)=0
		  and ifnull(d.source_rework_record,'')='' and d.source_work_report in %s
		  and date(w.created_at) between s.start_date and s.end_date
		order by s.{CONFIRMED_FIELD},d.idx
	""", (employee, names), as_dict=True)
	by_report = {}
	for original in originals:
		by_report.setdefault(original.source_work_report, original)
	late_qty = defaultdict(float)
	additions = []
	for event in events:
		original = by_report.get(event.from_work_report)
		if not original or original.duration_seconds or not is_after_confirmation(event.confirmed_at, confirmation_time(original)):
			continue
		if original.get("has_late_deduction"):
			frappe.throw(f"原报工 {event.from_work_report} 在工资核定后又新增了次品扣除，不能把未实际扣薪的数量直接补发。请核对原工资单 {original.name} 的扣薪情况后处理；本轮不自动处理核定后新增扣除的补扣工资。")
		late_qty[event.from_work_report] += flt(event.reworked_qty)
		if getdate(from_date) <= getdate(event.confirmed_at) <= getdate(to_date):
			additions.append(make_recovery_row(event, original))
	for row in rows:
		if row.get("is_penalty") or row.get("total_duration_seconds"):
			continue
		if row.work_report in late_qty:
			row.total_valid_qty = max(0, flt(row.total_valid_qty) - late_qty[row.work_report])
			row.rate = flt(by_report[row.work_report].rate)
	return rows + additions


def recovery_employee_ids(from_date, to_date):
	if not schema_ready():
		return []
	return frappe.db.sql("""select distinct w.employee from `tabRework Record` r
		join `tabFWB Work Report` w on w.name=r.from_work_report
		where r.docstatus=1 and r.rework_action='良品回补'
		and date(r.confirmed_at) between %s and %s and w.docstatus=1
		and w.employee is not null""", (from_date,to_date), pluck=True)
