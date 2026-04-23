# Copyright (c) 2025, WenZhou Furui Handicraft Co.,Ltd. and contributors
# For license information, please see license.txt

# v2026.04.23.01 - Employee Defect Rate Report backend
# - Denominator: sum of FWB Work Report.qty (total_qty)
# - Also show sum of valid_qty (total_valid_qty) for reference
# - Numerator: sum of Rework Record.defective_qty only
#   penalty_qty is already included inside defective_qty and must not be added again
#   good-piece recovery does not subtract from this numerator
# - One row per employee + work_order + workstation
# - Product name column comes from Work Order.item_name / FWB Work Report.product_name
# - Filter: product_name fuzzy search via Work Order.item_name / FWB Work Report.product_name
# - New: append a total row (sum of qtys + weighted defect_rate) at bottom
# - New: employee_for_workstation link query for dependent employee filter

from __future__ import unicode_literals

import frappe
from frappe.utils import flt


def execute(filters=None):
    filters = frappe._dict(filters or {})
    columns = get_columns()
    data = get_data(filters)

    # append total row at bottom
    total_row = get_total_row(data)
    if total_row:
        data.append(total_row)

    return columns, data


def get_columns():
    """Columns definition aligned with Report JSON."""
    return [
        {
            "label": "员工ID",
            "fieldname": "employee",
            "fieldtype": "Link",
            "options": "Employee",
            "width": 140,
        },
        {
            "label": "员工姓名",
            "fieldname": "employee_name",
            "fieldtype": "Data",
            "width": 160,
        },
        {
            "label": "产品名",
            "fieldname": "product_name",
            "fieldtype": "Data",
            "width": 180,
        },
        {
            "label": "有效总数",
            "fieldname": "total_valid_qty",
            "fieldtype": "Int",
            "width": 110,
        },
        {
            "label": "报工总数",
            "fieldname": "total_qty",
            "fieldtype": "Int",
            "width": 110,
        },
        {
            "label": "次品总数",
            "fieldname": "total_defect_qty",
            "fieldtype": "Int",
            "width": 110,
        },
        {
            "label": "总次品率",
            "fieldname": "defect_rate",
            "fieldtype": "Float",
            "width": 110,
        },
        {
            "label": "工单号",
            "fieldname": "work_order",
            "fieldtype": "Link",
            "options": "Work Order",
            "width": 160,
        },
        {
            "label": "工作站",
            "fieldname": "workstation",
            "fieldtype": "Link",
            "options": "Workstation",
            "width": 160,
        },
    ]


def get_data(filters):
    where_clauses = ["w.docstatus = 1"]
    params = {}

    # date range based on FWB Work Report.created_at
    if filters.get("from_date"):
        where_clauses.append("DATE(w.created_at) >= %(from_date)s")
        params["from_date"] = filters.get("from_date")

    if filters.get("to_date"):
        where_clauses.append("DATE(w.created_at) <= %(to_date)s")
        params["to_date"] = filters.get("to_date")

    if filters.get("employee"):
        where_clauses.append("w.employee = %(employee)s")
        params["employee"] = filters.get("employee")

    if filters.get("work_order"):
        where_clauses.append("w.work_order = %(work_order)s")
        params["work_order"] = filters.get("work_order")

    if filters.get("workstation"):
        where_clauses.append("w.workstation = %(workstation)s")
        params["workstation"] = filters.get("workstation")

    product_name = (filters.get("product_name") or "").strip()
    if product_name:
        where_clauses.append(
            "COALESCE(NULLIF(wo.item_name, ''), NULLIF(w.product_name, ''), '') "
            "LIKE %(product_name)s"
        )
        params["product_name"] = f"%{product_name}%"

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    # total_defect_qty deliberately aggregates Rework Record.defective_qty only.
    # Do not replace it with penalty_qty, and do not subtract reworked_qty here.
    sql = f"""
        SELECT
            w.employee                                AS employee,
            MAX(w.employee_name_display)              AS employee_name,
            MAX(COALESCE(wo.item_name, w.product_name, wo.production_item, ''))
                                                    AS product_name,
            w.work_order                              AS work_order,
            w.workstation                             AS workstation,
            SUM(IFNULL(w.valid_qty, 0))               AS total_valid_qty,
            SUM(IFNULL(w.qty, 0))                     AS total_qty,
            IFNULL(SUM(IFNULL(r_agg.total_defective_qty, 0)), 0)
                                                    AS total_defect_qty
        FROM `tabFWB Work Report` w
        LEFT JOIN (
            SELECT
                r.from_work_report,
                SUM(IFNULL(r.defective_qty, 0)) AS total_defective_qty
            FROM `tabRework Record` r
            WHERE r.docstatus = 1
            GROUP BY r.from_work_report
        ) r_agg
            ON r_agg.from_work_report = w.name
        LEFT JOIN `tabWork Order` wo
            ON wo.name = w.work_order
        {where_sql}
        GROUP BY
            w.employee,
            w.work_order,
            w.workstation
        HAVING
            total_qty > 0
            OR total_defect_qty > 0
    """

    rows = frappe.db.sql(sql, params, as_dict=True)

    result = []
    for row in rows:
        total_valid = flt(row.total_valid_qty or 0)
        total_qty = flt(row.total_qty or 0)
        total_defect = flt(row.total_defect_qty or 0)

        if total_qty > 0:
            rate = (total_defect / total_qty) * 100.0
        else:
            rate = 0.0

        result.append(
            {
                "employee": row.employee,
                "employee_name": row.employee_name,
                "product_name": row.product_name,
                "work_order": row.work_order,
                "workstation": row.workstation,
                "total_valid_qty": int(total_valid),
                "total_qty": int(total_qty),
                "total_defect_qty": int(total_defect),
                "defect_rate": round(rate, 2),
            }
        )

    return result


def get_total_row(data):
    """Build a total row based on filtered data."""
    if not data:
        return None

    sum_valid = 0
    sum_total = 0
    sum_defect = 0

    for row in data:
        sum_valid += int(row.get("total_valid_qty") or 0)
        sum_total += int(row.get("total_qty") or 0)
        sum_defect += int(row.get("total_defect_qty") or 0)

    if sum_total > 0:
        avg_rate = (flt(sum_defect) / flt(sum_total)) * 100.0
    else:
        avg_rate = 0.0

    return {
        "employee": "",
        "employee_name": "合计",
        "product_name": "",
        "work_order": "",
        "workstation": "",
        "total_valid_qty": sum_valid,
        "total_qty": sum_total,
        "total_defect_qty": sum_defect,
        "defect_rate": round(avg_rate, 2),
        "is_total_row": 1,
    }


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def employee_for_workstation(doctype, txt, searchfield, start, page_len, filters):
    """
    Link-field query for Employee filter on this report.

    Rules:
    - Data source: FWB Work Report (docstatus = 1)
    - If workstation is provided in filters:
        * only employees who have reported at this workstation
    - Else:
        * employees who have appeared in any FWB Work Report
          (optionally excluding some special workstations)
    - Return (employee, employee_name_display)
    """

    search_txt = "%%%s%%" % (txt or "")
    workstation = (filters or {}).get("workstation") if filters else None

    # Workstations to be excluded when workstation is not specified
    excluded_ws = ("发货台", "打包区", "质检区")

    if workstation:
        # limit to employees who worked on this workstation
        return frappe.db.sql(
            """
            SELECT
                w.employee,
                MAX(w.employee_name_display) AS employee_name
            FROM `tabFWB Work Report` w
            WHERE
                w.docstatus = 1
                AND w.workstation = %(workstation)s
                AND (
                    w.employee LIKE %(st)s
                    OR IFNULL(w.employee_name_display, '') LIKE %(st)s
                )
            GROUP BY w.employee
            ORDER BY employee_name ASC
            LIMIT %(start)s, %(page_len)s
            """,
            {
                "workstation": workstation,
                "st": search_txt,
                "start": start,
                "page_len": page_len,
            },
        )

    # no workstation filter: show employees from all non-excluded workstations
    return frappe.db.sql(
        """
        SELECT
            w.employee,
            MAX(w.employee_name_display) AS employee_name
        FROM `tabFWB Work Report` w
        WHERE
            w.docstatus = 1
            AND COALESCE(w.workstation, '') NOT IN %(excluded_ws)s
            AND (
                w.employee LIKE %(st)s
                OR IFNULL(w.employee_name_display, '') LIKE %(st)s
            )
        GROUP BY w.employee
        ORDER BY employee_name ASC
        LIMIT %(start)s, %(page_len)s
        """,
        {
            "st": search_txt,
            "excluded_ws": excluded_ws,
            "start": start,
            "page_len": page_len,
        },
    )
