# Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and Contributors
# See license.txt
"""回填历史 FWB Work Report / Rework Record 的 custom_work_order_date。

口径与 `work_order_snapshot.get_work_order_creation_date` 一致：
SQL `DATE(wo.creation)` == Python `getdate(creation)`。幂等：仅回填尚未写入的行。
"""

import frappe


def execute():
    for doctype in ("FWB Work Report", "Rework Record"):
        if not frappe.db.has_column(doctype, "custom_work_order_date"):
            continue
        frappe.db.sql(
            f"""
            UPDATE `tab{doctype}` t
            JOIN `tabWork Order` wo ON t.work_order = wo.name
            SET t.custom_work_order_date = DATE(wo.creation)
            WHERE t.work_order IS NOT NULL
              AND t.work_order != ''
              AND t.custom_work_order_date IS NULL
            """
        )
    frappe.db.commit()
