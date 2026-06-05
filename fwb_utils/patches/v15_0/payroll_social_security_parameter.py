import frappe


def execute():
	"""Keep social security salary components hidden at zero; amounts are written by the salary slip button."""
	component_defaults = {
		"社保-个人": {
			"remove_if_zero_valued": 1,
			"depends_on_payment_days": 0,
			"is_tax_applicable": 0,
		},
		"社保-单位": {
			"remove_if_zero_valued": 1,
			"depends_on_payment_days": 0,
			"do_not_include_in_total": 1,
			"is_tax_applicable": 0,
		},
	}
	for component, values in component_defaults.items():
		if frappe.db.exists("Salary Component", component):
			frappe.db.set_value("Salary Component", component, values, update_modified=False)
