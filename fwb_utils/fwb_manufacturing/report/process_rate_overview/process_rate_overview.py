# v2025.12.04.01 - Process Rate Overview report backend

from __future__ import unicode_literals
import frappe
from frappe.utils import flt


def execute(filters=None):
    """
    Entry point for Script Report.

    Returns:
        columns (list): column definitions
        data (list): list of row dicts
    """
    filters = filters or {}
    columns = get_columns()
    data = get_data(filters)
    return columns, data


def get_columns():
    """
    Process Rate Overview 报表的列定义（可直接复制使用）
    - 已按你现在的需求调整列顺序
    - 长/宽/高宽度改为 70
    """

    return [
        {
            "label": "产品名",
            "fieldname": "item_name",
            "fieldtype": "Data",
            "width": 150,
        },
        {
            "label": "长",
            "fieldname": "size_l",
            "fieldtype": "Data",
            "width": 70,     # ← 缩短
        },
        {
            "label": "宽",
            "fieldname": "size_w",
            "fieldtype": "Data",
            "width": 70,     # ← 缩短
        },
        {
            "label": "高",
            "fieldname": "size_h",
            "fieldtype": "Data",
            "width": 70,     # ← 缩短
        },
        {
            "label": "木工单价",
            "fieldname": "wood_rate",
            "fieldtype": "Currency",
            "width": 110,
        },
        {
            "label": "裱纸单价",
            "fieldname": "mounting_rate",
            "fieldtype": "Currency",
            "width": 110,
        },
        {
            "label": "贴皮单价",
            "fieldname": "veneer_rate",
            "fieldtype": "Currency",
            "width": 110,
        },
        {
            "label": "底漆单价",
            "fieldname": "primer_rate",
            "fieldtype": "Currency",
            "width": 110,
        },
        {
            "label": "面漆单价",
            "fieldname": "topcoat_rate",
            "fieldtype": "Currency",
            "width": 110,
        },
        {
            "label": "抛光单价",
            "fieldname": "polish_rate",
            "fieldtype": "Currency",
            "width": 110,
        },
        {
            "label": "装配单价",
            "fieldname": "assembly_rate",
            "fieldtype": "Currency",
            "width": 110,
        },
        {
            "label": "软包单价",
            "fieldname": "upholstery_rate",
            "fieldtype": "Currency",
            "width": 110,
        },
        {
            "label": "物料类别",
            "fieldname": "item_group",
            "fieldtype": "Link",
            "options": "Item Group",
            "width": 120,
        },
        {
            "label": "BOM 编号",
            "fieldname": "bom",
            "fieldtype": "Link",
            "options": "BOM",
            "width": 140,
        },
        {
            "label": "成品物料",
            "fieldname": "item_code",
            "fieldtype": "Link",
            "options": "Item",
            "width": 130,
        },
    ]


def get_data(filters):
    """
    Build data rows for the report.
    One row = one BOM.
    """
    bom_rows = get_bom_list(filters)

    if not bom_rows:
        return []

    data = []
    for bom_row in bom_rows:
        rates = get_operation_rates_for_bom(bom_row.bom_name)

        row = {
            "bom": bom_row.bom_name,
            "item_code": bom_row.item_code,
            "item_name": bom_row.item_name,
            "size_l": bom_row.size_l,
            "size_w": bom_row.size_w,
            "size_h": bom_row.size_h,
            "wood_rate": rates.get("wood_rate", 0),
            "mounting_rate": rates.get("mounting_rate", 0),
            "veneer_rate": rates.get("veneer_rate", 0),
            "primer_rate": rates.get("primer_rate", 0),
            "topcoat_rate": rates.get("topcoat_rate", 0),
            "polish_rate": rates.get("polish_rate", 0),
            "assembly_rate": rates.get("assembly_rate", 0),
            "upholstery_rate": rates.get("upholstery_rate", 0),
            "item_group": bom_row.item_group,
        }
        data.append(row)

    return data


def get_bom_list(filters):
    """
    Fetch BOM + Item basic info according to filters.

    Notes:
    - Custom fields size_l / size_w / size_h live in DB as
      custom_size_l / custom_size_w / custom_size_h on tabBOM.
    - Item group is fetched from tabItem.item_group.
    """
    conditions = []
    params = []

    # Only active BOMs
    conditions.append("b.is_active = 1")

    item_group = filters.get("item_group")
    if item_group:
        conditions.append("i.item_group = %s")
        params.append(item_group)

    item_name = filters.get("item_name")
    if item_name:
        conditions.append("i.item_name LIKE %s")
        params.append(f"%{item_name}%")

    condition_sql = " AND ".join(conditions) if conditions else "1=1"

    bom_rows = frappe.db.sql(
        f"""
        SELECT
            b.name AS bom_name,
            b.item AS item_code,
            COALESCE(b.item_name, i.item_name) AS item_name,
            b.custom_size_l AS size_l,
            b.custom_size_w AS size_w,
            b.custom_size_h AS size_h,
            i.item_group
        FROM `tabBOM` b
        LEFT JOIN `tabItem` i ON i.name = b.item
        WHERE {condition_sql}
        ORDER BY b.modified DESC
        """,
        tuple(params),
        as_dict=True,
    )

    return bom_rows


def get_operation_rates_for_bom(bom_name):
    """
    Read all BOM Operation rows under a given BOM
    and map workstation -> rate fields.

    Workstation name mapping:
    - 木工房  -> wood_rate
    - 裱纸区  -> mounting_rate
    - 贴皮区  -> veneer_rate
    - 底漆房  -> primer_rate
    - 面漆房  -> topcoat_rate
    - 抛光区  -> polish_rate
    - 装配区  -> assembly_rate
    - 软包区  -> upholstery_rate
    """
    rates = {
        "wood_rate": 0.0,
        "mounting_rate": 0.0,
        "veneer_rate": 0.0,
        "primer_rate": 0.0,
        "topcoat_rate": 0.0,
        "polish_rate": 0.0,
        "assembly_rate": 0.0,
        "upholstery_rate": 0.0,
    }

    if not bom_name:
        return rates

    operations = frappe.db.sql(
        """
        SELECT workstation, custom_piece_rate
        FROM `tabBOM Operation`
        WHERE parent = %s
        """,
        (bom_name,),
        as_dict=True,
    )

    if not operations:
        return rates

    for op in operations:
        ws = (op.workstation or "").strip()
        rate_val = flt(op.custom_piece_rate)

        if not ws:
            continue

        if ws == "木工房":
            rates["wood_rate"] = rate_val
        elif ws == "裱纸区":
            rates["mounting_rate"] = rate_val
        elif ws == "贴皮区":
            rates["veneer_rate"] = rate_val
        elif ws == "底漆房":
            rates["primer_rate"] = rate_val
        elif ws == "面漆房":
            rates["topcoat_rate"] = rate_val
        elif ws == "抛光区":
            rates["polish_rate"] = rate_val
        elif ws == "装配区":
            rates["assembly_rate"] = rate_val
        elif ws == "软包区":
            rates["upholstery_rate"] = rate_val

    return rates


# Example: how to manually throw an error with debug info
# You can uncomment this block temporarily when debugging.
#
# def debug_example():
#     test_data = {"hello": "world"}
#     frappe.throw(f"DEBUG: test_data = {test_data}")
