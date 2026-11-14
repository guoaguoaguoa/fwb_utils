"""增加回补确认/来源字段，不推断或回填任何历史确认时间。"""
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	frappe.reload_doc("fwb_manufacturing", "doctype", "rework_record", force=True)
	frappe.reload_doc("fwb_manufacturing", "doctype", "employee_wage_sheet_detail", force=True)
	create_custom_fields({"Salary Slip": [{
		"fieldname": "custom_piece_wage_confirmed_at", "fieldtype": "Datetime",
		"label": "计件工资核定时间", "insert_after": "custom_piece_wage_total_amount",
		"read_only": 1, "no_copy": 1,
		"depends_on": "eval:doc.docstatus==1",
	}]}, update=True)
	# field_order 属性会覆盖原生顺序；同步新字段，避免升级后页面漏显示。
	name = "Salary Slip-main-field_order"
	if frappe.db.exists("Property Setter", name):
		setter = frappe.get_doc("Property Setter", name)
		order = frappe.parse_json(setter.value)
		field = "custom_piece_wage_confirmed_at"
		if field not in order:
			order.insert(order.index("custom_piece_wage_total_amount") + 1, field)
			setter.value = frappe.as_json(order)
			setter.save(ignore_permissions=True)
