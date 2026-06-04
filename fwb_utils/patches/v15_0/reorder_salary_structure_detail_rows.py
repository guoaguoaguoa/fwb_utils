import frappe

NON_WORKER_STRUCTURES = ("内贸业务员结构", "外贸业务员结构", "美工结构", "行政结构")
REGULAR_STRUCTURE = "普工结构"

# 收入：固定工资4项聚一起 → 餐补 → 提成 → 节日/加班/其他 → 社保统计垫底。
NON_WORKER_EARNINGS = [
	"底薪", "工龄补贴", "等级工资", "证书津贴", "餐补",
	"内贸提成", "外贸提成", "节日津贴", "加班", "其他", "社保-单位",
]
# 扣除：考勤扣款(迟到→早退相邻) → 社保 → 代扣(宿舍/水/电) → 预支 → 其他。
NON_WORKER_DEDUCTIONS = [
	"迟到扣款", "早退扣款", "社保-个人", "宿舍租金", "水费", "电费", "工资预支", "其他扣款",
]
REGULAR_EARNINGS = ["底薪", "工龄补贴", "等级工资", "加班", "其他"]
REGULAR_DEDUCTIONS = ["迟到扣款", "早退扣款", "宿舍租金", "水费", "电费", "工资预支", "其他扣款"]


def execute():
	"""按可读性重排薪资明细行序（仅调 idx，不动金额/公式/docstatus）。董事/无底薪计件工不动。"""
	for structure in NON_WORKER_STRUCTURES:
		_reorder(structure, "earnings", NON_WORKER_EARNINGS)
		_reorder(structure, "deductions", NON_WORKER_DEDUCTIONS)
	_reorder(REGULAR_STRUCTURE, "earnings", REGULAR_EARNINGS)
	_reorder(REGULAR_STRUCTURE, "deductions", REGULAR_DEDUCTIONS)


def _reorder(structure, parentfield, order):
	if not frappe.db.exists("Salary Structure", structure):
		return
	rows = frappe.get_all(
		"Salary Detail",
		filters={"parenttype": "Salary Structure", "parent": structure, "parentfield": parentfield},
		fields=["name", "salary_component", "idx"],
		order_by="idx",
	)

	def sort_key(row):
		# 在名单内的按名单序；不在名单内的保持原相对序、排到名单后面。
		try:
			return (0, order.index(row.salary_component))
		except ValueError:
			return (1, row.idx)

	for new_idx, row in enumerate(sorted(rows, key=sort_key), start=1):
		if row.idx != new_idx:
			frappe.db.set_value("Salary Detail", row.name, "idx", new_idx, update_modified=False)
