# Copyright (c) 2025, WenZhou Furui Handicraft Co.,Ltd. and contributors
# For license information, please see license.txt

# v2025.12.08.06 - Material Readiness Check backend
# - Work Order on_submit: auto create Material Readiness Check (draft) and pull items
# - Work Order on_cancel: auto cancel / delete related checks
# - pull_from_work_order(check_name): sync header and items from Work Order / BOM
# - get_checker_employee_query:
#     * only active Employees
#     * department is under any Department whose name/department_name contains "办公职能" or "销售部"
# - Optional daily reminder function (not enabled by default)

from __future__ import unicode_literals

import frappe
from frappe.model.document import Document
from frappe.utils import getdate, flt


class MaterialReadinessCheck(Document):
    """Main DocType class for Material Readiness Check."""
    pass


@frappe.whitelist()
def pull_from_work_order(check_name: str) -> dict:
    """
    Sync Material Readiness Check from its linked Work Order:

    - Header:
        * work_order_date (from Work Order.planned_start_date or creation)
        * product_name
        * product_qty
        * size_l / size_w / size_h (from BOM custom_size_l/w/h)
        * sales_order
        * checked_by / checked_by_name:
          from Sales Order -> Sales Team -> Sales Person.employee (if any)
    - Child table items from Work Order.required_items.
    """
    if not check_name:
        frappe.throw("Missing check_name")

    check = frappe.get_doc("Material Readiness Check", check_name)

    if not check.work_order:
        frappe.throw("Please set Work Order before syncing materials.")

    wo = frappe.get_doc("Work Order", check.work_order)

    # header from Work Order
    check.work_order_date = getdate(wo.planned_start_date or wo.creation)
    check.product_name = wo.item_name or wo.production_item or ""
    check.product_qty = flt(wo.qty or 0)

    # size from BOM custom fields
    size_l = ""
    size_w = ""
    size_h = ""
    if wo.bom_no:
        bom = frappe.db.get_value(
            "BOM",
            wo.bom_no,
            ["custom_size_l", "custom_size_w", "custom_size_h"],
            as_dict=True,
        )
        if bom:
            size_l = bom.custom_size_l or ""
            size_w = bom.custom_size_w or ""
            size_h = bom.custom_size_h or ""

    check.size_l = size_l
    check.size_w = size_w
    check.size_h = size_h

    # sales order
    check.sales_order = wo.sales_order

    # === 新逻辑：从销售订单的销售团队里自动带出检查员 ===
    # 规则：
    #   Sales Order.sales_team -> 每一行的 sales_person -> 对应 Sales Person.employee
    #   取第一条能找到 employee 的记录：
    #       checked_by      = 这个 employee 的 Employee.name
    #       checked_by_name = 这个 employee 的 employee_name
    #   如果找不到任何 employee，就保持 checked_by 现有的值（可能为空或人工已选择）
    if wo.sales_order:
        try:
            so = frappe.get_doc("Sales Order", wo.sales_order)
        except frappe.DoesNotExistError:
            so = None

        if so and getattr(so, "sales_team", None):
            sales_emp_id = None
            sales_emp_name = None

            for st in so.sales_team:
                # 没选 sales_person 的行跳过
                sales_person = getattr(st, "sales_person", None)
                if not sales_person:
                    continue

                # 从 Sales Person 拿到 employee
                sp = frappe.db.get_value(
                    "Sales Person",
                    sales_person,
                    ["employee"],
                    as_dict=True,
                )
                if not sp or not sp.employee:
                    continue

                sales_emp_id = sp.employee

                emp = frappe.db.get_value(
                    "Employee",
                    sales_emp_id,
                    ["employee_name"],
                    as_dict=True,
                )
                sales_emp_name = emp.employee_name if emp else None
                # 找到第一条就用它，跳出循环
                break

            if sales_emp_id:
                check.checked_by = sales_emp_id
                if hasattr(check, "checked_by_name"):
                    check.checked_by_name = sales_emp_name or ""

    # rebuild items from Work Order required_items
    check.set("items", [])

    for it in wo.required_items:
        row = check.append("items", {})
        row.item_code = it.item_code
        row.item_name = it.item_name or it.description or ""
        row.required_qty = flt(it.required_qty or 0)
        row.uom = it.stock_uom or ""
        row.warehouse = it.source_warehouse or ""

        # is_confirmed / check_date / actual_available_qty / remarks
        # will be filled manually later

    check.save()

    return {
        "total_items": len(check.items or []),
    }



def work_order_on_submit(doc, method=None):
    """
    Hook: called when Work Order is submitted.

    Auto-create a draft Material Readiness Check linked to this Work Order,
    and pull items from Work Order / BOM.
    """
    if not doc.name:
        return

    # if there is already a related check (not cancelled), do nothing
    existing = frappe.get_all(
        "Material Readiness Check",
        filters={
            "work_order": doc.name,
            "docstatus": ["<", 2],
        },
        pluck="name",
    )
    if existing:
        return

    # create draft Material Readiness Check
    check = frappe.new_doc("Material Readiness Check")
    check.work_order = doc.name
    check.insert()

    # pull items + header data
    pull_from_work_order(check.name)


def work_order_on_cancel(doc, method=None):
    """
    Hook: called when Work Order is cancelled.

    For related Material Readiness Check:
    - if submitted -> cancel
    - if draft     -> delete
    """
    if not doc.name:
        return

    names = frappe.get_all(
        "Material Readiness Check",
        filters={"work_order": doc.name, "docstatus": ["<", 2]},
        pluck="name",
    )

    for name in names:
        check = frappe.get_doc("Material Readiness Check", name)
        if check.docstatus == 1:
            check.cancel()
        elif check.docstatus == 0:
            check.delete()


@frappe.whitelist()
def get_checker_employee_query(doctype, txt, searchfield, start, page_len, filters):
    """
    Link field query for checked_by:

    - Only active Employee
    - Department is under any Department whose name/department_name contains
      "办公职能" or "销售部" (supports department tree via lft/rgt)
    - Search by given searchfield or employee_name
    """
    search_txt = "%%%s%%" % (txt or "")
    kw1 = "%办公职能%"
    kw2 = "%销售部%"

    # Using department tree (nested set) to include all children under group departments.
    # Also allow direct match on current department name/department_name as fallback.
    query = """
        SELECT e.name, e.employee_name
        FROM `tabEmployee` e
        LEFT JOIN `tabDepartment` d ON e.department = d.name
        WHERE e.docstatus < 2
          AND e.status = 'Active'
          AND (
                EXISTS (
                    SELECT 1
                    FROM `tabDepartment` g
                    WHERE g.lft <= d.lft
                      AND g.rgt >= d.rgt
                      AND (
                           g.name LIKE %(kw1)s
                        OR g.department_name LIKE %(kw1)s
                        OR g.name LIKE %(kw2)s
                        OR g.department_name LIKE %(kw2)s
                      )
                )
                OR d.name LIKE %(kw1)s
                OR d.department_name LIKE %(kw1)s
                OR d.name LIKE %(kw2)s
                OR d.department_name LIKE %(kw2)s
          )
          AND (
                e.{searchfield} LIKE %(st)s
                OR e.employee_name LIKE %(st)s
          )
        ORDER BY e.employee_name ASC
        LIMIT %(page_len)s OFFSET %(start)s
    """.format(searchfield=searchfield)

    return frappe.db.sql(
        query,
        {
            "kw1": kw1,
            "kw2": kw2,
            "st": search_txt,
            "page_len": page_len,
            "start": start,
        },
    )


# ----------------------------------------------------------------------
# Optional: daily reminder for incomplete Material Readiness Check
# ----------------------------------------------------------------------

def _get_pending_items_for_check(check_doc):
    """Return list of child rows that are not fully confirmed."""
    pending = []
    for row in (check_doc.items or []):
        # treat anything not "齐全" as pending (including empty / 未到 / 部分 / 错误)
        if (row.is_confirmed or "").strip() != "齐全":
            pending.append(row)
    return pending

# v2025.12.09.01 - Material Readiness Check daily reminder (Chinese mail, grouped by checker)


def send_material_readiness_daily_reminder():
    """Send daily email reminder for all not-fully-ready materials.

    Rules:
    - Include Material Readiness Check with docstatus < 2 (Draft + Submitted).
    - Only child rows where is_confirmed in ("未到", "部分", "错误").
    - Group by checked_by (Employee), and send ONE mail per checker.
    - Email content is in Chinese, with an HTML table of all pending rows.
    """

    pending_status = ("未到", "部分", "错误")

    # 1) Collect all pending rows (join parent + child)
    rows = frappe.db.sql(
        """
        SELECT
            m.name               AS mrc_name,
            m.work_order,
            m.product_name,
            m.product_qty,
            m.checked_by,
            i.item_code,
            i.item_name,
            i.required_qty,
            i.actual_available_qty,
            i.uom,
            i.is_confirmed
        FROM `tabMaterial Readiness Check` m
        INNER JOIN `tabMaterial Readiness Check Item` i
            ON i.parent = m.name
        WHERE
            m.docstatus < 2
            AND COALESCE(i.is_confirmed, '') IN %(status_list)s
        ORDER BY
            m.work_order, m.name, i.idx
        """,
        {"status_list": pending_status},
        as_dict=True,
    )

    if not rows:
        # Nothing to remind today
        return {
            "status": "no_pending_items",
            "sent": [],
        }

    # 2) Group rows by checker (Employee)
    grouped_by_checker = {}
    for r in rows:
        emp = r.checked_by or "__no_checker__"
        grouped_by_checker.setdefault(emp, []).append(r)

    sent_info = []

    # 3) For each checker, resolve email and send one mail
    for emp, items in grouped_by_checker.items():
        # 3.1 resolve recipient email and display name
        email = None
        display_name = None

        if emp != "__no_checker__":
            emp_doc = frappe.db.get_value(
                "Employee",
                emp,
                ["employee_name", "user_id"],
                as_dict=True,
            )
            if emp_doc:
                display_name = emp_doc.employee_name or ""
                # In your system user_id is the login (email)
                if emp_doc.user_id:
                    email = emp_doc.user_id

        # fallback: Administrator
        if not email:
            admin = frappe.db.get_value(
                "User",
                "Administrator",
                ["email", "full_name"],
                as_dict=True,
            )
            if admin and admin.email:
                email = admin.email
                if not display_name:
                    display_name = admin.full_name or "同事"
            else:
                # No valid target, skip this group to avoid errors
                continue

        if not display_name:
            display_name = "同事"

        # 3.2 build HTML table body
        table_rows_html = ""
        work_orders = set()
        for r in items:
            work_orders.add(r.work_order or "")
            # Frappe link to MRC form
            mrc_link = frappe.utils.get_link_to_form(
                "Material Readiness Check", r.mrc_name
            )

            table_rows_html += f"""
            <tr>
                <td>{r.work_order or ""}</td>
                <td>{r.product_name or ""}</td>
                <td>{r.product_qty or ""}</td>
                <td>{r.item_code or ""}</td>
                <td>{r.item_name or ""}</td>
                <td>{r.required_qty or ""}</td>
                <td>{r.actual_available_qty or ""}</td>
                <td>{r.uom or ""}</td>
                <td>{r.is_confirmed or ""}</td>
                <td>{mrc_link}</td>
            </tr>
            """

        work_order_text = ", ".join(sorted([wo for wo in work_orders if wo])) or "无工单号"
        total_lines = len(items)

        # 3.3 email subject & message (Chinese)
        subject = f"【物料齐套提醒】共有 {total_lines} 条物料尚未齐套"

        message = f"""
        <p>{display_name} 您好，</p>
        <p>以下是目前仍未完全到位或存在异常的物料，请尽快跟进：</p>
        <ul>
            <li>涉及工单：{work_order_text}</li>
            <li>未齐套物料行数：{total_lines}</li>
        </ul>

        <table border="1" cellpadding="4" cellspacing="0" style="border-collapse: collapse; font-size: 12px;">
            <thead style="background-color: #f5f5f5;">
                <tr>
                    <th>工单号</th>
                    <th>产品名</th>
                    <th>产品数量</th>
                    <th>物料ID</th>
                    <th>物料名</th>
                    <th>所需数</th>
                    <th>现场盘点数</th>
                    <th>单位</th>
                    <th>物料情况</th>
                    <th>物料齐套单</th>
                </tr>
            </thead>
            <tbody>
                {table_rows_html}
            </tbody>
        </table>

        <p style="margin-top: 10px; color: #888;">
            本邮件由系统自动发送，用于提醒物料齐套进度，请勿直接回复此邮件。
        </p>
        """

        # 3.4 send mail
        frappe.sendmail(
            recipients=[email],
            subject=subject,
            message=message,
        )

        sent_info.append(
            {
                "employee": emp,
                "email": email,
                "rows": total_lines,
            }
        )

    return {
        "status": "ok",
        "sent": sent_info,
    }
