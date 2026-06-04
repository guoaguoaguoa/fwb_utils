import frappe


NON_WORKER_STRUCTURES = (
	"内贸业务员结构",
	"外贸业务员结构",
	"美工结构",
	"行政结构",
)

FIXED_COMPONENTS = ("底薪", "工龄补贴", "等级工资", "证书津贴")
LATE_DEDUCTION_COMPONENT = "迟到扣款"
EARLY_DEDUCTION_COMPONENT = "早退扣款"
ADMIN_MANUAL_EARNING = "内贸提成"


def execute():
	"""非普工固定工资由工资单按钮托管，并补早退扣款/行政内贸提成常驻行。"""
	_ensure_salary_component(EARLY_DEDUCTION_COMPONENT, "Deduction", "ETD")
	_ensure_salary_component(LATE_DEDUCTION_COMPONENT, "Deduction", "LTD")
	_ensure_salary_component(ADMIN_MANUAL_EARNING, "Earning", "NMTC")

	for component in (*FIXED_COMPONENTS, LATE_DEDUCTION_COMPONENT, EARLY_DEDUCTION_COMPONENT, ADMIN_MANUAL_EARNING):
		if frappe.db.exists("Salary Component", component):
			frappe.db.set_value(
				"Salary Component",
				component,
				{
					"depends_on_payment_days": 0,
					"amount_based_on_formula": 0,
					"formula": None,
					"remove_if_zero_valued": 0,
				},
				update_modified=False,
			)

	for structure in NON_WORKER_STRUCTURES:
		_clear_structure_formula_rows(structure, "earnings", FIXED_COMPONENTS)
		_ensure_structure_row(structure, "deductions", EARLY_DEDUCTION_COMPONENT)

	_clear_structure_formula_rows("行政结构", "earnings", (ADMIN_MANUAL_EARNING,))
	_ensure_structure_row("行政结构", "earnings", ADMIN_MANUAL_EARNING)


def _ensure_salary_component(component, component_type, abbr):
	if frappe.db.exists("Salary Component", component):
		frappe.db.set_value(
			"Salary Component",
			component,
			{
				"type": component_type,
				"salary_component_abbr": frappe.db.get_value("Salary Component", component, "salary_component_abbr") or abbr,
				"depends_on_payment_days": 0,
				"is_tax_applicable": 1 if component_type == "Earning" else 0,
				"amount_based_on_formula": 0,
				"amount": 0,
				"formula": None,
				"remove_if_zero_valued": 0,
			},
			update_modified=False,
		)
		return

	doc = frappe.get_doc(
		{
			"doctype": "Salary Component",
			"salary_component": component,
			"salary_component_abbr": abbr,
			"type": component_type,
			"depends_on_payment_days": 0,
			"is_tax_applicable": 1 if component_type == "Earning" else 0,
			"amount_based_on_formula": 0,
			"amount": 0,
			"remove_if_zero_valued": 0,
		}
	)
	doc.insert(ignore_permissions=True)


def _clear_structure_formula_rows(structure, parentfield, components):
	if not frappe.db.exists("Salary Structure", structure):
		return
	rows = frappe.get_all(
		"Salary Detail",
		filters={
			"parenttype": "Salary Structure",
			"parent": structure,
			"parentfield": parentfield,
			"salary_component": ["in", components],
		},
		pluck="name",
	)
	for row_name in rows:
		frappe.db.set_value(
			"Salary Detail",
			row_name,
			{
				"depends_on_payment_days": 0,
				"amount_based_on_formula": 0,
				"formula": None,
				"amount": 0,
				"default_amount": 0,
			},
			update_modified=False,
		)


def _ensure_structure_row(structure, parentfield, component):
	if not frappe.db.exists("Salary Structure", structure) or not frappe.db.exists("Salary Component", component):
		return
	existing = frappe.db.exists(
		"Salary Detail",
		{
			"parenttype": "Salary Structure",
			"parent": structure,
			"parentfield": parentfield,
			"salary_component": component,
		},
	)
	if existing:
		frappe.db.set_value(
			"Salary Detail",
			existing,
			{
				"depends_on_payment_days": 0,
				"amount_based_on_formula": 0,
				"formula": None,
				"amount": 0,
				"default_amount": 0,
			},
			update_modified=False,
		)
		return

	idx = (
		frappe.db.sql(
			"""select coalesce(max(idx), 0) + 1
			from `tabSalary Detail`
			where parent=%s and parenttype='Salary Structure' and parentfield=%s""",
			(structure, parentfield),
		)[0][0]
		or 1
	)
	component_doc = frappe.db.get_value(
		"Salary Component",
		component,
		[
			"salary_component_abbr",
			"depends_on_payment_days",
			"is_tax_applicable",
			"variable_based_on_taxable_salary",
			"statistical_component",
			"do_not_include_in_total",
		],
		as_dict=True,
	)
	row = frappe.get_doc(
		{
			"doctype": "Salary Detail",
			"parent": structure,
			"parenttype": "Salary Structure",
			"parentfield": parentfield,
			"idx": idx,
			"docstatus": 1,
			"salary_component": component,
			"abbr": component_doc.salary_component_abbr,
			"depends_on_payment_days": 0,
			"is_tax_applicable": component_doc.is_tax_applicable if parentfield == "earnings" else 0,
			"variable_based_on_taxable_salary": component_doc.variable_based_on_taxable_salary if parentfield == "deductions" else 0,
			"statistical_component": component_doc.statistical_component,
			"do_not_include_in_total": component_doc.do_not_include_in_total,
			"amount_based_on_formula": 0,
			"formula": None,
			"amount": 0,
			"default_amount": 0,
		}
	)
	row.insert(ignore_permissions=True)
