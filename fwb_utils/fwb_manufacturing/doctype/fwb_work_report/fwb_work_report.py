# Copyright (c) 2025, WenZhou Furui Handicraft Co.,Ltd. and contributors
# For license information, please see license.txt
import frappe
from frappe.model.document import Document

class FWBWorkReport(Document):
        pass

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

