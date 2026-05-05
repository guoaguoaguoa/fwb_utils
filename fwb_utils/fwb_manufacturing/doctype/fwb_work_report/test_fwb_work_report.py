# Copyright (c) 2025, WenZhou Furui Handicraft Co.,Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from fwb_utils.fwb_manufacturing.doctype.employee_wage_sheet.employee_wage_sheet import (
	_get_time_rate,
)


class TestFWBWorkReport(FrappeTestCase):
	"""
	Minimal regression tests around hourly_rate priority.

	Note: full BOM-based fixture tests require a Work Order + BOM + BOM Operation
	chain which is heavy to set up; here we cover the pure-Python priority helper
	and rely on the integration check in `_get_time_rate` for production behavior.
	"""

	def test_time_rate_falls_back_to_row_when_no_bom(self):
		# bom_no=None forces helper to skip BOM lookup; should fall back to row rate
		rate = _get_time_rate(bom_no=None, workstation="任意", row_hourly_rate=80)
		self.assertEqual(flt(rate), 80.0)

	def test_time_rate_returns_zero_when_no_data_anywhere(self):
		rate = _get_time_rate(bom_no=None, workstation=None, row_hourly_rate=0)
		self.assertEqual(flt(rate), 0.0)

	def test_time_rate_handles_none_row_value(self):
		rate = _get_time_rate(bom_no=None, workstation="X", row_hourly_rate=None)
		self.assertEqual(flt(rate), 0.0)
