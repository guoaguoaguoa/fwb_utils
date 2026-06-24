# Copyright (c) 2025, WenZhou Furui Handicraft Co.,Ltd. and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from fwb_utils.fwb_manufacturing.doctype.employee_wage_sheet.employee_wage_sheet import (
	_collect_aggregated_rows,
	_reset_wage_sheets_for_slip,
	generate_wage_details,
	on_salary_slip_unlink,
)
from fwb_utils.fwb_manufacturing.salary_slip_piece_wage import (
	PIECE_WAGE_COMPONENT,
	PIECE_WAGE_DETAIL_FIELD,
	PIECE_WAGE_STRUCTURE,
	generate_piece_wage_details_for_salary_slip,
)
from fwb_utils.tests.factories import (
	ensure_test_employee,
	ensure_test_workstation,
	get_existing_company,
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

	def test_total_duration_seconds_field_on_parent(self):
		"""Schema regression: 总用工时 must live on Employee Wage Sheet itself
		so it can be displayed and reused on payroll docs/reports."""
		meta = frappe.get_meta("Employee Wage Sheet")
		field = meta.get_field("total_duration_seconds")
		self.assertIsNotNone(
			field,
			"Employee Wage Sheet must define 'total_duration_seconds' field",
		)
		self.assertEqual(field.fieldtype, "Duration")
		self.assertEqual(field.read_only, 1)

	def test_validate_recomputes_total_duration_from_manual_rows(self):
		"""手工录入计时明细后保存，total_duration_seconds 必须按当前子表
		即时重算，不依赖『从报工生成明细』按钮。"""
		employee = ensure_test_employee(
			"wage-duration-manual@example.com", employee_name="Wage Duration"
		)

		ws = frappe.get_doc(
			{
				"doctype": "Employee Wage Sheet",
				"employee": employee.name,
				"employee_name": employee.employee_name,
				"from_date": "2026-05-01",
				"to_date": "2026-05-31",
				"details": [
					{
						"product_name": "手工计时-A",
						"qty": 0,
						"rate": 30,
						"duration_seconds": 3600,
						"amount": 30,
					},
					{
						"product_name": "手工计时-B",
						"qty": 0,
						"rate": 30,
						"duration_seconds": 5400,
						"amount": 45,
					},
				],
			}
		).insert(ignore_permissions=True)

		ws.reload()
		self.assertEqual(ws.total_duration_seconds, 9000)

		# Edit one detail's duration and re-save: total must follow immediately.
		ws.details[1].duration_seconds = 1800
		ws.save(ignore_permissions=True)
		ws.reload()
		self.assertEqual(ws.total_duration_seconds, 5400)

		# Adding a brand-new manual row also flows through validate().
		ws.append(
			"details",
			{
				"product_name": "手工计时-C",
				"qty": 0,
				"rate": 30,
				"duration_seconds": 7200,
				"amount": 60,
			},
		)
		ws.save(ignore_permissions=True)
		ws.reload()
		self.assertEqual(ws.total_duration_seconds, 12600)

	def test_generate_wage_details_sets_total_duration_seconds(self):
		"""『从报工生成明细』必须把子表 duration_seconds 汇总到
		parent.total_duration_seconds，并在返回 payload 中带出。"""
		employee = ensure_test_employee(
			"wage-duration-generate@example.com", employee_name="Wage Gen Duration"
		)
		workstation = ensure_test_workstation("Test Wage Duration Station")

		wr_a = make_fwb_work_report(
			employee=employee.name,
			workstation=workstation.name,
			qty=5,
		)
		wr_b = make_fwb_work_report(
			employee=employee.name,
			workstation=workstation.name,
			qty=5,
		)

		ws = frappe.get_doc(
			{
				"doctype": "Employee Wage Sheet",
				"employee": employee.name,
				"employee_name": employee.employee_name,
				"from_date": "2026-04-01",
				"to_date": "2026-04-30",
			}
		).insert(ignore_permissions=True)

		generated_rows = [
			frappe._dict(
				{
					"work_report": wr_a.name,
					"work_order": None,
					"workstation": workstation.name,
					"product_name": "计时-A",
					"size_l": "",
					"size_w": "",
					"size_h": "",
					"total_valid_qty": 0,
					"total_defect_qty": 0,
					"defect_rate": 0,
					"total_duration_seconds": 3600,
					"rate": 30,
				}
			),
			frappe._dict(
				{
					"work_report": wr_b.name,
					"work_order": None,
					"workstation": workstation.name,
					"product_name": "计时-B",
					"size_l": "",
					"size_w": "",
					"size_h": "",
					"total_valid_qty": 0,
					"total_defect_qty": 0,
					"defect_rate": 0,
					"total_duration_seconds": 1800,
					"rate": 30,
				}
			),
		]

		with patch(
			"fwb_utils.fwb_manufacturing.doctype.employee_wage_sheet.employee_wage_sheet._collect_aggregated_rows",
			return_value=generated_rows,
		):
			result = generate_wage_details(ws.name)

		ws.reload()
		self.assertEqual(result["total_duration_seconds"], 5400)
		self.assertEqual(ws.total_duration_seconds, 5400)

	# --- Salary Slip 删除/取消 → 解链复位（保留手工明细）回归 ---

	def _make_wage_sheet_linked_to_slip(self, employee, slip_name, *, submit=True):
		"""造一张带手工明细、并(模拟 make_salary_slip 建链)指向 slip_name 的工资表。"""
		ws = frappe.get_doc(
			{
				"doctype": "Employee Wage Sheet",
				"employee": employee.name,
				"employee_name": employee.employee_name,
				"from_date": "2026-06-01",
				"to_date": "2026-06-30",
				"details": [
					{"product_name": "手工罚款", "qty": 1, "rate": 50, "amount": 50, "is_penalty": 1},
				],
			}
		).insert(ignore_permissions=True)
		if submit:
			ws.submit()
		# 模拟 make_salary_slip_from_wage_sheet 的建链：db_set salary_slip + status
		frappe.db.set_value(
			"Employee Wage Sheet", ws.name, "salary_slip", slip_name, update_modified=False
		)
		frappe.db.set_value(
			"Employee Wage Sheet", ws.name, "status", "已生成工资单", update_modified=False
		)
		ws.reload()
		return ws

	def test_reset_unlinks_and_restores_confirmed_status(self):
		"""删除/取消工资单 → 提交态工资表 salary_slip 清空、状态 已生成工资单→已确认、手工明细保留。"""
		employee = ensure_test_employee(
			"wage-unlink-confirmed@example.com", employee_name="Unlink Confirmed"
		)
		ws = self._make_wage_sheet_linked_to_slip(employee, "FAKE-SLIP-CONFIRMED")
		self.assertEqual(ws.docstatus, 1)
		self.assertEqual(ws.salary_slip, "FAKE-SLIP-CONFIRMED")
		self.assertEqual(ws.status, "已生成工资单")
		detail_count = len(ws.details)

		affected = _reset_wage_sheets_for_slip("FAKE-SLIP-CONFIRMED")
		self.assertIn(ws.name, affected)

		ws.reload()
		self.assertFalse(ws.salary_slip)
		self.assertEqual(ws.status, "已确认")
		self.assertEqual(len(ws.details), detail_count)  # 手工录入明细完整保留
		self.assertEqual(ws.details[0].product_name, "手工罚款")

	def test_reset_draft_wage_sheet_goes_back_to_draft(self):
		"""草稿态工资表复位回「草稿」（防御性分支）。"""
		employee = ensure_test_employee(
			"wage-unlink-draft@example.com", employee_name="Unlink Draft"
		)
		ws = self._make_wage_sheet_linked_to_slip(employee, "FAKE-SLIP-DRAFT", submit=False)
		self.assertEqual(ws.docstatus, 0)

		_reset_wage_sheets_for_slip("FAKE-SLIP-DRAFT")

		ws.reload()
		self.assertFalse(ws.salary_slip)
		self.assertEqual(ws.status, "草稿")

	def test_reset_noop_when_no_linked_wage_sheet(self):
		"""无关联工资表 / 空 slip 名 → 返回空列表、不报错。"""
		self.assertEqual(_reset_wage_sheets_for_slip("NON-EXISTENT-SLIP-XYZ"), [])
		self.assertEqual(_reset_wage_sheets_for_slip(None), [])
		self.assertEqual(_reset_wage_sheets_for_slip(""), [])

	def test_on_salary_slip_unlink_passes_doc_name_to_reset(self):
		"""钩子把 doc.name 传给复位函数（on_trash / on_cancel 共用）。"""
		with patch(
			"fwb_utils.fwb_manufacturing.doctype.employee_wage_sheet.employee_wage_sheet._reset_wage_sheets_for_slip",
			return_value=[],
		) as mock_reset:
			on_salary_slip_unlink(frappe._dict(name="SOME-SLIP"))
		mock_reset.assert_called_once_with("SOME-SLIP")


class TestSalarySlipPieceWage(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		cls.enable_safe_exec()
		super().setUpClass()

	def setUp(self):
		self.company = get_existing_company()
		self.holiday_list = self._ensure_holiday_list()
		self.employee = ensure_test_employee(
			"salary-slip-piece@example.com",
			employee_name="Salary Slip Piece",
			date_of_joining="2026-01-01",
			holiday_list=self.holiday_list,
		)
		frappe.db.delete("Salary Slip", {"employee": self.employee.name})
		frappe.db.delete("Salary Structure Assignment", {"employee": self.employee.name})
		self._ensure_piece_component()

	def _ensure_holiday_list(self):
		name = "测试计件工资单节假日表"
		if frappe.db.exists("Holiday List", name):
			return name
		holiday_list = frappe.get_doc(
			{
				"doctype": "Holiday List",
				"holiday_list_name": name,
				"from_date": "2026-01-01",
				"to_date": "2026-12-31",
				"holidays": [],
			}
		)
		holiday_list.insert(ignore_permissions=True)
		return holiday_list.name

	def _ensure_piece_component(self):
		if frappe.db.exists("Salary Component", PIECE_WAGE_COMPONENT):
			return
		frappe.get_doc(
			{
				"doctype": "Salary Component",
				"salary_component": PIECE_WAGE_COMPONENT,
				"salary_component_abbr": "PWC",
				"type": "Earning",
			}
		).insert(ignore_permissions=True)

	def _ensure_salary_structure_assignment(self, structure):
		self.assertTrue(
			frappe.db.exists("Salary Structure", structure),
			f"Salary Structure {structure} must exist for payroll tests",
		)
		ssa = frappe.get_doc(
			{
				"doctype": "Salary Structure Assignment",
				"employee": self.employee.name,
				"salary_structure": structure,
				"company": self.company,
				"from_date": "2026-01-01",
				"base": 0,
			}
		)
		ssa.insert(ignore_permissions=True)
		ssa.submit()
		return ssa.name

	def _draft_salary_slip(self, structure=PIECE_WAGE_STRUCTURE):
		self._ensure_salary_structure_assignment(structure)
		slip = frappe.get_doc(
			{
				"doctype": "Salary Slip",
				"employee": self.employee.name,
				"company": self.company,
				"posting_date": "2026-04-30",
				"start_date": "2026-04-01",
				"end_date": "2026-04-30",
				"payroll_frequency": "Monthly",
				"salary_structure": structure,
			}
		)
		slip.insert(ignore_permissions=True)
		return slip

	def test_salary_slip_piece_wage_custom_fields_are_available(self):
		meta = frappe.get_meta("Salary Slip")

		self.assertEqual(meta.get_field("custom_piece_wage_total_qty").label, "总有效数量")
		self.assertEqual(meta.get_field("custom_piece_wage_total_duration_seconds").label, "总用工时")
		self.assertEqual(meta.get_field("custom_piece_wage_total_amount").label, "总金额")

		details = meta.get_field(PIECE_WAGE_DETAIL_FIELD)
		self.assertIsNotNone(details)
		self.assertEqual(details.fieldtype, "Table")
		self.assertEqual(details.options, "Employee Wage Sheet Detail")

		legacy = meta.get_field("custom_manufacturing_wage_details")
		self.assertIsNotNone(legacy)
		self.assertEqual(legacy.options, "Manufacturing Wage Detail")

	def test_generate_piece_wage_details_preserves_manual_rows_and_updates_salary_slip(self):
		slip = self._draft_salary_slip()
		workstation = ensure_test_workstation("Test Salary Slip Piece Station")
		report = make_fwb_work_report(
			employee=self.employee.name,
			workstation=workstation.name,
			qty=8,
		)

		slip.append(
			PIECE_WAGE_DETAIL_FIELD,
			{
				"product_name": "手工补贴",
				"qty": 1,
				"rate": 20,
				"amount": 20,
			},
		)
		slip.append(
			PIECE_WAGE_DETAIL_FIELD,
			{
				"source_work_report": report.name,
				"workstation": workstation.name,
				"product_name": "罚款",
				"qty": 2,
				"rate": 5,
				"amount": 10,
				"is_penalty": 1,
				"remarks": "保留罚款金额",
			},
		)
		slip.save(ignore_permissions=True)

		generated_rows = [
			frappe._dict(
				{
					"work_report": report.name,
					"work_order": None,
					"workstation": workstation.name,
					"product_name": "计件报工",
					"size_l": "",
					"size_w": "",
					"size_h": "",
					"total_valid_qty": 8,
					"total_defect_qty": 0,
					"defect_rate": 0,
					"total_duration_seconds": 0,
					"rate": 3,
				}
			),
			frappe._dict(
				{
					"work_report": report.name,
					"work_order": None,
					"workstation": workstation.name,
					"product_name": "罚款",
					"size_l": "",
					"size_w": "",
					"size_h": "",
					"total_valid_qty": 2,
					"total_defect_qty": 0,
					"defect_rate": 0,
					"total_duration_seconds": 0,
					"rate": 0,
					"is_penalty": 1,
				}
			),
		]

		with patch(
			"fwb_utils.fwb_manufacturing.salary_slip_piece_wage._collect_aggregated_rows",
			return_value=generated_rows,
		):
			result = generate_piece_wage_details_for_salary_slip(slip.name)

		slip.reload()
		details = slip.get(PIECE_WAGE_DETAIL_FIELD)
		earnings = {row.salary_component: row for row in slip.earnings}

		self.assertEqual(result["manual_rows"], 1)
		self.assertEqual(result["generated_rows"], 2)
		self.assertEqual(len(details), 3)
		self.assertEqual(details[0].product_name, "手工补贴")
		self.assertFalse(details[0].source_work_report)
		self.assertEqual(details[1].source_work_report, report.name)
		self.assertEqual(details[2].is_penalty, 1)
		self.assertEqual(flt(details[2].rate), 5)
		self.assertEqual(flt(details[2].amount), 10)
		self.assertEqual(details[2].remarks, "保留罚款金额")
		self.assertEqual(flt(slip.custom_piece_wage_total_qty), 11)
		self.assertEqual(flt(slip.custom_piece_wage_total_amount), 34)
		self.assertIn(PIECE_WAGE_COMPONENT, earnings)
		self.assertEqual(flt(earnings[PIECE_WAGE_COMPONENT].amount), 34)
		self.assertEqual(flt(earnings[PIECE_WAGE_COMPONENT].default_amount), 34)
		self.assertEqual(flt(slip.net_pay), 34)
		self.assertFalse(slip.get("custom_manufacturing_wage_details"))

	def test_generate_piece_wage_fills_penalty_remark_from_rework_record(self):
		"""罚款行（来自 Rework Record，is_penalty=1）生成时应把返工单
		「次品情况描述」(remark) 抓进明细备注 (remarks)，方便在工资单直接看
		扣除原因，无需回 Rework Record 按报工单号查。"""
		slip = self._draft_salary_slip()
		workstation = ensure_test_workstation("Test Penalty Remark Station")
		report = make_fwb_work_report(
			employee=self.employee.name,
			workstation=workstation.name,
			qty=10,
			created_at="2026-04-10 10:00:00",
		)
		report.submit()

		rr = make_rework_record(
			from_work_report=report.name,
			employee=self.employee.name,
			workstation=workstation.name,
			is_penalty=1,
			penalty_qty=3,
			remark="掉漆返工，责任工序扣罚",
		)
		# 与现有罚款用例一致：直接置 docstatus=1，跳过提交钩子的报工回写副作用。
		frappe.db.set_value(
			"Rework Record", rr.name, {"docstatus": 1}, update_modified=False
		)

		generate_piece_wage_details_for_salary_slip(slip.name)
		slip.reload()

		penalty_rows = [d for d in slip.get(PIECE_WAGE_DETAIL_FIELD) if d.is_penalty]
		self.assertEqual(len(penalty_rows), 1)
		self.assertEqual(penalty_rows[0].source_work_report, report.name)
		self.assertEqual(penalty_rows[0].remarks, "掉漆返工，责任工序扣罚")

	def test_generate_piece_wage_empty_slip_remark_not_wiped_by_fresh_fetch(self):
		"""空覆盖守卫：工资单上罚款行原备注为空时，重新生成不应把刚从返工单
		抓来的备注用空值冲掉（业主口径：首次填入、之后保留手工改）。"""
		slip = self._draft_salary_slip()
		workstation = ensure_test_workstation("Test Penalty Empty Remark Station")
		report = make_fwb_work_report(
			employee=self.employee.name,
			workstation=workstation.name,
			qty=5,
			created_at="2026-04-12 10:00:00",
		)

		# 预置一条同源罚款行，但备注留空（模拟首次生成时返工单还没写原因）
		slip.append(
			PIECE_WAGE_DETAIL_FIELD,
			{
				"source_work_report": report.name,
				"workstation": workstation.name,
				"product_name": "罚款",
				"qty": 2,
				"rate": 0,
				"amount": 0,
				"is_penalty": 1,
				"remarks": "",
			},
		)
		slip.save(ignore_permissions=True)

		generated_rows = [
			frappe._dict(
				{
					"work_report": report.name,
					"work_order": None,
					"workstation": workstation.name,
					"product_name": "罚款",
					"size_l": "",
					"size_w": "",
					"size_h": "",
					"total_valid_qty": 2,
					"total_defect_qty": 0,
					"defect_rate": 0,
					"total_duration_seconds": 0,
					"rate": 0,
					"remarks": "后补的扣罚原因",
					"is_penalty": 1,
				}
			),
		]

		with patch(
			"fwb_utils.fwb_manufacturing.salary_slip_piece_wage._collect_aggregated_rows",
			return_value=generated_rows,
		):
			generate_piece_wage_details_for_salary_slip(slip.name)

		slip.reload()
		penalty_rows = [d for d in slip.get(PIECE_WAGE_DETAIL_FIELD) if d.is_penalty]
		self.assertEqual(len(penalty_rows), 1)
		self.assertEqual(penalty_rows[0].remarks, "后补的扣罚原因")

	def test_generate_piece_wage_details_rejects_non_piece_structure(self):
		slip = self._draft_salary_slip("普工结构")

		with self.assertRaises(frappe.ValidationError):
			generate_piece_wage_details_for_salary_slip(slip.name)

	def test_generate_piece_wage_details_rejects_submitted_salary_slip(self):
		slip = self._draft_salary_slip()
		frappe.db.set_value("Salary Slip", slip.name, "docstatus", 1, update_modified=False)

		with self.assertRaises(frappe.ValidationError):
			generate_piece_wage_details_for_salary_slip(slip.name)

	def test_salary_slip_validate_syncs_manual_piece_rows(self):
		slip = self._draft_salary_slip()
		slip.append(
			PIECE_WAGE_DETAIL_FIELD,
			{
				"product_name": "手工计时",
				"qty": 1,
				"rate": 30,
				"duration_seconds": 3600,
				"amount": 30,
			},
		)
		slip.append(
			PIECE_WAGE_DETAIL_FIELD,
			{
				"product_name": "手工罚款",
				"qty": 1,
				"rate": 5,
				"amount": 5,
				"is_penalty": 1,
			},
		)
		slip.save(ignore_permissions=True)
		slip.reload()

		earnings = {row.salary_component: row for row in slip.earnings}

		self.assertEqual(flt(slip.custom_piece_wage_total_qty), 2)
		self.assertEqual(slip.custom_piece_wage_total_duration_seconds, 3600)
		self.assertEqual(flt(slip.custom_piece_wage_total_amount), 25)
		self.assertEqual(flt(earnings[PIECE_WAGE_COMPONENT].amount), 25)

	def test_attendance_recalculate_preserves_piece_wage_component(self):
		slip = self._draft_salary_slip()
		slip.append(
			PIECE_WAGE_DETAIL_FIELD,
			{
				"product_name": "手工计件",
				"qty": 10,
				"rate": 4,
				"amount": 40,
			},
		)
		slip.save(ignore_permissions=True)

		from fwb_utils.fwb_manufacturing.dingtalk_attendance_api import recalculate_salary_slip_attendance

		recalculate_salary_slip_attendance(slip.name)
		slip.reload()
		earnings = {row.salary_component: row.amount for row in slip.earnings}

		self.assertEqual(flt(slip.custom_piece_wage_total_amount), 40)
		self.assertEqual(flt(earnings[PIECE_WAGE_COMPONENT]), 40)
