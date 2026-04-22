# Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and Contributors
# See license.txt

from datetime import datetime
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from fwb_utils.fwb_manufacturing.page.factory_control_towe import factory_control_towe


class TestFactoryControlTower(FrappeTestCase):
	def test_dashboard_filters_normalize_product_name_and_sample_threshold(self):
		filters = factory_control_towe._get_dashboard_filters("  高光木盒  ", "10")

		self.assertEqual(filters.product_name, "高光木盒")
		self.assertEqual(filters.product_name_like, "%高光木盒%")
		self.assertEqual(filters.sample_qty_threshold, 10)

		empty_filters = factory_control_towe._get_dashboard_filters("", "-5")

		self.assertEqual(empty_filters.product_name, "")
		self.assertIsNone(empty_filters.product_name_like)
		self.assertEqual(empty_filters.sample_qty_threshold, 0)

		invalid_filters = factory_control_towe._get_dashboard_filters("", "abc")

		self.assertEqual(invalid_filters.sample_qty_threshold, 0)

	def test_work_order_filter_sql_skips_sample_filter_when_threshold_is_zero(self):
		filters = factory_control_towe._get_dashboard_filters("", 0)

		condition, params = factory_control_towe._get_work_order_filter_sql(filters, "wo")

		self.assertEqual(condition, "")
		self.assertEqual(params, {})

	def test_work_order_filter_sql_uses_product_and_qty_threshold(self):
		filters = factory_control_towe._get_dashboard_filters("木盒", 10)

		condition, params = factory_control_towe._get_work_order_filter_sql(filters, "wo")
		normalized_condition = " ".join(condition.split()).lower()

		self.assertIn("wo.item_name like %(product_name)s", normalized_condition)
		self.assertIn("ifnull(wo.qty, 0) > %(sample_qty_threshold)s", normalized_condition)
		self.assertEqual(params["product_name"], "%木盒%")
		self.assertEqual(params["sample_qty_threshold"], 10)

	def test_kpi_work_report_queries_only_use_submitted_normal_reports(self):
		captured_sql = []

		def fake_sql(sql, params=None, as_dict=False):
			captured_sql.append(sql)
			normalized = " ".join(sql.split()).lower()
			if "from `tabwork order`" in normalized:
				return [
					frappe._dict(
						total=0,
						completed_count=0,
						pending_qty=0,
						completed_qty=0,
					)
				]
			if "sum(ifnull(total_amount, 0))" in normalized:
				return [frappe._dict(total_amount=0)]
			return [
				frappe._dict(
					total_valid_qty=0,
					total_qty=0,
					total_defect_qty=0,
				)
			]

		with patch.object(factory_control_towe.frappe.db, "sql", side_effect=fake_sql):
			factory_control_towe._get_kpi_block("2026-04-01", "2026-04-30")

		work_report_sql = " ".join(
			sql for sql in captured_sql if "`tabFWB Work Report`" in sql
		)
		normalized_sql = " ".join(work_report_sql.split()).lower()

		self.assertIn("docstatus = 1", normalized_sql)
		self.assertIn("rework_type = '否'", normalized_sql)
		self.assertIn("rework_type is null", normalized_sql)
		self.assertIn("rework_type = ''", normalized_sql)

	def test_kpi_applies_product_and_sample_filters_to_work_order_and_reports(self):
		captured = []

		def fake_sql(sql, params=None, as_dict=False):
			captured.append((sql, params or {}))
			normalized = " ".join(sql.split()).lower()
			if "from `tabwork order`" in normalized:
				return [
					frappe._dict(
						total=0,
						completed_count=0,
						pending_qty=0,
						completed_qty=0,
					)
				]
			if "sum(ifnull(total_amount, 0))" in normalized:
				return [frappe._dict(total_amount=0)]
			return [
				frappe._dict(
					total_valid_qty=0,
					total_qty=0,
					total_defect_qty=0,
				)
			]

		filters = factory_control_towe._get_dashboard_filters("木盒", 10)
		with patch.object(factory_control_towe.frappe.db, "sql", side_effect=fake_sql):
			factory_control_towe._get_kpi_block("2026-04-01", "2026-04-30", filters)

		normalized_sql = " ".join(" ".join(sql for sql, _ in captured).split()).lower()

		self.assertIn("from `tabwork order` wo", normalized_sql)
		self.assertIn("inner join `tabwork order` wo on w.work_order = wo.name", normalized_sql)
		self.assertEqual(captured[0][1]["product_name"], "%木盒%")
		self.assertEqual(captured[0][1]["sample_qty_threshold"], 10)
		for sql, params in captured:
			if "`tabwork order` wo" in sql.lower():
				self.assertIn("product_name", params)
				self.assertIn("sample_qty_threshold", params)

	def test_mrc_and_due_warning_apply_work_order_filters(self):
		captured = []

		def fake_sql(sql, params=None, as_dict=False):
			captured.append((sql, params or {}))
			return []

		filters = factory_control_towe._get_dashboard_filters("木盒", 10)
		with patch.object(factory_control_towe.frappe.db, "sql", side_effect=fake_sql):
			factory_control_towe._get_mrc_progress_list(filters)

		with (
			patch.object(factory_control_towe, "nowdate", return_value="2026-04-22"),
			patch.object(factory_control_towe, "add_days", return_value="2026-04-29"),
			patch.object(factory_control_towe.frappe.db, "sql", side_effect=fake_sql),
		):
			factory_control_towe._get_due_warning_list(filters)

		normalized_sql = " ".join(" ".join(sql for sql, _ in captured).split()).lower()

		self.assertIn("left join `tabwork order` wo on wo.name = m.work_order", normalized_sql)
		self.assertIn("from `tabwork order` wo", normalized_sql)
		self.assertIn("wo.item_name like %(product_name)s", normalized_sql)
		self.assertIn("ifnull(wo.qty, 0) > %(sample_qty_threshold)s", normalized_sql)

	def test_workstation_progress_uses_period_and_cumulative_normal_reports(self):
		captured = {}
		call_count = {"count": 0}

		def fake_sql(sql, params=None, as_dict=False):
			call_count["count"] += 1
			captured.setdefault("sql", []).append(sql)
			if call_count["count"] == 1:
				return [
					frappe._dict(
						work_order="WO-TEST",
						workstation="木工房",
						total_qty=10,
						total_valid_qty=10,
						total_defect_qty=0,
					)
				]
			return []

		with patch.object(factory_control_towe.frappe.db, "sql", side_effect=fake_sql):
			factory_control_towe._get_workstation_progress("2026-04-01", "2026-04-30")

		normalized_sql = " ".join(" ".join(captured["sql"]).split()).lower()

		self.assertIn("w.docstatus = 1", normalized_sql)
		self.assertIn("w_cumulative.docstatus = 1", normalized_sql)
		self.assertIn("w.rework_type = '否'", normalized_sql)
		self.assertIn("w_cumulative.rework_type = '否'", normalized_sql)
		self.assertIn("w.created_at >= %(from_datetime)s", normalized_sql)
		self.assertIn("w.created_at <= %(to_datetime)s", normalized_sql)
		self.assertIn("w_cumulative.created_at <= %(to_datetime)s", normalized_sql)
		self.assertNotIn("w_cumulative.created_at >= %(from_datetime)s", normalized_sql)

	def test_workstation_progress_applies_filters_to_period_work_orders(self):
		captured = {}

		def fake_sql(sql, params=None, as_dict=False):
			captured["sql"] = sql
			captured["params"] = params or {}
			return []

		filters = factory_control_towe._get_dashboard_filters("木盒", 10)
		with patch.object(factory_control_towe.frappe.db, "sql", side_effect=fake_sql):
			factory_control_towe._get_workstation_progress("2026-04-01", "2026-04-30", filters)

		normalized_sql = " ".join(captured["sql"].split()).lower()

		self.assertIn("inner join `tabwork order` wo_filter", normalized_sql)
		self.assertIn("wo_filter.item_name like %(product_name)s", normalized_sql)
		self.assertIn("ifnull(wo_filter.qty, 0) > %(sample_qty_threshold)s", normalized_sql)
		self.assertEqual(captured["params"]["product_name"], "%木盒%")
		self.assertEqual(captured["params"]["sample_qty_threshold"], 10)

	def test_stage_overview_applies_filters_to_period_work_order_selection(self):
		captured = {}

		def fake_sql(sql, params=None, as_dict=False):
			captured["sql"] = sql
			captured["params"] = params or {}
			return []

		filters = factory_control_towe._get_dashboard_filters("木盒", 10)
		with patch.object(factory_control_towe.frappe.db, "sql", side_effect=fake_sql):
			factory_control_towe._get_stage_overview("2026-04-01", "2026-04-30", filters)

		normalized_sql = " ".join(captured["sql"].split()).lower()

		self.assertIn("inner join `tabwork order` wo_filter", normalized_sql)
		self.assertIn("wo_filter.item_name like %(product_name)s", normalized_sql)
		self.assertIn("ifnull(wo_filter.qty, 0) > %(sample_qty_threshold)s", normalized_sql)
		self.assertEqual(captured["params"]["product_name"], "%木盒%")
		self.assertEqual(captured["params"]["sample_qty_threshold"], 10)

	def test_build_stage_overview_calculates_wait_and_partial_flow(self):
		work_orders = {
			"WO-1": frappe._dict(name="WO-1", item_name="Product A", qty=100),
			"WO-2": frappe._dict(name="WO-2", item_name="Product B", qty=100),
		}
		stage_rows = [
			frappe._dict(
				work_order="WO-1",
				workstation="木工房",
				total_valid_qty=100,
				first_created_at=datetime(2026, 4, 1, 10, 0, 0),
				last_created_at=datetime(2026, 4, 1, 10, 0, 0),
			),
			frappe._dict(
				work_order="WO-1",
				workstation="底漆房",
				total_valid_qty=40,
				first_created_at=datetime(2026, 4, 3, 12, 0, 0),
				last_created_at=datetime(2026, 4, 3, 18, 0, 0),
			),
			frappe._dict(
				work_order="WO-2",
				workstation="木工房",
				total_valid_qty=80,
				first_created_at=datetime(2026, 4, 1, 9, 0, 0),
				last_created_at=datetime(2026, 4, 1, 9, 0, 0),
			),
			frappe._dict(
				work_order="WO-2",
				workstation="底漆房",
				total_valid_qty=10,
				first_created_at=datetime(2026, 4, 2, 9, 0, 0),
				last_created_at=datetime(2026, 4, 2, 9, 0, 0),
			),
		]

		result = factory_control_towe._build_stage_overview(
			work_orders,
			stage_rows,
			datetime(2026, 4, 5, 10, 0, 0),
		)
		by_work_order = {row["work_order"]: row for row in result}

		self.assertEqual(by_work_order["WO-1"]["current_stage"], "底漆")
		self.assertEqual(by_work_order["WO-1"]["flow_wait"], "2天2小时")
		self.assertEqual(by_work_order["WO-1"]["overall_tip"], "底漆进行中")
		self.assertEqual(by_work_order["WO-2"]["overall_tip"], "部分流转")
