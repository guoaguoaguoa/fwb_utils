# Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and Contributors
# See license.txt
"""有偿返工在所有工位强制说明原因，并把原因传到工资明细。"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from fwb_utils.fwb_manufacturing.doctype.fwb_work_report.fwb_work_report import PRODUCTION_WORKSTATIONS
from fwb_utils.fwb_manufacturing.doctype.employee_wage_sheet.employee_wage_sheet import _collect_aggregated_rows
from fwb_utils.fwb_manufacturing.salary_slip_piece_wage import _append_aggregated_row
from fwb_utils.tests.factories import ensure_test_employee, ensure_test_workstation


class TestPaidReworkRemark(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# 只在测试进程内启用沙箱，不改运行中站点的 common_site_config.json。
		patcher = patch("frappe.utils.safe_exec.is_safe_exec_enabled", return_value=True)
		patcher.start()
		cls.addClassCleanup(patcher.stop)

	def test_all_stations_reject_missing_or_whitespace_remark(self):
		for station in (*PRODUCTION_WORKSTATIONS, "其它工作站", None):
			for wage_type in ("计件", "计时"):
				for remark in (None, "", " \n\t　"):
					with self.subTest(station=station, wage_type=wage_type, remark=remark):
						doc = frappe.get_doc({
							"doctype": "FWB Work Report", "workstation": station,
							"wage_type": wage_type, "rework_type": "有偿返工", "remark": remark,
						})
						with self.assertRaisesRegex(frappe.ValidationError, "有偿返工.*备注"):
							doc.run_method("validate")

	def test_normal_and_unpaid_reports_do_not_require_remark(self):
		for rework_type in ("否", "无偿返工", None):
			with self.subTest(rework_type=rework_type):
				doc = frappe.get_doc({"doctype": "FWB Work Report", "rework_type": rework_type})
				doc.run_method("validate")

	def test_save_rejects_paid_rework_without_remark(self):
		doc = frappe.get_doc({"doctype": "FWB Work Report", "rework_type": "有偿返工"})
		with self.assertRaisesRegex(frappe.ValidationError, "有偿返工.*备注"):
			doc.insert(ignore_permissions=True)

	def test_submit_validation_rejects_cleared_remark(self):
		doc = frappe.get_doc({"doctype": "FWB Work Report", "rework_type": "有偿返工", "remark": "返工原因"})
		doc.insert(ignore_permissions=True)
		doc.remark = "  "
		with self.assertRaisesRegex(frappe.ValidationError, "有偿返工.*备注"):
			doc.submit()

	def test_submitted_history_update_and_cancel_do_not_require_backfill(self):
		for action, status in (("update_after_submit", 1), ("cancel", 2)):
			with self.subTest(action=action):
				doc = frappe.get_doc({
					"doctype": "FWB Work Report", "rework_type": "有偿返工", "docstatus": status,
				})
				doc._action = action
				doc.run_before_save_methods()

	def test_paid_rework_reason_reaches_salary_detail_without_changing_amount(self):
		employee = ensure_test_employee("paid-rework-reason@example.com", employee_name="返工原因回归")
		station = ensure_test_workstation("Test Paid Rework Remark Station")
		reason = "客户调整颜色，重新补喷面漆"
		doc = frappe.get_doc({
			"doctype": "FWB Work Report", "employee": employee.name, "workstation": station.name,
			"wage_type": "计件", "rework_type": "有偿返工", "remark": reason,
			"qty": 20, "valid_qty": 20, "rework_rate": 0.5, "total_amount": 10,
			"created_at": "2026-11-14 10:00:00", "report_date": "2026-11-14",
		}).insert(ignore_permissions=True)
		doc.submit()
		rows = _collect_aggregated_rows(employee.name, "2026-11-01", "2026-11-30")
		row = next(r for r in rows if r.work_report == doc.name)
		self.assertEqual(row.get("remarks"), reason)
		slip = frappe.get_doc({"doctype": "Salary Slip"})
		child = _append_aggregated_row(slip, row)
		self.assertEqual(child.remarks, reason)
		self.assertEqual(child.rate, 0.5)
		self.assertEqual(child.amount, 10)
