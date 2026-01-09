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
        amount, piece_rate, hourly_rate = compute_amount_and_piece_rate(wr)

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
            "hourly_rate": hourly_rate,
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
    conditions = []
    params = []

    conditions.append("wr.docstatus = 1")

    if filters.get("employee"):
        conditions.append("wr.employee = %s")
        params.append(filters.get("employee"))

    if filters.get("workstation"):
        conditions.append("wr.workstation = %s")
        params.append(filters.get("workstation"))

    if filters.get("product_name"):
        conditions.append("wr.product_name LIKE %s")
        params.append(f"%{filters.get('product_name')}%")

    if filters.get("from_date"):
        conditions.append("DATE(wr.created_at) >= %s")
        params.append(filters.get("from_date"))

    if filters.get("to_date"):
        conditions.append("DATE(wr.created_at) <= %s")
        params.append(filters.get("to_date"))

    condition_sql = " AND ".join(conditions) if conditions else "1=1"

    # === 关键优化：使用 LEFT JOIN 一次性取出所有关联单价 ===
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
            b.custom_size_h AS size_h,
            bo.custom_piece_rate AS bom_piece_rate,
            bo.hour_rate AS bom_hour_rate
        FROM `tabFWB Work Report` wr
        LEFT JOIN `tabWork Order` wo ON wo.name = wr.work_order
        LEFT JOIN `tabBOM` b ON b.name = wo.bom_no
        LEFT JOIN `tabBOM Operation` bo ON (bo.parent = wo.bom_no AND bo.workstation = wr.workstation)
        WHERE {condition_sql}
        ORDER BY wr.created_at ASC
        """,
        tuple(params),
        as_dict=True,
    )

    return work_reports


def compute_amount_and_piece_rate(wr):
    """
    计算逻辑严格对齐 Employee Wage Sheet，但利用 SQL 预取的数据以保证性能。
    """
    qty = flt(wr.qty or 0)
    defect_qty = flt(wr.defect_qty or 0)
    recovered_qty = flt(wr.recovered_qty or 0)
    
    # 统一使用 valid_qty 作为计算基数 (与工资表一致)
    valid_qty = flt(
        wr.valid_qty if wr.valid_qty is not None else (qty - defect_qty + recovered_qty)
    )

    wage_type = (wr.wage_type or "计件").strip()
    rework_type = (wr.rework_type or "").strip()

    amount = 0.0
    piece_rate = 0.0
    hourly_rate = 0.0

    if wage_type == "计时":
        # === 计时逻辑 ===
        # 优先级 1: BOM Operation.hour_rate (从 SQL join 获取, 别名 bom_hour_rate)
        rate = flt(wr.bom_hour_rate or 0)
        
        # 优先级 2: 报工单.hourly_rate
        if rate <= 0:
            rate = flt(wr.hourly_rate or 0)
            
        dur_sec = flt(wr.duration or 0)
        hours = dur_sec / 3600.0
        amount = hours * rate
        
        # 填充返回数据
        piece_rate = 0.0
        hourly_rate = rate

    else:
        # === 计件逻辑 ===
        final_rate = 0.0

        # 优先级 1: 有偿返工
        if rework_type == "有偿返工":
            rr = flt(wr.rework_rate or 0)
            if rr > 0:
                final_rate = rr

        # 优先级 2: BOM Operation.custom_piece_rate (从 SQL join 获取)
        if final_rate == 0:
            br = flt(wr.bom_piece_rate or 0)
            if br > 0:
                final_rate = br

        # 优先级 3: 报工单.custom_piece_rate
        if final_rate == 0:
            cr = flt(wr.custom_piece_rate or 0)
            if cr > 0:
                final_rate = cr

        # 计算金额：始终基于 valid_qty (与工资表逻辑对齐)
        amount = valid_qty * final_rate
        
        # 填充返回数据
        piece_rate = final_rate
        hourly_rate = 0.0

    return amount, piece_rate, hourly_rate


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
