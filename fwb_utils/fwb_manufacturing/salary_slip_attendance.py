# Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and Contributors
# See license.txt
"""普通保存的普工记薪口径修正，不重新生成任何人工调整的考勤工资项。"""

import frappe
from frappe.utils import flt

from fwb_utils.fwb_manufacturing.dingtalk_attendance import (
	REGULAR_WORKER_STRUCTURE,
	get_attendance_payroll_factors,
)


def sync_regular_worker_payment_days(doc, method=None):
	"""原生 validate 后恢复普工记薪天数，再刷新公式工资和累计金额。

	原生 HRMS 不读取钉钉自定义请假字段，可能把 On Leave/leave_type 为空的
	事假按带薪日处理。本钩子只对齐 payment_days；餐补、加班、迟到/早退、
	社保等金额仍由 HR 手填或重算按钮管理，不能在保存时重新套用。
	"""
	if (
		doc.docstatus == 2
		or doc.salary_structure != REGULAR_WORKER_STRUCTURE
		or not doc.employee
		or not doc.start_date
		or not doc.end_date
		or frappe.db.get_single_value("Payroll Settings", "payroll_based_on") != "Attendance"
	):
		return

	factors = get_attendance_payroll_factors(doc.employee, doc.start_date, doc.end_date)
	if not factors.attendance_count:
		return
	payment_days = flt(factors.salary_days, doc.precision("payment_days"))
	if flt(doc.payment_days) == payment_days:
		return

	doc.payment_days = payment_days
	doc.calculate_net_pay()
	# 原生 validate 已按旧天数算过累计值，必须在更正后同步刷新。
	doc.compute_year_to_date()
	doc.compute_month_to_date()
	doc.compute_component_wise_year_to_date()
