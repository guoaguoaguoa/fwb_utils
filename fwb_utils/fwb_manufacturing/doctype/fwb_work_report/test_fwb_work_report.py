# Copyright (c) 2025, WenZhou Furui Handicraft Co.,Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt
from unittest.mock import patch

from fwb_utils.fwb_manufacturing.doctype.fwb_work_report import fwb_work_report
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

	def test_bom_hour_rate_lookup_uses_server_side_ignore_permissions(self):
		with (
			patch.object(
				fwb_work_report.frappe.db,
				"get_value",
				return_value=frappe._dict(bom_no="BOM-001"),
			),
			patch.object(
				fwb_work_report.frappe,
				"get_all",
				return_value=[{"hour_rate": 88}],
			) as mocked_get_all,
		):
			result = fwb_work_report._get_bom_hour_rate_info("WO-001", "装配区")

		self.assertEqual(result["bom_no"], "BOM-001")
		self.assertEqual(flt(result["hour_rate"]), 88.0)
		mocked_get_all.assert_called_once_with(
			"BOM Operation",
			filters={"parent": "BOM-001", "workstation": "装配区"},
			fields=["hour_rate"],
			ignore_permissions=True,
			limit=1,
		)

	def test_bom_hour_rate_lookup_returns_zero_when_input_incomplete(self):
		result = fwb_work_report._get_bom_hour_rate_info(work_order=None, workstation="装配区")
		self.assertEqual(result, {"bom_no": "", "hour_rate": 0.0})
