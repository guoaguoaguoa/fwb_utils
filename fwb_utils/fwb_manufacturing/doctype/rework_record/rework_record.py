# Copyright (c) 2025, WenZhou Furui Handicraft Co.,Ltd. and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import flt

from fwb_utils.fwb_manufacturing.doctype.fwb_work_report.fwb_work_report import (
	apply_quality_totals_to_work_report,
)


class ReworkRecord(Document):
	def apply_submitted_rework_record(self):
		apply_submitted_rework_record(self)

	def rollback_cancelled_rework_record(self):
		rollback_cancelled_rework_record(self)


def _get_rework_doc(doc_or_name):
	if isinstance(doc_or_name, Document):
		return doc_or_name
	return frappe.get_doc("Rework Record", doc_or_name)


def _recalculate_work_report_amount(target_doc):
	wage_type = target_doc.wage_type or "计件"

	if wage_type == "计时":
		return

	if target_doc.rework_type == "有偿返工":
		target_doc.total_amount = flt(target_doc.valid_qty) * flt(target_doc.rework_rate or 0)
	else:
		target_doc.total_amount = flt(target_doc.valid_qty) * flt(target_doc.custom_piece_rate or 0)


def _sync_total_quality_inspected(from_work_report, excluded_name=None):
	if not from_work_report:
		return 0

	params = [from_work_report]
	excluded_sql = ""

	if excluded_name:
		excluded_sql = " AND name != %s"
		params.append(excluded_name)

	total_quality_inspected = (
		frappe.db.sql(
			f"""
			SELECT SUM(IFNULL(quality_inspected, 0))
			FROM `tabRework Record`
			WHERE from_work_report = %s
			  AND docstatus = 1
			  {excluded_sql}
			""",
			tuple(params),
		)[0][0]
		or 0
	)

	filters = {"from_work_report": from_work_report, "docstatus": 1}
	if excluded_name:
		filters["name"] = ["!=", excluded_name]

	for name in frappe.db.get_all("Rework Record", filters=filters, pluck="name"):
		frappe.db.set_value(
			"Rework Record",
			name,
			"total_quality_inspected",
			total_quality_inspected,
			update_modified=False,
		)

	return flt(total_quality_inspected)


def apply_submitted_rework_record(doc_or_name):
	doc = _get_rework_doc(doc_or_name)

	if not doc.from_work_report:
		return

	target_doc = frappe.get_doc("FWB Work Report", doc.from_work_report)
	action = (doc.rework_action or "").strip()
	defective_qty = flt(doc.defective_qty)
	reworked_qty = flt(doc.reworked_qty)
	is_changed = False
	old_valid_qty = flt(target_doc.valid_qty or 0)

	if action == "次品扣除" and defective_qty > 0:
		target_doc.defect_qty = flt(target_doc.defect_qty) + defective_qty
		is_changed = True
	elif action == "良品回补" and reworked_qty > 0:
		target_doc.recovered_qty = flt(target_doc.recovered_qty) + reworked_qty
		is_changed = True

	total_quality_inspected = _sync_total_quality_inspected(doc.from_work_report)
	apply_quality_totals_to_work_report(target_doc)
	needs_save = (
		is_changed
		or flt(target_doc.valid_qty or 0) != old_valid_qty
	)

	if needs_save:
		_recalculate_work_report_amount(target_doc)
		target_doc.flags.ignore_validate_update_after_submit = True
		target_doc.save(ignore_permissions=True)

		frappe.msgprint(
			f"✅ 已同步更新生产报工单：\n质检扣除: {target_doc.defect_qty}\n返工回补: {target_doc.recovered_qty}\n有效数量: {target_doc.valid_qty}"
		)

	frappe.db.set_value(
		"Rework Record",
		doc.name,
		"total_quality_inspected",
		total_quality_inspected,
		update_modified=False,
	)


def rollback_cancelled_rework_record(doc_or_name):
	doc = _get_rework_doc(doc_or_name)

	if not doc.from_work_report:
		return

	target_doc = frappe.get_doc("FWB Work Report", doc.from_work_report)
	action = (doc.rework_action or "").strip()
	defective_qty = flt(doc.defective_qty)
	reworked_qty = flt(doc.reworked_qty)
	is_changed = False
	old_valid_qty = flt(target_doc.valid_qty or 0)

	if action == "次品扣除" and defective_qty > 0:
		target_doc.defect_qty = max(0, flt(target_doc.defect_qty) - defective_qty)
		is_changed = True
	elif action == "良品回补" and reworked_qty > 0:
		target_doc.recovered_qty = max(0, flt(target_doc.recovered_qty) - reworked_qty)
		is_changed = True

	_sync_total_quality_inspected(doc.from_work_report, excluded_name=doc.name)
	apply_quality_totals_to_work_report(target_doc, excluded_rework_record=doc.name)
	needs_save = (
		is_changed
		or flt(target_doc.valid_qty or 0) != old_valid_qty
	)

	if needs_save:
		_recalculate_work_report_amount(target_doc)
		frappe.db.set_value(
			"FWB Work Report",
			target_doc.name,
			{
				"defect_qty": target_doc.defect_qty,
				"recovered_qty": target_doc.recovered_qty,
				"valid_qty": target_doc.valid_qty,
				"total_amount": target_doc.total_amount,
			},
			update_modified=False,
		)

		frappe.msgprint(f"✅ 已回滚生产报工单数据，当前金额：{target_doc.total_amount}")



@frappe.whitelist()
def get_rework_history_summary(from_work_report):
	if not from_work_report:
		return {
			"history_count": 0,
			"total_defective_qty": 0,
			"total_reworked_qty": 0,
			"records": [],
		}

	rows = frappe.db.sql(
		"""
		SELECT
			rr.name,
			rr.modified AS submitted_at,
			rr.inspector,
			COALESCE(emp.employee_name, rr.inspector_name_display, rr.inspector, '') AS inspector_name,
			rr.rework_action,
			IFNULL(rr.quality_inspected, 0) AS quality_inspected,
			IFNULL(rr.defective_qty, 0) AS defective_qty,
			IFNULL(rr.reworked_qty, 0) AS reworked_qty,
			IFNULL(rr.penalty_qty, 0) AS penalty_qty
		FROM `tabRework Record` rr
		LEFT JOIN `tabEmployee` emp
			ON emp.name = rr.inspector
		WHERE
			rr.from_work_report = %s
			AND rr.docstatus = 1
		ORDER BY rr.modified DESC, rr.creation DESC
		""",
		(from_work_report,),
		as_dict=True,
	)

	records = []
	total_defective_qty = 0
	total_reworked_qty = 0

	for row in rows:
		row_data = {
			"name": row.name,
			"submitted_at": row.submitted_at,
			"inspector": row.inspector,
			"inspector_name": row.inspector_name or row.inspector or "",
			"rework_action": row.rework_action or "",
			"quality_inspected": flt(row.quality_inspected),
			"defective_qty": flt(row.defective_qty),
			"reworked_qty": flt(row.reworked_qty),
			"penalty_qty": flt(row.penalty_qty),
		}
		total_defective_qty += row_data["defective_qty"]
		total_reworked_qty += row_data["reworked_qty"]
		records.append(row_data)

	return {
		"history_count": len(records),
		"total_defective_qty": total_defective_qty,
		"total_reworked_qty": total_reworked_qty,
		"records": records,
	}
