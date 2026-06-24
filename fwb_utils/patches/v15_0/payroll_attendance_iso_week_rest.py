import frappe

from fwb_utils.fwb_manufacturing.doctype.payroll_attendance_parameter.payroll_attendance_parameter import (
	DEFAULT_NON_WORKER_DOUBLE_REST_WEEK_PARITY,
	DEFAULT_NON_WORKER_REST_CALCULATION_MODE,
)


def execute():
	doc = frappe.get_single("Payroll Attendance Parameter")
	changed = False
	if not str(doc.get("non_worker_rest_calculation_mode") or "").strip():
		doc.non_worker_rest_calculation_mode = DEFAULT_NON_WORKER_REST_CALCULATION_MODE
		changed = True
	if not str(doc.get("non_worker_double_rest_week_parity") or "").strip():
		doc.non_worker_double_rest_week_parity = DEFAULT_NON_WORKER_DOUBLE_REST_WEEK_PARITY
		changed = True
	if changed:
		doc.save(ignore_permissions=True)
	frappe.clear_cache(doctype="Payroll Attendance Parameter")
