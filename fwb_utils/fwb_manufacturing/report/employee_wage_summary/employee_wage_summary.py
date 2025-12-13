# v2025.12.09.01 - Employee Wage Summary report backend
# - Add total row for amount / defect_qty / duration / valid_qty
# - Support employee filter
# - Add link queries for Employee / Workstation filters in report JS

from __future__ import unicode_literals
import frappe
from frappe.utils import flt


def execute(filters=None):
    """
    Entry point for Script Report.

    Args:
        filters (dict): report filters

    Returns:
        tuple: (columns, data)
    """
    filters = filters or {}
    columns = get_columns()
    data = get_data(filters)
    return columns, data


def get_columns():
    """
    Define report columns.
    Fieldnames MUST match keys in each data row.
    """
    return [
        {
            "label": "报工日期",
            "fieldname": "posting_date",
            "fieldtype": "Datetime",
            "width": 130,
        },
        {
            "label": "员工姓名",
            "fieldname": "employee_name",
            "fieldtype": "Data",
            "width": 100,
        },
        {
            "label": "产品名",
            "fieldname": "product_name",
            "fieldtype": "Data",
            "width": 120,
        },
        {
            "label": "长",
            "fieldname": "size_l",
            "fieldtype": "Data",
            "width": 70,
        },
        {
            "label": "宽",
            "fieldname": "size_w",
            "fieldtype": "Data",
            "width": 70,
        },
        {
            "label": "高",
            "fieldname": "size_h",
            "fieldtype": "Data",
            "width": 70,
        },
        {
            "label": "工作站",
            "fieldname": "workstation",
            "fieldtype": "Link",
            "options": "Workstation",
            "width": 90,
        },
        {
            "label": "计件单价",
            "fieldname": "piece_rate",
            "fieldtype": "Currency",
            "width": 100,
        },
        {
            "label": "有效数量",
            "fieldname": "valid_qty",
            "fieldtype": "Int",
            "width": 60,
        },
        {
            "label": "有效工时",
            "fieldname": "duration",
            "fieldtype": "Duration",
            "width": 60,
        },
        {
            "label": "时薪价",
            "fieldname": "hourly_rate",
            "fieldtype": "Currency",
            "width": 100,
        },
        {
            "label": "本行工资金额",
            "fieldname": "amount",
            "fieldtype": "Currency",
            "width": 140,
        },
        {
            "label": "次品数量",
            "fieldname": "defect_qty",
            "fieldtype": "Int",
            "width": 70,
        },
        {
            "label": "次品率",
            "fieldname": "defect_rate",
            "fieldtype": "Percent",
            "width": 100,
        },
        {
            "label": "工单号",
            "fieldname": "work_order",
            "fieldtype": "Link",
            "options": "Work Order",
            "width": 150,
        },
        {
            "label": "员工ID",
            "fieldname": "employee",
            "fieldtype": "Link",
            "options": "Employee",
            "width": 120,
        },
    ]


def get_data(filters):
    """
    Fetch and build data rows.

    Filters supported (from report JSON / JS):
        - employee (Link Employee)
        - workstation (Link Workstation)
        - from_date (Date)
        - to_date (Date)
        - product_name (Data)
    """
    rows = get_work_reports(filters)
    if not rows:
        return []

    data = []

    total_amount = 0.0
    total_defect_qty = 0.0
    total_valid_qty = 0.0
    total_duration = 0.0

    for wr in rows:
        # same logic as client for amount / piece_rate
        amount, piece_rate = compute_amount_and_piece_rate(wr)

        # defect rate = defect_qty / (valid_qty + defect_qty)
        defect_qty = flt(wr.defect_qty or 0)
        valid_qty = flt(wr.valid_qty or 0)
        defect_denominator = valid_qty + defect_qty
        defect_rate = 0.0
        if defect_denominator > 0:
            defect_rate = (defect_qty / defect_denominator) * 100.0

        duration_seconds = flt(wr.duration or 0)

        row = {
            "posting_date": wr.posting_date,
            "employee": wr.employee,
            "employee_name": wr.employee_name_display,
            "work_order": wr.work_order,
            "product_name": wr.product_name,
            "size_l": wr.size_l,
            "size_w": wr.size_w,
            "size_h": wr.size_h,
            "workstation": wr.workstation,
            "piece_rate": piece_rate,
            "valid_qty": valid_qty,
            "duration": duration_seconds,
            "hourly_rate": flt(wr.hourly_rate or 0),
            "amount": amount,
            "defect_qty": defect_qty,
            "defect_rate": defect_rate,
        }

        data.append(row)

        # accumulate totals
        total_amount += amount
        total_defect_qty += defect_qty
        total_valid_qty += valid_qty
        total_duration += duration_seconds

    # append total row at bottom (affected by filters)
    if data:
        total_row = {
            "posting_date": None,
            "employee": "",
            "employee_name": "合计",
            "work_order": "",
            "product_name": "",
            "size_l": "",
            "size_w": "",
            "size_h": "",
            "workstation": "",
            "piece_rate": None,
            "valid_qty": total_valid_qty,
            "duration": total_duration,
            "hourly_rate": None,
            "amount": total_amount,
            "defect_qty": total_defect_qty,
            "defect_rate": None,
        }
        # mark as total row
        total_row["is_total_row"] = 1
        data.append(total_row)

    return data


def get_work_reports(filters):
    """
    Load FWB Work Report rows with all required joins.

    We join:
        - Work Order: to fetch BOM no and production item
        - BOM: to fetch size_l / size_w / size_h (custom fields)
    """

    conditions = []
    params = []

    # Only submitted reports (docstatus = 1)
    conditions.append("wr.docstatus = 1")

    # Filter by employee (Link)
    employee = filters.get("employee")
    if employee:
        conditions.append("wr.employee = %s")
        params.append(employee)

    # Filter by workstation
    workstation = filters.get("workstation")
    if workstation:
        conditions.append("wr.workstation = %s")
        params.append(workstation)

    # Filter by product name (from FWB Work Report)
    product_name = filters.get("product_name")
    if product_name:
        conditions.append("wr.product_name LIKE %s")
        params.append(f"%{product_name}%")

    # Filter by date range on created_at (posting_date)
    from_date = filters.get("from_date")
    if from_date:
        conditions.append("DATE(wr.created_at) >= %s")
        params.append(from_date)

    to_date = filters.get("to_date")
    if to_date:
        conditions.append("DATE(wr.created_at) <= %s")
        params.append(to_date)

    condition_sql = " AND ".join(conditions) if conditions else "1=1"

    # Note: custom_size_l/w/h are on BOM as DB columns
    work_reports = frappe.db.sql(
        f"""
        SELECT
            wr.name,
            wr.employee,
            wr.employee_name_display,
            wr.work_order,
            wr.product_name,
            wr.workstation,
            wr.wage_type,
            wr.rework_type,
            wr.qty,
            wr.hourly_rate,
            wr.custom_piece_rate,
            wr.rework_rate,
            wr.total_amount,
            wr.duration,
            wr.created_at AS posting_date,
            wr.defect_qty,
            wr.recovered_qty,
            wr.valid_qty,
            wo.bom_no,
            b.custom_size_l AS size_l,
            b.custom_size_w AS size_w,
            b.custom_size_h AS size_h
        FROM `tabFWB Work Report` wr
        LEFT JOIN `tabWork Order` wo ON wo.name = wr.work_order
        LEFT JOIN `tabBOM` b ON b.name = wo.bom_no
        WHERE {condition_sql}
        ORDER BY wr.created_at ASC
        """,
        tuple(params),
        as_dict=True,
    )

    return work_reports


def compute_amount_and_piece_rate(wr):
    """
    Compute amount and piece_rate using the same logic
    as the client-side JS (calculate_total).

    Logic:
        valid_qty = qty - defect_qty + recovered_qty
        if wage_type == "计时":
            amount = (duration_in_seconds / 3600) * hourly_rate
            piece_rate = 0
        else:
            if rework_type == "有偿返工":
                amount = qty * rework_rate
                piece_rate = rework_rate
            else:
                amount = valid_qty * custom_piece_rate
                piece_rate = custom_piece_rate
    """
    qty = flt(wr.qty or 0)
    defect_qty = flt(wr.defect_qty or 0)
    recovered_qty = flt(wr.recovered_qty or 0)
    valid_qty = flt(
        wr.valid_qty if wr.valid_qty is not None else (qty - defect_qty + recovered_qty)
    )

    wage_type = (wr.wage_type or "计件").strip()
    rework_type = (wr.rework_type or "").strip()

    amount = 0.0
    piece_rate = 0.0

    if wage_type == "计时":
        # duration is stored as seconds in ERPNext Duration field
        dur_sec = flt(wr.duration or 0)
        hours = dur_sec / 3600.0
        amount = hours * flt(wr.hourly_rate or 0)
        piece_rate = 0.0
    else:
        # piece-work mode
        if rework_type == "有偿返工":
            amount = qty * flt(wr.rework_rate or 0)
            piece_rate = flt(wr.rework_rate or 0)
        else:
            amount = valid_qty * flt(wr.custom_piece_rate or 0)
            piece_rate = flt(wr.custom_piece_rate or 0)

    return amount, piece_rate


@frappe.whitelist()
def get_employee_for_wage_summary(doctype, txt, searchfield, start, page_len, filters=None):
    """
    Link field query for Employee filter in Employee Wage Summary report.

    Behavior:
    - If workstation filter is set, only return employees that have FWB Work Reports on that workstation.
    - Otherwise, return all employees that have any FWB Work Report.
    - Uses employee code and employee_name_display for searching.
    """
    if filters is None:
        filters = {}

    if not isinstance(filters, dict):
        try:
            filters = frappe.parse_json(filters)
        except Exception:
            filters = {}

    workstation = filters.get("workstation")

    search_txt = "%%%s%%" % (txt or "")

    conditions = ["wr.docstatus = 1"]
    params = {
        "st": search_txt,
        "page_len": page_len,
        "start": start,
    }

    if workstation:
        conditions.append("wr.workstation = %(ws)s")
        params["ws"] = workstation

    where_sql = " AND ".join(conditions)

    query = f"""
        SELECT DISTINCT wr.employee, wr.employee_name_display
        FROM `tabFWB Work Report` wr
        WHERE {where_sql}
          AND (wr.employee LIKE %(st)s OR wr.employee_name_display LIKE %(st)s)
        ORDER BY wr.employee_name_display ASC, wr.employee ASC
        LIMIT %(page_len)s OFFSET %(start)s
    """

    return frappe.db.sql(query, params)


@frappe.whitelist()
def get_workstation_for_wage_summary(doctype, txt, searchfield, start, page_len, filters=None):
    """
    Link field query for Workstation filter in Employee Wage Summary report.

    Behavior:
    - Exclude some workstations (shipping / packing / QC).
    - Search by name or workstation_name.
    """
    banned_names = ["发货台", "打包区", "质检区"]

    search_txt = "%%%s%%" % (txt or "")

    query = """
        SELECT w.name, w.workstation_name
        FROM `tabWorkstation` w
        WHERE w.docstatus < 2
          AND (w.name LIKE %(st)s OR w.workstation_name LIKE %(st)s)
          AND w.name NOT IN %(banned)s
          AND w.workstation_name NOT IN %(banned)s
        ORDER BY w.workstation_name ASC, w.name ASC
        LIMIT %(page_len)s OFFSET %(start)s
    """

    params = {
        "st": search_txt,
        "banned": tuple(banned_names),
        "page_len": page_len,
        "start": start,
    }

    return frappe.db.sql(query, params)
