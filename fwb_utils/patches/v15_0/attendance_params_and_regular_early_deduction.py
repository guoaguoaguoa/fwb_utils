import frappe
from frappe.utils import cint, flt

from fwb_utils.patches.v15_0.non_worker_fixed_salary_hourly_deductions import _ensure_structure_row

REGULAR_STRUCTURE = "普工结构"
EARLY_DEDUCTION_COMPONENT = "早退扣款"

DEFAULT_PROFILES = (
	{
		"profile_name": "普工",
		"is_regular": 1,
		"work_start": "07:30",
		"lunch_start": "11:30",
		"lunch_end": "12:30",
		"work_end": "17:00",
		"daily_hours": 8.5,
	},
	{
		"profile_name": "综合岗",
		"is_regular": 0,
		"work_start": "08:30",
		"lunch_start": "11:30",
		"lunch_end": "13:00",
		"work_end": "17:30",
		"daily_hours": 7.5,
	},
)


def execute():
	"""薪资考勤参数默认值 + 普工/综合岗排班档案；普工结构补「早退扣款」常驻扣除行。"""
	_seed_attendance_params()
	_ensure_regular_early_deduction_row()


def _seed_attendance_params():
	doc = frappe.get_single("Payroll Attendance Parameter")
	changed = False
	if not flt(doc.meal_unit_price):
		doc.meal_unit_price = 14
		changed = True
	if not cint(doc.non_worker_monthly_rest_days):
		doc.non_worker_monthly_rest_days = 6
		changed = True
	if not cint(doc.deduction_threshold_minutes):
		doc.deduction_threshold_minutes = 30
		changed = True
	if not cint(doc.regular_daily_divisor):
		doc.regular_daily_divisor = 30
		changed = True
	if not doc.get("schedule_profiles"):
		for profile in DEFAULT_PROFILES:
			doc.append("schedule_profiles", dict(profile))
		changed = True
	if changed:
		doc.save(ignore_permissions=True)


def _ensure_regular_early_deduction_row():
	if not frappe.db.exists("Salary Structure", REGULAR_STRUCTURE):
		return
	if not frappe.db.exists("Salary Component", EARLY_DEDUCTION_COMPONENT):
		return
	_ensure_structure_row(REGULAR_STRUCTURE, "deductions", EARLY_DEDUCTION_COMPONENT)
