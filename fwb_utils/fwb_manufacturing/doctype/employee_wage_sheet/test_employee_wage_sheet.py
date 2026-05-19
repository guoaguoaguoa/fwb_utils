# Copyright (c) 2025, WenZhou Furui Handicraft Co.,Ltd. and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from fwb_utils.fwb_manufacturing.doctype.employee_wage_sheet.employee_wage_sheet import (
	_collect_aggregated_rows,
	generate_wage_details,
)
from fwb_utils.tests.factories import (
	ensure_test_employee,
	ensure_test_workstation,
	make_fwb_work_report,
	make_rework_record,
)


class TestEmployeeWageSheet(FrappeTestCase):
	"""
	Schema regression: child table 'Employee Wage Sheet Detail' must expose
	'source_work_report' so admins can click through to the originating
	FWB Work Report from a generated wage sheet (Task 3).
	"""

	@classmethod
	def setUpClass(cls):
		cls.enable_safe_exec()
		super().setUpClass()

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

	def test_generate_wage_details_preserves_manual_rows_at_top(self):
		employee = ensure_test_employee("wage-manual-row@example.com", employee_name="Wage Manual")
		workstation = ensure_test_workstation("Test Wage Manual Station")

		existing_report = make_fwb_work_report(
			employee=employee.name,
			workstation=workstation.name,
			qty=10,
		)
		new_report = make_fwb_work_report(
			employee=employee.name,
			workstation=workstation.name,
			qty=8,
		)

		ws = frappe.get_doc(
			{
				"doctype": "Employee Wage Sheet",
				"employee": employee.name,
				"employee_name": employee.employee_name,
				"from_date": "2026-04-01",
				"to_date": "2026-04-30",
				"details": [
					{
						"product_name": "手工补贴",
						"qty": 1,
						"rate": 20,
						"amount": 20,
					},
				],
			}
		).insert(ignore_permissions=True)

		generated_rows = [
			frappe._dict(
				{
					"work_report": existing_report.name,
					"work_order": None,
					"workstation": workstation.name,
					"product_name": "已有报工新数据",
					"size_l": "",
					"size_w": "",
					"size_h": "",
					"total_valid_qty": 10,
					"total_defect_qty": 0,
					"defect_rate": 0,
					"total_duration_seconds": 0,
					"rate": 1,
				}
			),
			frappe._dict(
				{
					"work_report": new_report.name,
					"work_order": None,
					"workstation": workstation.name,
					"product_name": "新报工",
					"size_l": "",
					"size_w": "",
					"size_h": "",
					"total_valid_qty": 8,
					"total_defect_qty": 0,
					"defect_rate": 0,
					"total_duration_seconds": 0,
					"rate": 2,
				}
			),
		]

		with patch(
			"fwb_utils.fwb_manufacturing.doctype.employee_wage_sheet.employee_wage_sheet._collect_aggregated_rows",
			return_value=generated_rows,
		):
			result = generate_wage_details(ws.name)

		ws.reload()

		self.assertEqual(result["manual_rows"], 1)
		self.assertEqual(result["generated_rows"], 2)
		self.assertEqual(len(ws.details), 3)
		self.assertEqual(ws.details[0].product_name, "手工补贴")
		self.assertEqual(ws.details[1].source_work_report, existing_report.name)
		self.assertEqual(ws.details[2].source_work_report, new_report.name)

	def test_generate_uses_inspected_total_not_stale_valid_qty(self):
		"""生成明细时按 Rework Record.total_quality_inspected 重算 valid_qty，
		忽略 FWB Work Report 上可能陈旧的 valid_qty（历史数据未回填场景，
		复现 WR-20260508-07：报工 540 / 已质检总数 538 → 应结算 538）。"""
		employee = ensure_test_employee("wage-tqi@example.com", employee_name="QC Base")
		workstation = ensure_test_workstation("Test Wage TQI Station")

		wr = make_fwb_work_report(
			employee=employee.name,
			workstation=workstation.name,
			qty=540,
			defect_qty=64,
			recovered_qty=64,
			valid_qty=540,
			custom_piece_rate=1,
			created_at="2026-05-08 10:00:00",
		)
		wr.submit()

		rr = make_rework_record(
			from_work_report=wr.name,
			employee=employee.name,
			workstation=workstation.name,
			rework_action="次品扣除",
			defective_qty=0,
			reworked_qty=0,
		)
		# 模拟历史质检单：强制已质检总数 538、置为已提交
		frappe.db.set_value(
			"Rework Record",
			rr.name,
			{"total_quality_inspected": 538, "docstatus": 1},
			update_modified=False,
		)
		# 模拟“历史报工单未回填”：把 valid_qty 强行还原成陈旧的 540
		frappe.db.set_value(
			"FWB Work Report", wr.name, "valid_qty", 540, update_modified=False
		)

		rows = _collect_aggregated_rows(employee.name, "2026-05-01", "2026-05-31")
		target = [r for r in rows if r.get("work_report") == wr.name]

		self.assertEqual(len(target), 1)
		# 538 - 64 + 64 = 538，而不是陈旧的 540
		self.assertEqual(flt(target[0]["total_valid_qty"]), 538.0)

	def test_stale_zero_valid_qty_not_dropped_when_effective_positive(self):
		"""回归：纳入筛选必须用重算口径。

		历史/损坏单存量 valid_qty 错成 0，但按已质检总数应 > 0 时，
		不能被 _collect_aggregated_rows 的 WHERE 静默排除（否则工人少结算）。"""
		employee = ensure_test_employee(
			"wage-stale0@example.com", employee_name="Stale Zero"
		)
		workstation = ensure_test_workstation("Test Wage Stale0 Station")

		wr = make_fwb_work_report(
			employee=employee.name,
			workstation=workstation.name,
			qty=200,
			defect_qty=0,
			recovered_qty=0,
			valid_qty=200,
			custom_piece_rate=1,
			created_at="2026-05-10 10:00:00",
		)
		wr.submit()

		rr = make_rework_record(
			from_work_report=wr.name,
			employee=employee.name,
			workstation=workstation.name,
			rework_action="次品扣除",
			defective_qty=0,
			reworked_qty=0,
		)
		# 已质检总数 200、已提交
		frappe.db.set_value(
			"Rework Record",
			rr.name,
			{"total_quality_inspected": 200, "docstatus": 1},
			update_modified=False,
		)
		# 关键：把存量 valid_qty 强行损坏成 0（模拟历史/异常单）
		frappe.db.set_value(
			"FWB Work Report", wr.name, "valid_qty", 0, update_modified=False
		)

		rows = _collect_aggregated_rows(employee.name, "2026-05-01", "2026-05-31")
		target = [r for r in rows if r.get("work_report") == wr.name]

		# 存量 valid_qty=0 但有效结算数量=200 > 0，必须被纳入
		self.assertEqual(
			len(target), 1, "stale valid_qty=0 row was silently dropped by WHERE filter"
		)
		self.assertEqual(flt(target[0]["total_valid_qty"]), 200.0)

	def test_stale_zero_valid_qty_dropped_when_effective_zero(self):
		"""对照：存量 0 且有效结算数量也 = 0（纯计件、无质检、无产量）时
		仍应被排除，避免凭空多出 0 行。"""
		employee = ensure_test_employee(
			"wage-zero@example.com", employee_name="True Zero"
		)
		workstation = ensure_test_workstation("Test Wage TrueZero Station")

		wr = make_fwb_work_report(
			employee=employee.name,
			workstation=workstation.name,
			qty=0,
			defect_qty=0,
			recovered_qty=0,
			valid_qty=0,
			custom_piece_rate=1,
			created_at="2026-05-11 10:00:00",
		)
		wr.submit()
		frappe.db.set_value(
			"FWB Work Report", wr.name, "valid_qty", 0, update_modified=False
		)

		rows = _collect_aggregated_rows(employee.name, "2026-05-01", "2026-05-31")
		target = [r for r in rows if r.get("work_report") == wr.name]

		self.assertEqual(len(target), 0)
