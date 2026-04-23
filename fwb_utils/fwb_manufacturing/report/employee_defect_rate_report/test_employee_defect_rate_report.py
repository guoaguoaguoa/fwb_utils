# Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and Contributors
# See license.txt

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from fwb_utils.fwb_manufacturing.report.employee_defect_rate_report import (
	employee_defect_rate_report,
)


class TestEmployeeDefectRateReport(FrappeTestCase):
	def test_product_name_filter_uses_fuzzy_match(self):
		captured = {}

		def fake_sql(sql, params=None, as_dict=False):
			captured["sql"] = sql
			captured["params"] = params or {}
			return []

		with patch.object(employee_defect_rate_report.frappe.db, "sql", side_effect=fake_sql):
			employee_defect_rate_report.get_data({"product_name": "  木盒  "})

		normalized_sql = " ".join(captured["sql"].split()).lower()

		self.assertIn("like %(product_name)s", normalized_sql)
		self.assertNotIn("wo.bom_no = %(finished_bom)s", normalized_sql)
		self.assertEqual(captured["params"]["product_name"], "%木盒%")

	def test_report_json_uses_product_name_data_filter(self):
		report_json = Path(__file__).with_name("employee_defect_rate_report.json")
		report = json.loads(report_json.read_text(encoding="utf-8"))
		filters = {row["fieldname"]: row for row in report["filters"]}

		self.assertIn("product_name", filters)
		self.assertNotIn("finished_bom", filters)
		self.assertEqual(filters["product_name"]["label"], "产品名")
		self.assertEqual(filters["product_name"]["fieldtype"], "Data")
