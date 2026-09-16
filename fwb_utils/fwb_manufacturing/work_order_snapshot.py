# Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and Contributors
# See license.txt
"""列表日期快照：把关联单据的日期快照到本单本地字段，供列表页按范围筛选。

- `custom_work_order_date`：关联 Work Order 的建立日期(creation)
  （FWB Work Report / Rework Record）
- `custom_work_report_date`：关联 FWB Work Report 的报工时间点(created_at) 的日期
  （Rework Record；返工单自身 `created_at` 是质检时间，不是报工日期）

为什么快照而不是实时反查 / fetch_from：
- 两个源日期都不再变化：Work Order.creation 不可变；Rework Record 界面只能关联已提交
  (docstatus=1) 的报工单，且 FWB Work Report.created_at 未开 allow_on_submit。故快照恒等于实时值。
- 全仓无 `fetch_from ...creation` 先例，改用可单测的 Python 钩子。
- 本地列可被列表按范围直接筛选；钩子与 backfill patch 同口径（`getdate` == SQL `DATE()`）。
"""

import frappe
from frappe.utils import getdate

WORK_ORDER_DATE_FIELD = "custom_work_order_date"
WORK_REPORT_DATE_FIELD = "custom_work_report_date"


def get_work_order_creation_date(work_order):
    """返回工单建立日期(creation) 的日期部分；无工单或查不到返回 None。"""
    if not work_order:
        return None
    creation = frappe.db.get_value("Work Order", work_order, "creation")
    return getdate(creation) if creation else None


def get_work_report_date(work_report):
    """返回报工单报工时间点(created_at) 的日期部分；无报工单或查不到返回 None。"""
    if not work_report:
        return None
    created_at = frappe.db.get_value("FWB Work Report", work_report, "created_at")
    return getdate(created_at) if created_at else None


def set_work_order_date_snapshot(doc, method=None):
    """doc_events(validate) 钩子：写入 `custom_work_order_date`。

    字段尚未 migrate 时静默跳过，保证代码先于 DocType 上线也不抛错。
    """
    if not doc.meta.get_field(WORK_ORDER_DATE_FIELD):
        return
    doc.set(WORK_ORDER_DATE_FIELD, get_work_order_creation_date(doc.get("work_order")))


def set_work_report_date_snapshot(doc, method=None):
    """Rework Record doc_events(validate) 钩子：写入 `custom_work_report_date`。"""
    if not doc.meta.get_field(WORK_REPORT_DATE_FIELD):
        return
    doc.set(WORK_REPORT_DATE_FIELD, get_work_report_date(doc.get("from_work_report")))
