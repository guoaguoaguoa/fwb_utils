import frappe

from fwb_utils.patches.v15_0.reload_fwb_manufacturing_workspace import execute as reload_workspace


WORKSPACE = "FWB Manufacturing"
LEGACY_WAGE_LINKS = ("Employee Wage Sheet", "Employee Wage Sheet Detail")


def execute():
	reload_workspace()
	_delete_workspace_rows("Workspace Link")
	_delete_workspace_rows("Workspace Shortcut")
	frappe.clear_cache(doctype="Workspace")


def _delete_workspace_rows(doctype):
	for link_to in LEGACY_WAGE_LINKS:
		for name in frappe.get_all(
			doctype,
			filters={"parent": WORKSPACE, "link_to": link_to},
			pluck="name",
		):
			frappe.db.delete(doctype, {"name": name})
