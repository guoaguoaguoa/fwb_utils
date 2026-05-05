# Copyright (c) 2025, WenZhou Furui Handicraft Co.,Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestEmployeeWageSheet(FrappeTestCase):
	"""
	Schema regression: child table 'Employee Wage Sheet Detail' must expose
	'source_work_report' so admins can click through to the originating
	FWB Work Report from a generated wage sheet (Task 3).
	"""

	def test_employee_wage_sheet_detail_has_source_work_report_link(self):
		meta = frappe.get_meta("Employee Wage Sheet Detail")
		field = meta.get_field("source_work_report")
		self.assertIsNotNone(
			field,
			"Employee Wage Sheet Detail must define 'source_work_report' field",
		)
		self.assertEqual(field.fieldtype, "Link")
		self.assertEqual(field.options, "FWB Work Report")
		self.assertEqual(field.read_only, 1)
