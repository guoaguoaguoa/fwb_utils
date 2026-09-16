# Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and Contributors
# See license.txt
"""中文错译覆盖回归。

Frappe 自带 `frappe/locale/zh.po` 把 `pretty_date.js` 的 `"{0} M"`（M = month）
误译成「{0}兆」（把 M 当成 Mega），导致列表「最后修改时间」列把 1 个月显示成「1兆」。
本 app 用 `fwb_utils/translations/<lang>.csv` 覆盖（app 加载顺序最后，可盖过 frappe）。
"""

from __future__ import annotations

from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

CHINESE_LANGS = ("zh", "zh-CN", "zh-TW")


class TestChineseTranslationOverrides(FrappeTestCase):
    def test_month_abbreviation_not_mistranslated_as_mega(self):
        """「1兆」bug：{0} M 必须译成「月」，不能出现「兆」。"""
        for lang in CHINESE_LANGS:
            value = frappe._("{0} M", lang=lang)
            self.assertNotIn("兆", value, msg=f"{lang}: {value}")
            self.assertIn("月", value, msg=f"{lang}: {value}")
            self.assertIn("{0}", value, msg=f"{lang}: {value}")

    def test_other_short_time_units_still_translated_and_clean(self):
        """其它简写单位（分/时/天/周/年）不得被本次覆盖影响，也不得含「兆」。"""
        for source in ("{0} m", "{0} h", "{0} d", "{0} w", "{0} y"):
            value = frappe._(source, lang="zh")
            self.assertNotIn("兆", value, msg=f"{source}: {value}")
            self.assertNotEqual(value, source, msg=f"{source} 未被翻译")

    def test_override_csv_files_shipped(self):
        base = Path(frappe.get_app_path("fwb_utils")) / "translations"
        for name in ("zh.csv", "zh-CN.csv", "zh-TW.csv"):
            self.assertTrue((base / name).exists(), msg=f"缺少 {name}")
