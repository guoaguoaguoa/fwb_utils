# Copyright (c) 2025, WenZhou Furui Handicraft Co.,Ltd. and Contributors
# See license.txt

import json
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from fwb_utils.fwb_manufacturing.doctype.fwb_work_report import fwb_work_report
from fwb_utils.fwb_manufacturing.doctype.employee_wage_sheet.employee_wage_sheet import (
	_get_time_rate,
)
from fwb_utils.tests.factories import (
	ensure_test_employee,
	ensure_test_workstation,
	make_fwb_work_report,
	make_rework_record,
)


class TestFWBWorkReport(FrappeTestCase):
	"""
	Minimal regression tests around hourly_rate priority.

	Note: full BOM-based fixture tests require a Work Order + BOM + BOM Operation
	chain which is heavy to set up; here we cover the pure-Python priority helper
	and rely on the integration check in `_get_time_rate` for production behavior.
	"""

	@classmethod
	def setUpClass(cls):
		cls.enable_safe_exec()
		super().setUpClass()

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

	def test_effective_qty_uses_reported_qty_before_qc_exists(self):
		result = fwb_work_report.calculate_effective_qty(
			qty=100,
			defect_qty=8,
			recovered_qty=3,
			total_quality_inspected=0,
		)
		self.assertEqual(flt(result), 95.0)

	def test_effective_qty_uses_quality_inspected_once_qc_exists(self):
		result = fwb_work_report.calculate_effective_qty(
			qty=100,
			defect_qty=8,
			recovered_qty=3,
			total_quality_inspected=80,
		)
		self.assertEqual(flt(result), 75.0)

	def test_work_report_server_script_uses_rework_total_quality_inspected(self):
		fixture_path = (
			Path(__file__).resolve().parents[3]
			/ "fixtures"
			/ "server_script.json"
		)
		scripts = json.loads(fixture_path.read_text())
		script = next(row["script"] for row in scripts if row["name"] == "FWB Work Report（工人报工表）脚本")

		self.assertIn("MAX(IFNULL(total_quality_inspected, 0))", script)
		self.assertNotIn("SUM(IFNULL(quality_inspected, 0))", script)

	def test_rate_backfill_server_script_handles_hourly_rate(self):
		fixture_path = (
			Path(__file__).resolve().parents[3]
			/ "fixtures"
			/ "server_script.json"
		)
		scripts = json.loads(fixture_path.read_text())
		rate_script = next(row["script"] for row in scripts if row["name"] == "Piece Rate to bom")

		self.assertIn("BOM Operation\", bom_op_name, \"hour_rate", rate_script)
		self.assertIn("doc.hourly_rate", rate_script)
		self.assertIn("custom_piece_rate", rate_script)

	def test_bom_hour_rate_cost_fields_allow_submit_edit(self):
		fixture_path = (
			Path(__file__).resolve().parents[3]
			/ "fixtures"
			/ "property_setter.json"
		)
		setters = json.loads(fixture_path.read_text())
		setters_by_name = {row["name"]: row for row in setters}
		expected_setters = {
			"BOM Operation-hour_rate-allow_on_submit",
			"BOM Operation-base_hour_rate-allow_on_submit",
			"BOM Operation-operating_cost-allow_on_submit",
			"BOM Operation-base_operating_cost-allow_on_submit",
			"BOM Operation-cost_per_unit-allow_on_submit",
			"BOM Operation-base_cost_per_unit-allow_on_submit",
			"BOM-operating_cost-allow_on_submit",
			"BOM-base_operating_cost-allow_on_submit",
			"BOM-total_cost-allow_on_submit",
			"BOM-base_total_cost-allow_on_submit",
		}

		for name in expected_setters:
			setter = setters_by_name.get(name)
			self.assertIsNotNone(setter, msg=f"Missing property setter: {name}")
			self.assertEqual(setter["property"], "allow_on_submit")
			self.assertEqual(setter["value"], "1")

	def _sql_effective_qty(self, work_report_name):
		rows = frappe.db.sql(
			f"""
			SELECT {fwb_work_report.effective_qty_sql("wr")}
			FROM `tabFWB Work Report` wr
			WHERE wr.name = %s
			""",
			(work_report_name,),
		)
		return flt(rows[0][0])

	def test_effective_qty_sql_matches_python_when_qc_exists(self):
		"""SQL 口径函数与 Python calculate_effective_qty 在有质检时必须等价
		(复现 WR-20260508-07：报工 540 / 已质检总数 538 → 538)。"""
		employee = ensure_test_employee("eqsql-qc@example.com", employee_name="EQ SQL QC")
		workstation = ensure_test_workstation("Test EQSQL QC Station")

		wr = make_fwb_work_report(
			employee=employee.name,
			workstation=workstation.name,
			qty=540,
			defect_qty=64,
			recovered_qty=64,
			valid_qty=540,
			created_at="2026-05-08 10:00:00",
		)
		wr.submit()

		rr = make_rework_record(
			from_work_report=wr.name,
			employee=employee.name,
			workstation=workstation.name,
			rework_action="次品扣除",
		)
		frappe.db.set_value(
			"Rework Record",
			rr.name,
			{"total_quality_inspected": 538, "docstatus": 1},
			update_modified=False,
		)
		# 模拟历史报工单未回填：valid_qty 仍是陈旧 540
		frappe.db.set_value(
			"FWB Work Report", wr.name, "valid_qty", 540, update_modified=False
		)

		sql_val = self._sql_effective_qty(wr.name)
		py_val = fwb_work_report.calculate_effective_qty(
			qty=540,
			defect_qty=64,
			recovered_qty=64,
			total_quality_inspected=fwb_work_report.get_total_quality_inspected(wr.name),
		)

		self.assertEqual(sql_val, 538.0)
		self.assertEqual(flt(py_val), 538.0)
		self.assertEqual(sql_val, flt(py_val))

	def test_effective_qty_sql_matches_python_without_qc(self):
		"""无质检记录时应回退到报工数：SQL 与 Python 仍须等价。"""
		employee = ensure_test_employee("eqsql-noqc@example.com", employee_name="EQ SQL NoQC")
		workstation = ensure_test_workstation("Test EQSQL NoQC Station")

		wr = make_fwb_work_report(
			employee=employee.name,
			workstation=workstation.name,
			qty=100,
			defect_qty=7,
			recovered_qty=2,
			valid_qty=95,
			created_at="2026-05-09 10:00:00",
		)
		wr.submit()

		sql_val = self._sql_effective_qty(wr.name)
		py_val = fwb_work_report.calculate_effective_qty(
			qty=100,
			defect_qty=7,
			recovered_qty=2,
			total_quality_inspected=fwb_work_report.get_total_quality_inspected(wr.name),
		)

		# 100 - 7 + 2 = 95
		self.assertEqual(sql_val, 95.0)
		self.assertEqual(flt(py_val), 95.0)
		self.assertEqual(sql_val, flt(py_val))

	# ===== 扫码足量提醒（防串单）=====

	def test_is_overproduced_inclusive_threshold(self):
		"""阈值口径：累计有效数量 >= 工单总数即触发（含等于）。"""
		self.assertTrue(fwb_work_report.is_overproduced(100, 100))  # 等于即触发
		self.assertTrue(fwb_work_report.is_overproduced(101, 100))
		self.assertFalse(fwb_work_report.is_overproduced(99, 100))
		# 工单未设数量 (<=0) 一律不触发，避免误弹
		self.assertFalse(fwb_work_report.is_overproduced(50, 0))
		self.assertFalse(fwb_work_report.is_overproduced(0, 0))

	def _make_submitted_report(self, employee, workstation, work_order, **kwargs):
		wr = make_fwb_work_report(employee=employee, workstation=workstation, **kwargs)
		wr.submit()
		# 用合成且唯一的工单号，避免与开发库真实数据串联；提交态下直接写库
		frappe.db.set_value(
			"FWB Work Report", wr.name, "work_order", work_order, update_modified=False
		)
		return wr

	def _patched_work_order(self, qty, item_name="测试产品A"):
		"""只为 Work Order 查询返回合成总数/产品名，其余 get_value 走真实实现。"""
		real_get_value = frappe.db.get_value

		def fake_get_value(doctype, *args, **kwargs):
			if doctype == "Work Order":
				return frappe._dict(qty=qty, item_name=item_name)
			return real_get_value(doctype, *args, **kwargs)

		return patch.object(
			fwb_work_report.frappe.db, "get_value", side_effect=fake_get_value
		)

	def test_production_progress_uses_effective_qty_and_inclusive_flag(self):
		"""累计有效数量 == 工单总数时 exceeded=True（>= 含等于）。"""
		employee = ensure_test_employee("overprod-eq@example.com", employee_name="OverProd EQ")
		ws = ensure_test_workstation("软包区")
		wo = "WO-TEST-OVERPROD-EQ"
		self._make_submitted_report(employee.name, ws.name, wo, qty=60)
		self._make_submitted_report(employee.name, ws.name, wo, qty=40)

		with self._patched_work_order(qty=100):
			res = fwb_work_report.get_production_progress(work_order=wo, workstation=ws.name)

		self.assertEqual(flt(res["reported_qty"]), 100.0)
		self.assertEqual(flt(res["order_qty"]), 100.0)
		self.assertEqual(res["product_name"], "测试产品A")
		self.assertTrue(res["is_production_station"])
		self.assertTrue(res["exceeded"])

	def test_production_progress_subtracts_defects(self):
		"""口径证明：累计用有效结算数量（减次品），不是原始报工数 qty。"""
		employee = ensure_test_employee("overprod-def@example.com", employee_name="OverProd Def")
		ws = ensure_test_workstation("装配区")
		wo = "WO-TEST-OVERPROD-DEF"
		# 原始 qty 60+40=100，但 60 那条扣 10 次品 → 有效 50+40=90 < 100
		self._make_submitted_report(employee.name, ws.name, wo, qty=60, defect_qty=10)
		self._make_submitted_report(employee.name, ws.name, wo, qty=40)

		with self._patched_work_order(qty=100):
			res = fwb_work_report.get_production_progress(work_order=wo, workstation=ws.name)

		self.assertEqual(flt(res["reported_qty"]), 90.0)
		# 若误用原始 qty=100，这里会错判 True
		self.assertFalse(res["exceeded"])

	def test_production_progress_excludes_rework_and_other_station(self):
		"""有偿返工报工、其它工位报工都不计入本工序累计。"""
		employee = ensure_test_employee("overprod-rw@example.com", employee_name="OverProd RW")
		ws = ensure_test_workstation("面漆房")
		other_ws = ensure_test_workstation("抛光区")
		wo = "WO-TEST-OVERPROD-RW"
		# 计入：面漆房 普通报工 80
		self._make_submitted_report(employee.name, ws.name, wo, qty=80)
		# 不计入：有偿返工 50
		self._make_submitted_report(
			employee.name, ws.name, wo,
			qty=50, rework_type="有偿返工", rework_rate=1, custom_piece_rate=0,
		)
		# 不计入：他工位 抛光区 90
		self._make_submitted_report(employee.name, other_ws.name, wo, qty=90)

		with self._patched_work_order(qty=100):
			res = fwb_work_report.get_production_progress(work_order=wo, workstation=ws.name)

		self.assertEqual(flt(res["reported_qty"]), 80.0)
		self.assertFalse(res["exceeded"])

	def test_production_progress_safe_for_non_production_station(self):
		"""非 6 生产工位（如质检区）直接安全返回，不触发提醒。"""
		res = fwb_work_report.get_production_progress(work_order="WO-X", workstation="质检区")
		self.assertFalse(res["is_production_station"])
		self.assertFalse(res["exceeded"])

	def test_production_progress_safe_when_args_missing(self):
		res = fwb_work_report.get_production_progress(work_order=None, workstation=None)
		self.assertFalse(res["exceeded"])
		self.assertEqual(flt(res["reported_qty"]), 0.0)
