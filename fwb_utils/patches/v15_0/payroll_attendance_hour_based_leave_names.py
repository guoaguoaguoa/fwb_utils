import frappe

from fwb_utils.fwb_manufacturing.doctype.payroll_attendance_parameter.payroll_attendance_parameter import (
	DEFAULT_HOUR_BASED_LEAVE_NAMES,
)


def execute():
	doc = frappe.get_single("Payroll Attendance Parameter")
	if str(doc.get("hour_based_leave_names") or "").strip():
		return
	doc.hour_based_leave_names = DEFAULT_HOUR_BASED_LEAVE_NAMES
	doc.save(ignore_permissions=True)
