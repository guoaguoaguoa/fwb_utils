# Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and Contributors
# See license.txt
"""普通保存必须沿用普工自定义记薪口径，并保留人工扣款调整。"""

from unittest import TestCase
from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from fwb_utils.tests.factories import ensure_test_employee, get_existing_company


class TestSalarySlipPaymentDays(FrappeTestCase):
	def setUp(self):
		self.company = get_existing_company()
		holiday_list = "FWB Regular Save Regression 2026"
		if not frappe.db.exists("Holiday List", holiday_list):
			frappe.get_doc({
				"doctype": "Holiday List", "holiday_list_name": holiday_list,
				"from_date": "2026-01-01", "to_date": "2026-12-31",
				"holidays": [{"holiday_date": "2026-10-01", "description": "国庆"}],
			}).insert(ignore_permissions=True)
		self.employee = ensure_test_employee(
			"fwb-regular-save-regression@example.com", employee_name="普工保存回归员工",
			date_of_joining="2026-01-01", holiday_list=holiday_list,
		)
		for doctype in ("Attendance", "Salary Slip", "Salary Structure Assignment"):
			frappe.db.delete(doctype, {"employee": self.employee.name})
		frappe.get_doc({
			"doctype": "Salary Structure Assignment", "employee": self.employee.name,
			"company": self.company, "salary_structure": "普工结构", "from_date": "2026-01-01",
			"base": 4500, "custom_seniority_base": 500, "custom_grade_base": 2000,
		}).insert(ignore_permissions=True).submit()

	def _make_slip(self, unpaid_leave=True):
		for day in range(1, 32):
			status = "Absent" if day in (1, 2) else "Present"
			if unpaid_leave and day == 12:
				status = "On Leave"
			attendance = frappe.get_doc({
				"doctype": "Attendance", "employee": self.employee.name, "company": self.company,
				"attendance_date": f"2026-10-{day:02d}", "status": status,
				"custom_actual_attendance_days": int(status == "Present"),
				"custom_dingtalk_unpaid_leave_days": int(status == "On Leave"),
				"custom_dingtalk_leave_name": "事假" if status == "On Leave" else "",
			})
			attendance.flags.ignore_validate = True
			attendance.insert(ignore_permissions=True).submit()
		slip = frappe.get_doc({
			"doctype": "Salary Slip", "employee": self.employee.name, "company": self.company,
			"salary_structure": "普工结构", "payroll_frequency": "Monthly",
			"start_date": "2026-10-01", "end_date": "2026-10-31", "posting_date": "2026-10-31",
		}).insert(ignore_permissions=True)
		# 模拟重算按钮保存的正确快照，避免新建时的行为掩盖保存回归。
		slip.payment_days = 29 if unpaid_leave else 30
		slip.set_salary_structure_assignment()
		slip.calculate_net_pay()
		for row in slip.earnings:
			if row.salary_component == "加班":
				row.amount = row.default_amount = 1283.33
		for row in slip.deductions:
			if row.salary_component == "早退扣款":
				row.amount = row.default_amount = 123.53
		slip.set_totals()
		slip.flags.ignore_validate = True
		slip.save(ignore_permissions=True)
		slip.flags.ignore_validate = False
		return slip

	def test_save_preserves_unpaid_leave_days_and_waived_deduction(self):
		slip = self._make_slip()
		for row in slip.deductions:
			if row.salary_component == "早退扣款":
				row.amount = 0
		for _ in range(2):
			slip.save(ignore_permissions=True)
			slip.reload()
			self.assertEqual(slip.payment_days, 29)
			self.assertEqual(slip.gross_pay, 8049.99)
			self.assertEqual(slip.total_deduction, 0)
			self.assertEqual(slip.net_pay, 8049.99)
			self.assertEqual(slip.gross_year_to_date, 8049.99)
			self.assertEqual(slip.year_to_date, 8049.99)
			self.assertEqual(slip.month_to_date, 8049.99)
			self.assertEqual(
				{r.salary_component: r.amount for r in slip.earnings},
				{"底薪": 4350, "工龄补贴": 483.33, "等级工资": 1933.33, "加班": 1283.33, "其他": 0},
			)
			self.assertIn("捌仟零肆拾玖元玖角玖分", slip.total_in_words)
			for row in slip.earnings + slip.deductions:
				self.assertEqual(row.year_to_date, row.amount)

	def test_submit_validation_uses_same_days_without_restoring_waived_deduction(self):
		slip = self._make_slip()
		for row in slip.deductions:
			if row.salary_component == "早退扣款":
				row.amount = 0
		# 运行真正提交路径的保存前校验，但不创建付款/会计等提交副作用。
		slip._action = "submit"
		slip.docstatus = 1
		slip.run_before_save_methods()
		self.assertEqual(slip.payment_days, 29)
		self.assertEqual(slip.gross_pay, 8049.99)
		self.assertEqual(slip.total_deduction, 0)
		self.assertEqual(slip.net_pay, 8049.99)

	def test_save_without_edits_preserves_original_net(self):
		slip = self._make_slip()
		slip.save(ignore_permissions=True)
		slip.reload()
		self.assertEqual(slip.payment_days, 29)
		self.assertEqual(slip.gross_pay, 8049.99)
		self.assertEqual(slip.net_pay, 7926.46)

	def test_save_after_removing_deduction_row(self):
		slip = self._make_slip()
		slip.set("deductions", [r for r in slip.deductions if r.salary_component != "早退扣款"])
		slip.save(ignore_permissions=True)
		slip.reload()
		self.assertEqual(slip.payment_days, 29)
		self.assertEqual(slip.gross_pay, 8049.99)
		self.assertEqual(slip.net_pay, 8049.99)

	def test_worker_without_unpaid_leave_stays_at_full_fixed_salary(self):
		slip = self._make_slip(unpaid_leave=False)
		slip.save(ignore_permissions=True)
		slip.reload()
		self.assertEqual(slip.payment_days, 30)
		self.assertEqual(slip.gross_pay, 8283.33)
		self.assertEqual(slip.net_pay, 8159.80)


class TestPaymentDaysScope(TestCase):
	def _doc(self, **values):
		doc = Mock(
			docstatus=0, salary_structure="普工结构", employee="test-employee",
			start_date="2026-10-01", end_date="2026-10-31", payment_days=30,
		)
		doc.precision.return_value = 2
		for key, value in values.items():
			setattr(doc, key, value)
		return doc

	def test_scope_and_empty_attendance_keep_native_behavior(self):
		from fwb_utils.fwb_manufacturing import salary_slip_attendance as module

		for values in (
			{"docstatus": 2}, {"salary_structure": "无底薪计件工结构"},
			{"salary_structure": "内贸业务员结构"}, {"salary_structure": "董事结构"},
			{"employee": None}, {"start_date": None}, {"end_date": None},
		):
			with self.subTest(values=values), patch.object(module, "get_attendance_payroll_factors") as factors:
				doc = self._doc(**values)
				module.sync_regular_worker_payment_days(doc)
				factors.assert_not_called()
				doc.calculate_net_pay.assert_not_called()
		with patch.object(frappe.db, "get_single_value", return_value="Leave Application"):
			doc = self._doc()
			module.sync_regular_worker_payment_days(doc)
			doc.calculate_net_pay.assert_not_called()
		with patch.object(frappe.db, "get_single_value", return_value="Attendance"), patch.object(
			module, "get_attendance_payroll_factors", return_value=frappe._dict(attendance_count=0),
		):
			doc = self._doc()
			module.sync_regular_worker_payment_days(doc)
			self.assertEqual(doc.payment_days, 30)
			doc.calculate_net_pay.assert_not_called()

	def test_zero_fractional_and_unchanged_days(self):
		from fwb_utils.fwb_manufacturing import salary_slip_attendance as module

		for salary_days in (0, 28.5, 30):
			with self.subTest(salary_days=salary_days), patch.object(
				frappe.db, "get_single_value", return_value="Attendance",
			), patch.object(module, "get_attendance_payroll_factors", return_value=frappe._dict(
				attendance_count=31, salary_days=salary_days,
			)):
				doc = self._doc()
				module.sync_regular_worker_payment_days(doc)
				self.assertEqual(doc.payment_days, salary_days)
				if salary_days == 30:
					doc.calculate_net_pay.assert_not_called()
				else:
					doc.calculate_net_pay.assert_called_once_with()
					doc.compute_year_to_date.assert_called_once_with()
					doc.compute_month_to_date.assert_called_once_with()
					doc.compute_component_wise_year_to_date.assert_called_once_with()
