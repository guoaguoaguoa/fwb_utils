# Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and Contributors
# See license.txt

from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from fwb_utils.fwb_manufacturing.report.production_total_verification import (
	production_total_verification,
)


class TestProductionTotalVerification(FrappeTestCase):
	def test_order_qty_column_is_between_product_and_woodworking_columns(self):
		fieldnames = [column["fieldname"] for column in production_total_verification.get_columns()]

		self.assertLess(fieldnames.index("product_name"), fieldnames.index("order_qty"))
		self.assertLess(fieldnames.index("order_qty"), fieldnames.index("woodworking_qty"))

	def test_get_data_selects_work_order_qty(self):
		captured = {}

		def fake_sql(sql, filters, as_dict=False):
			captured["sql"] = sql
			captured["filters"] = filters
			captured["as_dict"] = as_dict
			return [{"work_order": "WO-TEST", "order_qty": 120}]

		with patch.object(production_total_verification.frappe.db, "sql", side_effect=fake_sql):
			data = production_total_verification.get_data({})

		normalized_sql = " ".join(captured["sql"].split()).lower()
		self.assertIn("wo.qty as order_qty", normalized_sql)
		self.assertTrue(captured["as_dict"])
		self.assertEqual(data[0]["order_qty"], 120)
