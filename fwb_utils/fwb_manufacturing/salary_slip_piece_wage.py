from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint, flt

from fwb_utils.fwb_manufacturing.doctype.employee_wage_sheet.employee_wage_sheet import (
	DETAIL_FIELDS_TO_COPY,
	_collect_aggregated_rows,
	_copy_detail_values,
	_format_duration_display,
)

PIECE_WAGE_STRUCTURE = "无底薪计件工结构"
PIECE_WAGE_COMPONENT = "无底薪计件工"
PIECE_WAGE_DETAIL_FIELD = "custom_piece_wage_details"
PIECE_WAGE_TOTAL_QTY_FIELD = "custom_piece_wage_total_qty"
PIECE_WAGE_TOTAL_DURATION_FIELD = "custom_piece_wage_total_duration_seconds"
PIECE_WAGE_TOTAL_AMOUNT_FIELD = "custom_piece_wage_total_amount"


@frappe.whitelist()
def generate_piece_wage_details_for_salary_slip(salary_slip: str) -> dict:
	"""Generate future piece-wage detail rows directly on a draft Salary Slip."""
	if not salary_slip:
		frappe.throw(_("Missing salary slip."))

	_require_payroll_manager()
	doc = frappe.get_doc("Salary Slip", salary_slip)
	_validate_generation_allowed(doc)

	preserved_rows = _get_preserved_manual_rows(doc)
	penalty_overrides = _get_existing_penalty_overrides(doc)
	doc.set(PIECE_WAGE_DETAIL_FIELD, [])
	for row in preserved_rows:
		child = doc.append(PIECE_WAGE_DETAIL_FIELD, {})
		_copy_detail_values(child, row)

	generated_rows = _collect_aggregated_rows(
		employee=doc.employee,
		from_date=doc.start_date,
		to_date=doc.end_date,
	)
	for row in generated_rows:
		child = _append_aggregated_row(doc, row)
		_apply_penalty_override(child, penalty_overrides)

	doc.flags.fwb_sync_piece_wage = True
	totals = _sync_piece_wage_summary_and_component(doc)
	doc.save(ignore_permissions=True)

	return {
		"salary_slip": doc.name,
		"rows": len(doc.get(PIECE_WAGE_DETAIL_FIELD) or []),
		"manual_rows": len(preserved_rows),
		"generated_rows": len(generated_rows),
		"total_qty": totals.total_qty,
		"total_amount": totals.total_amount,
		"total_duration_seconds": totals.total_duration_seconds,
	}


def sync_salary_slip_piece_wage_if_present(doc, method=None):
	"""Doc event hook: keep new Salary Slip piece-wage totals/component in sync.

	This hook intentionally ignores legacy custom_manufacturing_wage_details.
	"""
	if doc.doctype != "Salary Slip":
		return
	if not _has_piece_wage_custom_fields(doc):
		return
	if not _has_piece_wage_state(doc):
		return

	if not is_piece_wage_salary_slip(doc):
		if doc.get(PIECE_WAGE_DETAIL_FIELD):
			frappe.throw(
				_("只有工资结构为「{0}」的工资单可以保存计件工资明细。").format(PIECE_WAGE_STRUCTURE)
			)
		_clear_piece_wage_summary(doc)
		return

	return _sync_piece_wage_summary_and_component(doc)


def is_piece_wage_salary_slip(doc) -> bool:
	return (doc.get("salary_structure") or "").strip() == PIECE_WAGE_STRUCTURE


def _validate_generation_allowed(doc):
	if doc.docstatus != 0:
		frappe.throw(_("只能在草稿工资单生成计件工资明细；已提交工资单请取消并修订。"))
	if not doc.employee or not doc.start_date or not doc.end_date:
		frappe.throw(_("工资单缺少员工或起止日期。"))
	if not _has_piece_wage_custom_fields(doc):
		frappe.throw(_("Salary Slip 缺少计件工资明细字段，请先迁移自定义字段。"))
	if not is_piece_wage_salary_slip(doc):
		frappe.throw(_("只有工资结构为「{0}」的工资单可以从报工生成明细。").format(PIECE_WAGE_STRUCTURE))


def _require_payroll_manager():
	if frappe.session.user == "Administrator":
		return
	roles = set(frappe.get_roles())
	if not ({"System Manager", "HR Manager"} & roles):
		frappe.throw(_("只有 System Manager 或 HR Manager 可以生成计件工资明细。"), frappe.PermissionError)


def _has_piece_wage_custom_fields(doc) -> bool:
	return bool(doc.meta.get_field(PIECE_WAGE_DETAIL_FIELD))


def _has_piece_wage_state(doc) -> bool:
	return bool(
		doc.flags.get("fwb_sync_piece_wage")
		or doc.get(PIECE_WAGE_DETAIL_FIELD)
		or flt(doc.get(PIECE_WAGE_TOTAL_QTY_FIELD))
		or cint(doc.get(PIECE_WAGE_TOTAL_DURATION_FIELD))
		or flt(doc.get(PIECE_WAGE_TOTAL_AMOUNT_FIELD))
	)


def _get_preserved_manual_rows(doc) -> list[dict]:
	preserved = []
	for row in doc.get(PIECE_WAGE_DETAIL_FIELD) or []:
		if row.get("source_work_report"):
			continue
		preserved.append({fieldname: row.get(fieldname) for fieldname in DETAIL_FIELDS_TO_COPY})
	return preserved


def _append_aggregated_row(doc, row):
	child = doc.append(PIECE_WAGE_DETAIL_FIELD, {})
	child.source_work_report = row.get("work_report")
	child.work_order = row.get("work_order")
	child.product_name = row.get("product_name")
	child.size_l = row.get("size_l")
	child.size_w = row.get("size_w")
	child.size_h = row.get("size_h")
	child.workstation = row.get("workstation")
	child.qty = row.get("total_valid_qty")
	child.defect_qty = row.get("total_defect_qty")
	child.defect_rate = row.get("defect_rate")
	child.duration_seconds = row.get("total_duration_seconds")
	child.duration_display = _format_duration_display(row.get("total_duration_seconds"))
	child.is_penalty = row.get("is_penalty", 0)
	child.rate = row.get("rate") or 0
	child.amount = _calculate_row_amount(child)
	return child


def _calculate_row_amount(row) -> float:
	seconds = cint(row.get("duration_seconds") or 0)
	rate = flt(row.get("rate") or 0)
	if seconds > 0:
		return flt(seconds) / 3600.0 * rate
	return flt(row.get("qty") or 0) * rate


def _get_existing_penalty_overrides(doc) -> dict[tuple, dict]:
	overrides = {}
	for row in doc.get(PIECE_WAGE_DETAIL_FIELD) or []:
		if not cint(row.get("is_penalty")) or not row.get("source_work_report"):
			continue
		overrides[_penalty_override_key(row)] = {
			"rate": row.get("rate"),
			"amount": row.get("amount"),
			"remarks": row.get("remarks"),
		}
	return overrides


def _apply_penalty_override(child, overrides: dict[tuple, dict]):
	if not cint(child.get("is_penalty")):
		return
	override = overrides.get(_penalty_override_key(child))
	if not override:
		return
	child.rate = override.get("rate")
	child.amount = override.get("amount")
	child.remarks = override.get("remarks")


def _penalty_override_key(row) -> tuple:
	return (
		row.get("source_work_report") or "",
		row.get("workstation") or "",
		row.get("product_name") or "",
		flt(row.get("qty") or 0),
	)


def _sync_piece_wage_summary_and_component(doc):
	totals = _calculate_piece_wage_totals(doc.get(PIECE_WAGE_DETAIL_FIELD) or [])
	doc.set(PIECE_WAGE_TOTAL_QTY_FIELD, totals.total_qty)
	doc.set(PIECE_WAGE_TOTAL_DURATION_FIELD, totals.total_duration_seconds)
	doc.set(PIECE_WAGE_TOTAL_AMOUNT_FIELD, totals.total_amount)
	_set_piece_wage_component_amount(doc, totals.total_amount)
	_refresh_salary_totals(doc)
	return totals


def _calculate_piece_wage_totals(rows):
	total_qty = 0.0
	total_amount = 0.0
	total_duration_seconds = 0

	for row in rows:
		if row.get("duration_seconds"):
			row.duration_display = _format_duration_display(row.duration_seconds)
		total_qty += flt(row.get("qty") or 0)
		total_duration_seconds += cint(row.get("duration_seconds") or 0)
		if cint(row.get("is_penalty")):
			total_amount -= flt(row.get("amount") or 0)
		else:
			total_amount += flt(row.get("amount") or 0)

	return frappe._dict(
		total_qty=total_qty,
		total_amount=total_amount,
		total_duration_seconds=total_duration_seconds,
	)


def _set_piece_wage_component_amount(doc, amount: float):
	if not frappe.db.exists("Salary Component", PIECE_WAGE_COMPONENT):
		frappe.throw(_("工资构成「{0}」不存在，无法同步计件金额。").format(PIECE_WAGE_COMPONENT))

	row = next(
		(earning for earning in doc.get("earnings", []) if earning.salary_component == PIECE_WAGE_COMPONENT),
		None,
	)
	if row is None:
		row = doc.append(
			"earnings",
			{
				"salary_component": PIECE_WAGE_COMPONENT,
				"abbr": _component_abbr(PIECE_WAGE_COMPONENT),
			},
		)

	precision = row.precision("amount")
	target = flt(amount, precision)
	row.amount = target
	row.default_amount = target
	row.additional_amount = 0
	row.amount_based_on_formula = 0
	row.formula = None
	row.depends_on_payment_days = 0


def _component_abbr(component):
	return frappe.db.get_value("Salary Component", component, "salary_component_abbr") or str(component)[:6]


def _refresh_salary_totals(doc):
	if doc.get("salary_structure") and not getattr(doc, "_salary_structure_doc", None):
		doc.set_salary_structure_doc()
	doc.gross_pay = doc.get_component_totals("earnings", depends_on_payment_days=1)
	doc.base_gross_pay = flt(
		flt(doc.gross_pay) * flt(doc.exchange_rate or 1),
		doc.precision("base_gross_pay"),
	)
	doc.set_net_pay()
	if hasattr(doc, "compute_year_to_date"):
		doc.compute_year_to_date()
	if hasattr(doc, "compute_month_to_date"):
		doc.compute_month_to_date()
	if hasattr(doc, "compute_component_wise_year_to_date"):
		doc.compute_component_wise_year_to_date()


def _clear_piece_wage_summary(doc):
	doc.set(PIECE_WAGE_TOTAL_QTY_FIELD, 0)
	doc.set(PIECE_WAGE_TOTAL_DURATION_FIELD, 0)
	doc.set(PIECE_WAGE_TOTAL_AMOUNT_FIELD, 0)


def preview_wage_sheet_piece_wage_reconciliation(
	wage_sheet: str,
	manual_indexes: list[int] | None = None,
	compare_old_rows: bool = True,
) -> dict:
	"""Return an in-memory old-vs-new piece wage preview for data reconciliation.

	No Salary Slip is inserted or saved.
	"""
	ws = frappe.get_doc("Employee Wage Sheet", wage_sheet)
	manual_indexes = {cint(idx) for idx in (manual_indexes or [])}

	doc = frappe.new_doc("Salary Slip")
	doc.employee = ws.employee
	doc.company = (
		frappe.db.get_value("Employee", ws.employee, "company")
		or frappe.defaults.get_global_default("company")
	)
	doc.start_date = ws.from_date
	doc.end_date = ws.to_date
	doc.posting_date = ws.to_date
	doc.payroll_frequency = "Monthly"
	doc.salary_structure = PIECE_WAGE_STRUCTURE
	doc.exchange_rate = 1

	selected_manual_rows = []
	for old in ws.details or []:
		if manual_indexes and cint(old.idx) in manual_indexes:
			row_data = {fieldname: old.get(fieldname) for fieldname in DETAIL_FIELDS_TO_COPY}
			selected_manual_rows.append(row_data)
			child = doc.append(PIECE_WAGE_DETAIL_FIELD, {})
			_copy_detail_values(child, row_data)
		elif cint(old.get("is_penalty")) and old.get("source_work_report"):
			child = doc.append(PIECE_WAGE_DETAIL_FIELD, {})
			_copy_detail_values(
				child,
				{fieldname: old.get(fieldname) for fieldname in DETAIL_FIELDS_TO_COPY},
			)

	penalty_overrides = _get_existing_penalty_overrides(doc)
	doc.set(PIECE_WAGE_DETAIL_FIELD, [])

	for row_data in selected_manual_rows:
		child = doc.append(PIECE_WAGE_DETAIL_FIELD, {})
		_copy_detail_values(child, row_data)

	for row in _collect_aggregated_rows(ws.employee, ws.from_date, ws.to_date):
		child = _append_aggregated_row(doc, row)
		_apply_penalty_override(child, penalty_overrides)

	new_rows = doc.get(PIECE_WAGE_DETAIL_FIELD) or []
	new_totals = _calculate_piece_wage_totals(new_rows)
	_set_piece_wage_component_amount(doc, new_totals.total_amount)
	earning = next(
		(row for row in doc.earnings if row.salary_component == PIECE_WAGE_COMPONENT),
		None,
	)

	result = {
		"wage_sheet": ws.name,
		"salary_slip": ws.salary_slip,
		"employee": ws.employee_name,
		"period": f"{ws.from_date}..{ws.to_date}",
		"old_totals": _preview_signed_totals(ws.details or []),
		"new_totals": _preview_signed_totals(new_rows),
		"earning_amount": flt(earning.amount) if earning else None,
		"selected_manual_indexes": sorted(manual_indexes),
		"selected_manual_amount": sum(flt(row.get("amount") or 0) for row in selected_manual_rows),
		"manual_rows_kept_at_top": [
			{
				"idx": idx + 1,
				"product_name": new_rows[idx].product_name,
				"amount": flt(new_rows[idx].amount),
				"source_work_report": new_rows[idx].source_work_report,
			}
			for idx in range(len(selected_manual_rows))
		],
	}

	if compare_old_rows:
		differences = _preview_group_differences(ws.details or [], new_rows)
		result["difference_count"] = len(differences)
		result["first_differences"] = differences[:5]

	return result


def _preview_signed_totals(rows) -> dict:
	return {
		"rows": len(rows),
		"qty": sum(flt(row.get("qty") or 0) for row in rows),
		"duration_seconds": sum(cint(row.get("duration_seconds") or 0) for row in rows),
		"amount": sum(
			-flt(row.get("amount") or 0)
			if cint(row.get("is_penalty"))
			else flt(row.get("amount") or 0)
			for row in rows
		),
		"penalty_rows": sum(1 for row in rows if cint(row.get("is_penalty"))),
		"manual_rows": sum(1 for row in rows if not row.get("source_work_report")),
	}


def _preview_group_differences(old_rows, new_rows) -> list[dict]:
	old_groups = _preview_group_rows(old_rows)
	new_groups = _preview_group_rows(new_rows)
	differences = []
	for row_key in sorted(set(old_groups) | set(new_groups)):
		old = old_groups.get(row_key, _empty_preview_group())
		new = new_groups.get(row_key, _empty_preview_group())
		if old != new:
			differences.append({"key": row_key, "old": old, "new": new})
	return differences


def _preview_group_rows(rows) -> dict:
	groups = defaultdict(_empty_preview_group)
	for row in rows:
		item = groups[_preview_row_key(row)]
		item["count"] += 1
		item["rate"] += flt(row.get("rate") or 0)
		item["amount"] += flt(row.get("amount") or 0)
		item["duration_seconds"] += cint(row.get("duration_seconds") or 0)
	return groups


def _empty_preview_group() -> dict:
	return {"count": 0, "rate": 0.0, "amount": 0.0, "duration_seconds": 0}


def _preview_row_key(row) -> tuple:
	return (
		row.get("source_work_report") or "",
		row.get("workstation") or "",
		row.get("product_name") or "",
		flt(row.get("qty") or 0),
		cint(row.get("is_penalty")),
	)
