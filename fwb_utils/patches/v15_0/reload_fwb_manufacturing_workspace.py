import json
import os

import frappe


def execute():
	workspace_json = frappe.get_app_path(
		"fwb_utils",
		"fwb_manufacturing",
		"workspace",
		"fwb_manufacturing",
		"fwb_manufacturing.json",
	)
	if not os.path.exists(workspace_json):
		return

	with open(workspace_json) as f:
		data = json.load(f)

	previous_in_patch = getattr(frappe.flags, "in_patch", False)
	frappe.flags.in_patch = True
	try:
		_sync_workspace(data)
	finally:
		frappe.flags.in_patch = previous_in_patch
	frappe.clear_cache(doctype="Workspace")


def _sync_workspace(data):
	name = data.get("name")
	if not name:
		return

	if frappe.db.exists("Workspace", name):
		doc = frappe.get_doc("Workspace", name)
	else:
		doc = frappe.new_doc("Workspace")
		doc.name = name

	for fieldname, value in data.items():
		if fieldname in {"doctype", "name", "creation", "modified", "modified_by", "owner", "idx", "docstatus"}:
			continue
		if isinstance(value, list):
			doc.set(fieldname, [])
			for row in value:
				doc.append(fieldname, row)
		else:
			doc.set(fieldname, value)

	doc.save(ignore_permissions=True)
