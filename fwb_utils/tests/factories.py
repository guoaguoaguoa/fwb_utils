# Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and Contributors
# See license.txt

from __future__ import annotations

import frappe
from frappe.utils import flt, now_datetime

from erpnext.manufacturing.doctype.workstation.test_workstation import make_workstation
from erpnext.setup.doctype.employee.test_employee import make_employee


def ensure_test_employment_type(employee_type_name="Intern"):
	if not frappe.db.exists("Employment Type", employee_type_name):
		frappe.get_doc(
			{
				"doctype": "Employment Type",
				"employee_type_name": employee_type_name,
			}
		).insert(ignore_permissions=True)
	return employee_type_name


def ensure_test_employee(user_email, employee_name=None, **kwargs):
	ensure_test_employment_type(kwargs.get("employment_type", "Intern"))
	if employee_name:
		kwargs.setdefault("first_name", employee_name)

	existing_employee = frappe.db.get_value("Employee", {"user_id": user_email}, "name")
	if existing_employee:
		employee = frappe.get_doc("Employee", existing_employee)
		employee.update(kwargs)
		employee.status = "Active"
		employee.save(ignore_permissions=True)
		return employee

	employee = make_employee(
		user_email,
		company=kwargs.pop("company", "_Test Company"),
		**kwargs,
	)
	return frappe.get_doc("Employee", employee)


def ensure_test_workstation(workstation_name):
	return make_workstation(workstation_name=workstation_name)


def make_fwb_work_report(
	*,
	employee,
	workstation,
	qty=100,
	custom_piece_rate=1,
	rework_rate=0,
	wage_type="计件",
	rework_type="否",
	defect_qty=0,
	recovered_qty=0,
	valid_qty=None,
	total_amount=None,
	created_at=None,
):
	created_at = created_at or now_datetime()
	valid_qty = flt(qty) - flt(defect_qty) + flt(recovered_qty) if valid_qty is None else flt(valid_qty)

	if total_amount is None:
		if wage_type == "计时":
			total_amount = 0
		elif rework_type == "有偿返工":
			total_amount = valid_qty * flt(rework_rate)
		else:
			total_amount = valid_qty * flt(custom_piece_rate)

	doc = frappe.get_doc(
		{
			"doctype": "FWB Work Report",
			"employee": employee,
			"employee_name_display": frappe.db.get_value("Employee", employee, "employee_name"),
			"workstation": workstation,
			"wage_type": wage_type,
			"rework_type": rework_type,
			"qty": qty,
			"defect_qty": defect_qty,
			"recovered_qty": recovered_qty,
			"valid_qty": valid_qty,
			"custom_piece_rate": custom_piece_rate,
			"rework_rate": rework_rate,
			"total_amount": total_amount,
			"created_at": created_at,
			"report_date": str(created_at)[:10],
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


def make_rework_record(
	*,
	from_work_report,
	employee=None,
	workstation=None,
	inspector=None,
	rework_action="次品扣除",
	quality_inspected=0,
	defective_qty=0,
	reworked_qty=0,
	is_penalty=0,
	penalty_qty=0,
	created_at=None,
):
	report = frappe.get_doc("FWB Work Report", from_work_report)
	created_at = created_at or now_datetime()
	inspector_name = frappe.db.get_value("Employee", inspector, "employee_name") if inspector else ""

	doc = frappe.get_doc(
		{
			"doctype": "Rework Record",
			"from_work_report": from_work_report,
			"employee": employee or report.employee,
			"workstation": workstation or report.workstation,
			"work_order": report.work_order,
			"inspector": inspector,
			"inspector_name_display": inspector_name,
			"rework_action": rework_action,
			"quality_inspected": quality_inspected,
			"defective_qty": defective_qty,
			"reworked_qty": reworked_qty,
			"is_penalty": is_penalty,
			"penalty_qty": penalty_qty,
			"created_at": created_at,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc
