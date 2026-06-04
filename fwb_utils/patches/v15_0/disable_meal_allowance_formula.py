import frappe


MEAL_ALLOWANCE_STRUCTURES = (
	"内贸业务员结构",
	"外贸业务员结构",
	"美工结构",
	"行政结构",
)


def execute():
	"""餐补由工资单按钮按实际到岗天数写入，不再让 Salary Structure 公式随保存/提交重算。"""
	if frappe.db.exists("Salary Component", "餐补"):
		frappe.db.set_value(
			"Salary Component",
			"餐补",
			"remove_if_zero_valued",
			0,
			update_modified=False,
		)

	rows = frappe.get_all(
		"Salary Detail",
		filters={
			"parenttype": "Salary Structure",
			"parentfield": "earnings",
			"parent": ["in", MEAL_ALLOWANCE_STRUCTURES],
			"salary_component": "餐补",
		},
		pluck="name",
	)
	for row_name in rows:
		frappe.db.set_value(
			"Salary Detail",
			row_name,
			{
				"amount_based_on_formula": 0,
				"formula": None,
				"amount": 0,
				"default_amount": 0,
			},
			update_modified=False,
		)
