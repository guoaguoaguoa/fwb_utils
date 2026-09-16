# Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and Contributors
# See license.txt
"""回填历史 Rework Record 的 custom_work_report_date（= 关联报工单 created_at 的日期）。

口径与 `work_order_snapshot.get_work_report_date` 一致：
SQL `DATE(w.created_at)` == Python `getdate(created_at)`。幂等：仅回填尚未写入的行。
"""

import frappe


def execute():
    if not frappe.db.has_column("Rework Record", "custom_work_report_date"):
        return
    frappe.db.sql(
        """
        UPDATE `tabRework Record` r
        JOIN `tabFWB Work Report` w ON r.from_work_report = w.name
        SET r.custom_work_report_date = DATE(w.created_at)
        WHERE r.from_work_report IS NOT NULL
          AND r.from_work_report != ''
          AND w.created_at IS NOT NULL
          AND r.custom_work_report_date IS NULL
        """
    )
    frappe.db.commit()
