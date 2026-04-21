# Copyright (c) 2025, WenZhou Furui Handicraft Co.,Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from fwb_utils.fwb_manufacturing.doctype.rework_record.rework_record import (
	apply_submitted_rework_record,
	get_rework_history_summary,
	rollback_cancelled_rework_record,
)
from fwb_utils.tests.factories import (
	ensure_test_employee,
	ensure_test_workstation,
	make_fwb_work_report,
	make_rework_record,
)


class TestReworkRecord(FrappeTestCase):
	def setUp(self):
		self.workstation = ensure_test_workstation("_Test Rework Workstation").name
		self.production_employee = ensure_test_employee(
			"rework-production@example.com",
			employee_name="生产员工A",
		).name
		self.inspector = ensure_test_employee(
			"rework-inspector@example.com",
			employee_name="质检员A",
		).name

	def _set_rework_docstatus(self, doc, docstatus, modified="2026-03-01 08:00:00"):
		frappe.db.sql(
			"""
			UPDATE `tabRework Record`
			SET docstatus = %s, modified = %s
			WHERE name = %s
			""",
			(docstatus, modified, doc.name),
		)
		doc.reload()

	def _assert_numeric_equal(self, actual, expected):
		self.assertEqual(flt(actual), flt(expected))

	def test_get_rework_history_summary_returns_empty_for_no_history(self):
		report = make_fwb_work_report(
			employee=self.production_employee,
			workstation=self.workstation,
			qty=120,
			custom_piece_rate=2,
		)

		summary = get_rework_history_summary(report.name)

		self.assertEqual(summary["history_count"], 0)
		self.assertEqual(summary["total_defective_qty"], 0)
		self.assertEqual(summary["total_reworked_qty"], 0)
		self.assertEqual(summary["records"], [])

	def test_get_rework_history_summary_ignores_draft_and_cancelled(self):
		report = make_fwb_work_report(
			employee=self.production_employee,
			workstation=self.workstation,
			qty=100,
			custom_piece_rate=1.5,
		)

		submitted = make_rework_record(
			from_work_report=report.name,
			inspector=self.inspector,
			quality_inspected=20,
			defective_qty=5,
			rework_action="次品扣除",
		)
		draft = make_rework_record(
			from_work_report=report.name,
			inspector=self.inspector,
			quality_inspected=8,
			defective_qty=2,
			rework_action="次品扣除",
		)
		cancelled = make_rework_record(
			from_work_report=report.name,
			inspector=self.inspector,
			quality_inspected=6,
			reworked_qty=3,
			rework_action="良品回补",
			is_penalty=1,
			penalty_qty=1,
		)

		self._set_rework_docstatus(submitted, 1, "2026-03-01 09:00:00")
		self._set_rework_docstatus(draft, 0, "2026-03-01 10:00:00")
		self._set_rework_docstatus(cancelled, 2, "2026-03-01 11:00:00")

		summary = get_rework_history_summary(report.name)

		self.assertEqual(summary["history_count"], 1)
		self.assertEqual(summary["total_defective_qty"], 5.0)
		self.assertEqual(summary["total_reworked_qty"], 0.0)
		self.assertEqual(len(summary["records"]), 1)
		self.assertEqual(summary["records"][0]["name"], submitted.name)
		self.assertEqual(summary["records"][0]["inspector_name"], "质检员A")
		self.assertEqual(summary["records"][0]["penalty_qty"], 0.0)

	def test_apply_submitted_rework_record_updates_piece_report(self):
		report = make_fwb_work_report(
			employee=self.production_employee,
			workstation=self.workstation,
			qty=100,
			custom_piece_rate=2,
		)
		record = make_rework_record(
			from_work_report=report.name,
			inspector=self.inspector,
			quality_inspected=12,
			defective_qty=8,
			rework_action="次品扣除",
		)
		self._set_rework_docstatus(record, 1, "2026-03-01 09:30:00")

		apply_submitted_rework_record(record.name)

		report.reload()
		record.reload()

		self._assert_numeric_equal(report.defect_qty, 8)
		self._assert_numeric_equal(report.recovered_qty, 0)
		self._assert_numeric_equal(report.valid_qty, 92)
		self._assert_numeric_equal(report.total_amount, 184)
		self._assert_numeric_equal(record.total_quality_inspected, 12)

	def test_apply_submitted_rework_record_keeps_paid_rework_amount_rule(self):
		report = make_fwb_work_report(
			employee=self.production_employee,
			workstation=self.workstation,
			qty=100,
			custom_piece_rate=3,
			rework_type="有偿返工",
			rework_rate=0.8,
		)
		record = make_rework_record(
			from_work_report=report.name,
			inspector=self.inspector,
			quality_inspected=10,
			defective_qty=5,
			rework_action="次品扣除",
		)
		self._set_rework_docstatus(record, 1, "2026-03-01 10:00:00")

		apply_submitted_rework_record(record.name)

		report.reload()

		self._assert_numeric_equal(report.valid_qty, 95)
		self._assert_numeric_equal(report.total_amount, 76)

	def test_rollback_cancelled_rework_record_restores_report_and_history(self):
		report = make_fwb_work_report(
			employee=self.production_employee,
			workstation=self.workstation,
			qty=100,
			custom_piece_rate=2,
		)
		first = make_rework_record(
			from_work_report=report.name,
			inspector=self.inspector,
			quality_inspected=12,
			defective_qty=5,
			rework_action="次品扣除",
		)
		second = make_rework_record(
			from_work_report=report.name,
			inspector=self.inspector,
			quality_inspected=9,
			defective_qty=3,
			rework_action="次品扣除",
			is_penalty=1,
			penalty_qty=2,
		)
		self._set_rework_docstatus(first, 1, "2026-03-01 09:00:00")
		self._set_rework_docstatus(second, 1, "2026-03-01 10:00:00")

		apply_submitted_rework_record(first.name)
		apply_submitted_rework_record(second.name)

		report.reload()
		self._assert_numeric_equal(report.defect_qty, 8)
		self._assert_numeric_equal(report.valid_qty, 92)
		self._assert_numeric_equal(report.total_amount, 184)

		rollback_cancelled_rework_record(second.name)
		self._set_rework_docstatus(second, 2, "2026-03-01 11:00:00")

		report.reload()
		first.reload()

		self._assert_numeric_equal(report.defect_qty, 5)
		self._assert_numeric_equal(report.valid_qty, 95)
		self._assert_numeric_equal(report.total_amount, 190)
		self._assert_numeric_equal(first.total_quality_inspected, 12)

		summary = get_rework_history_summary(report.name)
		self.assertEqual(summary["history_count"], 1)
		self.assertEqual(summary["total_defective_qty"], 5.0)
		self.assertEqual(summary["records"][0]["name"], first.name)
