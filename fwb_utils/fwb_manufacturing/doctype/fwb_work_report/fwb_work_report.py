# Copyright (c) 2025, WenZhou Furui Handicraft Co.,Ltd. and contributors
# For license information, please see license.txt
import frappe
from frappe.model.document import Document
from frappe.utils import flt

class FWBWorkReport(Document):
        pass


@frappe.whitelist()
def get_bom_hour_rate(work_order=None, workstation=None):
    """
    Server-side lookup for BOM Operation.hour_rate used by worker-side FWB Work Report.

    The browser should not read BOM Operation directly because shop-floor users
    usually don't have read permission on that child table.
    """
    return _get_bom_hour_rate_info(work_order, workstation)

@frappe.whitelist()
def get_production_employee_query(doctype, txt, searchfield, start, page_len, filters):
    """FWB Work Report 用的员工过滤：
    - 只要 Active 员工
    - 默认：在 Employee Operation 里，至少有一个工作站是 6 个生产工位之一
    - 如果前端传入 filters.workstation，则只按该工作站过滤
    """
    text = f"%{txt or ''}%"

    # 确保 filters 一定是字典
    filters = filters or {}
    ws_filter = filters.get("workstation")

    # 如果指定了 workstation，则只按这个工作站过滤；
    # 否则退回到默认的 6 个生产工位列表。
    if ws_filter:
        workstations = (ws_filter,)
    else:
        workstations = (
            "木工房",
            "底漆房",
            "面漆房",
            "装配区",
            "抛光区",
            "软包区",
        )

    return frappe.db.sql(
        f"""
        SELECT
            e.name,
            e.employee_name
        FROM `tabEmployee` e
        INNER JOIN `tabEmployee Operation` op
            ON op.parent = e.name
        WHERE
            e.status = 'Active'
            AND e.docstatus < 2
            AND op.workstation IN %(ws)s
            AND (
                e.{searchfield} LIKE %(text)s
                OR e.employee_name LIKE %(text)s
            )
        GROUP BY e.name
        ORDER BY e.employee_name ASC
        LIMIT %(page_len)s OFFSET %(start)s
        """,
        {
            "ws": workstations,
            "text": text,
            "page_len": page_len,
            "start": start,
        },
    )


def _get_bom_hour_rate_info(work_order, workstation):
    if not work_order or not workstation:
        return {"bom_no": "", "hour_rate": 0.0}

    wo = frappe.db.get_value("Work Order", work_order, ["bom_no"], as_dict=True)
    bom_no = (wo.bom_no if wo else "") or ""
    if not bom_no:
        return {"bom_no": "", "hour_rate": 0.0}

    op = frappe.get_all(
        "BOM Operation",
        filters={"parent": bom_no, "workstation": workstation},
        fields=["hour_rate"],
        ignore_permissions=True,
        limit=1,
    )
    hour_rate = flt((op[0] or {}).get("hour_rate")) if op else 0.0

    return {
        "bom_no": bom_no,
        "hour_rate": hour_rate,
    }
