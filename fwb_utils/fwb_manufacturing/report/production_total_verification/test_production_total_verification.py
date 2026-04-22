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

	def test_get_data_marks_date_filter_state(self):
		def fake_sql(sql, filters, as_dict=False):
			return [{"work_order": "WO-TEST"}]

		with patch.object(production_total_verification.frappe.db, "sql", side_effect=fake_sql):
			without_dates = production_total_verification.get_data({})
			with_dates = production_total_verification.get_data({"to_date": "2026-04-30"})

		self.assertEqual(without_dates[0]["date_filter_active"], 0)
		self.assertEqual(with_dates[0]["date_filter_active"], 1)

	def test_get_data_selects_cumulative_workstation_fields(self):
		captured = {}

		def fake_sql(sql, filters, as_dict=False):
			captured["sql"] = sql
			return []

		with patch.object(production_total_verification.frappe.db, "sql", side_effect=fake_sql):
			production_total_verification.get_data({})

		normalized_sql = " ".join(captured["sql"].split()).lower()
		expected_fields = [
			"woodworking_qty_cumulative",
			"primer_qty_cumulative",
			"top_coat_qty_cumulative",
			"assembly_qty_cumulative",
			"polishing_qty_cumulative",
			"lining_qty_cumulative",
		]

		for fieldname in expected_fields:
			self.assertIn(fieldname, normalized_sql)

	def test_cumulative_conditions_ignore_from_date_and_respect_to_date(self):
		filters = {
			"from_date": "2026-04-01",
			"to_date": "2026-04-30",
		}

		production_total_verification.get_conditions(filters)
		cumulative_conditions = production_total_verification.get_cumulative_conditions(filters)

		self.assertNotIn("from_date", cumulative_conditions)
		self.assertIn("wr_cumulative.created_at <= %(to_date)s", cumulative_conditions)
		self.assertEqual(filters["to_date"], "2026-04-30 23:59:59")

	def test_work_order_filter_is_text_fuzzy_and_normalizes_common_w0_typo(self):
		filters = {"work_order": " W0-260315-02 "}

		conditions = production_total_verification.get_conditions(filters)

		self.assertIn("wr.work_order LIKE %(work_order)s", conditions)
		self.assertEqual(filters["work_order"], "%WO-260315-02%")

	def test_cumulative_subquery_excludes_cancelled_and_rework_reports(self):
		captured = {}

		def fake_sql(sql, filters, as_dict=False):
			captured["sql"] = sql
			return []

		with patch.object(production_total_verification.frappe.db, "sql", side_effect=fake_sql):
			production_total_verification.get_data({})

		normalized_sql = " ".join(captured["sql"].split()).lower()
		cumulative_sql = normalized_sql.split("`tabfwb work report` wr_cumulative", 1)[1]
		cumulative_sql = cumulative_sql.split("group by wr_cumulative.work_order", 1)[0]

		self.assertIn("wr_cumulative.docstatus < 2", cumulative_sql)
		self.assertIn("wr_cumulative.rework_type = '否'", cumulative_sql)
		self.assertIn("wr_cumulative.rework_type is null", cumulative_sql)
		self.assertIn("wr_cumulative.rework_type = ''", cumulative_sql)
