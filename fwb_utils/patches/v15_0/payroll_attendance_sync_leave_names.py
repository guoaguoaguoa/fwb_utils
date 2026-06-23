import frappe

from fwb_utils.fwb_manufacturing.doctype.payroll_attendance_parameter.payroll_attendance_parameter import (
	DEFAULT_SYNC_LEAVE_NAMES,
)


def execute():
	doc = frappe.get_single("Payroll Attendance Parameter")
	if str(doc.get("sync_leave_names") or "").strip():
		return
	doc.sync_leave_names = DEFAULT_SYNC_LEAVE_NAMES
	doc.save(ignore_permissions=True)
