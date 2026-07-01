# Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and contributors
# For license information, please see license.txt
"""防漂移测试：生产工位清单散落硬编码在多处，此测试锁定它们一致。

背景：`PRODUCTION_WORKSTATIONS` 常量、扫码 Client Script 的两个 JS 数组
(`prod_stations` / `auto_prod_stations`)、控制塔 `WORKSTATION_FLOW`、两张生产
报表各自硬编码工位清单（设计文档 §4.5 足量提醒、§11.2 核心规则分散）。任何一处
漏改都会静默失配（扫码/报表口径错）。此测试在改动后立即变红，逼迫同步。
"""

import json
import re

import frappe
from frappe.tests.utils import FrappeTestCase

from fwb_utils.fwb_manufacturing.doctype.fwb_work_report.fwb_work_report import (
	PRODUCTION_WORKSTATIONS,
)
from fwb_utils.fwb_manufacturing.page.factory_control_towe.factory_control_towe import (
	WORKSTATION_FLOW,
)


def _read_app_file(*path_parts):
	"""读取 fwb_utils app 下某个源文件的文本内容。"""
	with open(frappe.get_app_path("fwb_utils", *path_parts), encoding="utf-8") as handle:
		return handle.read()


def _extract_js_array(script, var_decl):
	"""从 `<var_decl> = [ "..","..." ];` 中抽出引号内的工位名列表。"""
	match = re.search(re.escape(var_decl) + r"\s*=\s*\[(.*?)\]", script, re.S)
	if not match:
		return None
	return re.findall(r'"([^"]+)"', match.group(1))


class TestWorkstationConstantSync(FrappeTestCase):
	def _load_scan_script(self):
		path = frappe.get_app_path("fwb_utils", "fixtures", "client_script.json")
		with open(path, encoding="utf-8") as handle:
			docs = json.load(handle)
		for doc in docs:
			script = doc.get("script") or ""
			if doc.get("name") == "FWB Work Report" and "prod_stations" in script:
				return script
		self.fail("未在 fixtures/client_script.json 找到 FWB Work Report 扫码脚本")

	def test_scan_arrays_match_constant(self):
		"""扫码 JS 的两个工位数组必须与 PRODUCTION_WORKSTATIONS 完全一致。"""
		script = self._load_scan_script()
		expected = set(PRODUCTION_WORKSTATIONS)
		for var_decl in ("var prod_stations", "const auto_prod_stations"):
			arr = _extract_js_array(script, var_decl)
			self.assertIsNotNone(arr, f"扫码脚本里找不到 {var_decl} 数组")
			self.assertEqual(
				set(arr),
				expected,
				f"{var_decl} 与 PRODUCTION_WORKSTATIONS 漂移："
				f"JS={sorted(arr)} vs 常量={sorted(expected)}",
			)

	def test_control_tower_covers_all_production_workstations(self):
		"""控制塔工位流必须覆盖全部生产工位（控制塔=生产工位 + 打包区）。"""
		flow_names = {ws for ws, _, _ in WORKSTATION_FLOW}
		missing = set(PRODUCTION_WORKSTATIONS) - flow_names
		self.assertFalse(missing, f"控制塔 WORKSTATION_FLOW 缺少生产工位：{missing}")

	def test_control_tower_js_order_matches_flow_panels(self):
		"""控制塔前端 `factory_control_towe.js` 的 order 标签数组必须与 Python
		`WORKSTATION_FLOW` 的进度面板名**同序一致**（新增工位要 py/js 两处同步）。"""
		path = frappe.get_app_path(
			"fwb_utils", "fwb_manufacturing", "page", "factory_control_towe", "factory_control_towe.js"
		)
		with open(path, encoding="utf-8") as handle:
			js = handle.read()
		match = re.search(r"const order = \[(.*?)\]", js, re.S)
		self.assertIsNotNone(match, "factory_control_towe.js 未找到 const order 数组")
		js_order = re.findall(r'"([^"]+)"', match.group(1))
		expected = [panel for _, _, panel in WORKSTATION_FLOW]
		self.assertEqual(
			js_order,
			expected,
			f"控制塔 JS order 与 WORKSTATION_FLOW 面板漂移：JS={js_order} vs FLOW={expected}",
		)

	def test_new_workstations_present_in_reports(self):
		"""两张生产报表必须为新工位输出对应列，锁定本次加法不遗漏报表。"""
		from fwb_utils.fwb_manufacturing.report.process_rate_overview import (
			process_rate_overview as pro,
		)
		from fwb_utils.fwb_manufacturing.report.production_total_verification import (
			production_total_verification as ptv,
		)

		ptv_fields = {col["fieldname"] for col in ptv.get_columns()}
		self.assertIn("mounting_qty", ptv_fields)
		self.assertIn("veneer_qty", ptv_fields)

		pro_fields = {col["fieldname"] for col in pro.get_columns()}
		self.assertIn("mounting_rate", pro_fields)
		self.assertIn("veneer_rate", pro_fields)

	def test_report_sql_maps_new_workstations_to_correct_columns(self):
		"""锁定报表里「工位名 → 列/率字段」映射，防止把裱纸/贴皮映射到错列。
		（端到端数量核对靠只读 smoke + 手工验收；此处静态锁定映射本身。）"""
		ptv_src = _read_app_file(
			"fwb_manufacturing", "report", "production_total_verification", "production_total_verification.py"
		)
		# 期间 CASE 与累计子查询 CASE 都要正确映射
		self.assertRegex(ptv_src, r"workstation = '裱纸区'[^\n]*as mounting_qty\b")
		self.assertRegex(ptv_src, r"workstation = '贴皮区'[^\n]*as veneer_qty\b")
		self.assertRegex(ptv_src, r"workstation = '裱纸区'[^\n]*as mounting_qty_cumulative\b")
		self.assertRegex(ptv_src, r"workstation = '贴皮区'[^\n]*as veneer_qty_cumulative\b")

		pro_src = _read_app_file(
			"fwb_manufacturing", "report", "process_rate_overview", "process_rate_overview.py"
		)
		self.assertRegex(pro_src, r'ws == "裱纸区":\s*\n\s*rates\["mounting_rate"\]')
		self.assertRegex(pro_src, r'ws == "贴皮区":\s*\n\s*rates\["veneer_rate"\]')
