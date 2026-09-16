# Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and Contributors
# See license.txt

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from fwb_utils.fwb_manufacturing import work_order_snapshot as wos


class TestWorkOrderSnapshot(FrappeTestCase):
    """工单日期快照：报工日期/工单日期范围筛选依赖 custom_work_order_date。"""

    def test_creation_date_returns_date_part(self):
        with patch.object(wos.frappe.db, "get_value", return_value="2026-06-15 08:30:00"):
            self.assertEqual(
                wos.get_work_order_creation_date("WO-1"), getdate("2026-06-15")
            )

    def test_creation_date_none_when_no_work_order(self):
        self.assertIsNone(wos.get_work_order_creation_date(""))
        self.assertIsNone(wos.get_work_order_creation_date(None))

    def test_creation_date_none_when_work_order_missing(self):
        with patch.object(wos.frappe.db, "get_value", return_value=None):
            self.assertIsNone(wos.get_work_order_creation_date("WO-missing"))

    def test_set_snapshot_writes_field_when_present(self):
        captured = {}
        doc = MagicMock()
        doc.meta.get_field.return_value = object()  # 字段已存在
        doc.get.return_value = "WO-1"
        doc.set.side_effect = lambda key, value: captured.__setitem__(key, value)

        with patch.object(
            wos, "get_work_order_creation_date", return_value=getdate("2026-06-15")
        ):
            wos.set_work_order_date_snapshot(doc)

        self.assertEqual(captured.get("custom_work_order_date"), getdate("2026-06-15"))

    def test_set_snapshot_noop_when_field_absent(self):
        doc = MagicMock()
        doc.meta.get_field.return_value = None  # 字段尚未 migrate
        wos.set_work_order_date_snapshot(doc)
        doc.set.assert_not_called()

    def test_both_doctypes_have_work_order_date_field(self):
        dt_dir = Path(wos.__file__).resolve().parent / "doctype"
        for folder, filename in (
            ("fwb_work_report", "fwb_work_report.json"),
            ("rework_record", "rework_record.json"),
        ):
            meta = json.loads((dt_dir / folder / filename).read_text(encoding="utf-8"))
            fields = {f["fieldname"]: f for f in meta["fields"]}
            self.assertIn("custom_work_order_date", fields, msg=folder)
            self.assertEqual(fields["custom_work_order_date"]["fieldtype"], "Date", msg=folder)
            self.assertIn("custom_work_order_date", meta["field_order"], msg=folder)

    def test_backfill_patch_registered(self):
        patches_txt = Path(wos.__file__).resolve().parents[1] / "patches.txt"
        text = patches_txt.read_text(encoding="utf-8")
        self.assertIn(
            "fwb_utils.patches.v15_0.backfill_work_order_date_snapshot", text
        )

    def test_list_js_files_present(self):
        dt_dir = Path(wos.__file__).resolve().parent / "doctype"
        self.assertTrue(
            (dt_dir / "fwb_work_report" / "fwb_work_report_list.js").exists()
        )
        self.assertTrue(
            (dt_dir / "rework_record" / "rework_record_list.js").exists()
        )

    # ===== Rework Record 报工日期快照 =====

    def test_work_report_date_returns_date_part(self):
        with patch.object(wos.frappe.db, "get_value", return_value="2026-06-24 09:45:47"):
            self.assertEqual(wos.get_work_report_date("WR-1"), getdate("2026-06-24"))

    def test_work_report_date_none_when_missing(self):
        self.assertIsNone(wos.get_work_report_date(""))
        with patch.object(wos.frappe.db, "get_value", return_value=None):
            self.assertIsNone(wos.get_work_report_date("WR-missing"))

    def test_set_work_report_snapshot_reads_from_work_report(self):
        captured = {}
        doc = MagicMock()
        doc.meta.get_field.return_value = object()
        doc.get.side_effect = lambda key: {"from_work_report": "WR-1"}.get(key)
        doc.set.side_effect = lambda key, value: captured.__setitem__(key, value)

        with patch.object(
            wos, "get_work_report_date", return_value=getdate("2026-06-24")
        ) as mocked:
            wos.set_work_report_date_snapshot(doc)

        # 必须取关联报工单，而不是返工单自身 created_at（那是质检时间）
        mocked.assert_called_once_with("WR-1")
        self.assertEqual(captured.get("custom_work_report_date"), getdate("2026-06-24"))

    def test_rework_record_has_work_report_date_field_and_patch(self):
        dt_dir = Path(wos.__file__).resolve().parent / "doctype"
        meta = json.loads(
            (dt_dir / "rework_record" / "rework_record.json").read_text(encoding="utf-8")
        )
        fields = {f["fieldname"]: f for f in meta["fields"]}
        self.assertEqual(fields["custom_work_report_date"]["fieldtype"], "Date")
        self.assertIn("custom_work_report_date", meta["field_order"])

        patches_txt = Path(wos.__file__).resolve().parents[1] / "patches.txt"
        self.assertIn(
            "fwb_utils.patches.v15_0.backfill_rework_report_date_snapshot",
            patches_txt.read_text(encoding="utf-8"),
        )

    def test_list_js_adds_controls_into_standard_filter_section(self):
        """回归：`page.add_field(df, parent)` 不传 parent 会落到 page_form，与 .standard-filter-section
        成为兄弟节点；该 section 是 flex:1 + .form-group{min-width:150px}，被挤窄后原生标准筛选会竖排
        成一列（2026-09-16 实际排版事故）。两个列表 JS 必须显式把控件放进该 section。"""
        dt_dir = Path(wos.__file__).resolve().parent / "doctype"
        for folder, filename in (
            ("fwb_work_report", "fwb_work_report_list.js"),
            ("rework_record", "rework_record_list.js"),
        ):
            js = (dt_dir / folder / filename).read_text(encoding="utf-8")
            self.assertIn("standard_filters_wrapper", js, msg=filename)
            self.assertIn("standard-filter-section", js, msg=filename)

    def test_no_enabled_list_client_script_overrides_doctype_list_js(self):
        """回归：启用的 List 视图 Client Script 会在 <doctype>_list.js 之后执行，
        整体覆盖 frappe.listview_settings，列表快捷筛选静默消失（2026-09-15 实际发生：
        「FWB Work Report Date」覆盖了 fwb_work_report_list.js）。"""
        fixtures = Path(wos.__file__).resolve().parents[1] / "fixtures" / "client_script.json"
        rows = json.loads(fixtures.read_text(encoding="utf-8"))
        offenders = [
            row["name"]
            for row in rows
            if row.get("dt") in ("FWB Work Report", "Rework Record")
            and row.get("view") == "List"
            and row.get("enabled")
        ]
        self.assertEqual(offenders, [])
