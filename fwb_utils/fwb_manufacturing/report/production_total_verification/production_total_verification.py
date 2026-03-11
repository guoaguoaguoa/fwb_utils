# v2026.01.10.01 - 生产总数核对报告 (草稿+已提交)

import frappe
from frappe import _

def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    return columns, data

def get_columns():
    return [
        {
            "fieldname": "order_date",
            "label": "下单日期",
            "fieldtype": "Date",
            "width": 100
        },
        {
            "fieldname": "work_order",
            "label": "工单号",
            "fieldtype": "Link",
            "options": "Work Order",
            "width": 160
        },
        {
            "fieldname": "product_name",
            "label": "产品名",
            "fieldtype": "Data",
            "width": 180
        },
        # --- 6个工作站统计 ---
        {
            "fieldname": "woodworking_qty",
            "label": "木工总数",
            "fieldtype": "Int",
            "width": 80
        },
        {
            "fieldname": "primer_qty",
            "label": "底漆总数",
            "fieldtype": "Int",
            "width": 80
        },
        {
            "fieldname": "top_coat_qty",
            "label": "面漆总数",
            "fieldtype": "Int",
            "width": 80
        },
        {
            "fieldname": "assembly_qty",
            "label": "装订总数", # 对应数据库: 装配区
            "fieldtype": "Int",
            "width": 80
        },
        {
            "fieldname": "polishing_qty",
            "label": "抛光总数",
            "fieldtype": "Int",
            "width": 80
        },
        {
            "fieldname": "lining_qty",
            "label": "软包总数",
            "fieldtype": "Int",
            "width": 80
        },
        # --- BOM 尺寸 ---
        {
            "fieldname": "size_l",
            "label": "长",
            "fieldtype": "Data",
            "width": 60
        },
        {
            "fieldname": "size_w",
            "label": "宽",
            "fieldtype": "Data",
            "width": 60
        },
        {
            "fieldname": "size_h",
            "label": "高",
            "fieldtype": "Data",
            "width": 60
        }
    ]

def get_data(filters):
    conditions = get_conditions(filters)
    
    # SQL 逻辑说明：
    # 1. 关联 Work Order 获取下单日期和产品名
    # 2. 关联 BOM 获取尺寸
    # 3. 使用 SUM(CASE...) 将行数据(工作站)转置为列数据(总数)
    
    sql = f"""
        SELECT
            DATE(wo.planned_start_date) as order_date,
            wr.work_order,
            wo.item_name as product_name,
            
            /* 数据透视：按工作站汇总数量 */
            SUM(CASE WHEN wr.workstation = '木工房' THEN wr.valid_qty ELSE 0 END) as woodworking_qty,
            SUM(CASE WHEN wr.workstation = '底漆房' THEN wr.valid_qty ELSE 0 END) as primer_qty,
            SUM(CASE WHEN wr.workstation = '面漆房' THEN wr.valid_qty ELSE 0 END) as top_coat_qty,
            SUM(CASE WHEN wr.workstation = '装配区' THEN wr.valid_qty ELSE 0 END) as assembly_qty,
            SUM(CASE WHEN wr.workstation = '抛光区' THEN wr.valid_qty ELSE 0 END) as polishing_qty,
            SUM(CASE WHEN wr.workstation = '软包区' THEN wr.valid_qty ELSE 0 END) as lining_qty,
            
            /* BOM 尺寸 */
            bom.custom_size_l as size_l,
            bom.custom_size_w as size_w,
            bom.custom_size_h as size_h

        FROM
            `tabFWB Work Report` wr
        INNER JOIN
            `tabWork Order` wo ON wr.work_order = wo.name
        LEFT JOIN
            `tabBOM` bom ON wo.bom_no = bom.name
        
        WHERE
            wr.docstatus < 2  /* 0=草稿, 1=已提交 (排除2=已取消) */
            AND (wr.rework_type = '否' OR wr.rework_type IS NULL OR wr.rework_type = '')
            {conditions}
            
        GROUP BY
            wr.work_order
        ORDER BY
            wo.planned_start_date DESC
    """
    
    data = frappe.db.sql(sql, filters, as_dict=True)
    return data

def get_conditions(filters):
    conditions = ""
    
    # 1. 日期筛选：针对 FWB Work Report 的 created_at (报工时间)
    if filters.get("from_date"):
        filters["from_date"] = f"{filters.get('from_date')} 00:00:00"
        conditions += " AND wr.created_at >= %(from_date)s"
        
    if filters.get("to_date"):
        filters["to_date"] = f"{filters.get('to_date')} 23:59:59"
        conditions += " AND wr.created_at <= %(to_date)s"

    # 2. 工单号筛选
    if filters.get("work_order"):
        conditions += " AND wr.work_order = %(work_order)s"

    # 3. 产品名筛选 (支持模糊搜索)
    if filters.get("product_name"):
        filters["product_name"] = f"%{filters.get('product_name')}%"
        # 注意：这里筛选的是工单上的 item_name
        conditions += " AND wo.item_name LIKE %(product_name)s"

    return conditions
