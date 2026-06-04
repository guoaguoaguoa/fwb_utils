import frappe


def execute():
	"""保留 0 元餐补行，避免新工资单因无公式而隐藏餐补组件。"""
	if frappe.db.exists("Salary Component", "餐补"):
		frappe.db.set_value(
			"Salary Component",
			"餐补",
			"remove_if_zero_valued",
			0,
			update_modified=False,
		)
