# Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and Contributors
# See license.txt

from datetime import datetime
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from fwb_utils.fwb_manufacturing.page.factory_control_towe import factory_control_towe


class TestFactoryControlTower(FrappeTestCase):
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
