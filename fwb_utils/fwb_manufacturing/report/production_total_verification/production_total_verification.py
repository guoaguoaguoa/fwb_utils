# v2026.01.10.01 - 生产总数核对报告 (草稿+已提交)

import frappe
from frappe import _
from frappe.utils import getdate

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
        {
            "fieldname": "order_qty",
            "label": "工单总数",
            "fieldtype": "Int",
            "width": 90
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
    filters = frappe._dict(filters or {})
    date_filter_active = bool(filters.get("from_date") or filters.get("to_date"))
    conditions = get_conditions(filters)
    cumulative_conditions = get_cumulative_conditions(filters)
    
    # SQL 逻辑说明：
    # 1. 关联 Work Order 获取下单日期、产品名和工单总数
    # 2. 关联 BOM 获取尺寸
    # 3. 使用 SUM(CASE...) 将行数据(工作站)转置为列数据(本期总数)
    # 4. 额外返回截至筛选结束日的工单工作站累计数，供前端区分历史生产
    
    sql = f"""
        SELECT
            DATE(wo.planned_start_date) as order_date,
            wr.work_order,
            wo.item_name as product_name,
            wo.qty as order_qty,
            
            /* 数据透视：按工作站汇总数量 */
            SUM(CASE WHEN wr.workstation = '木工房' THEN wr.valid_qty ELSE 0 END) as woodworking_qty,
            SUM(CASE WHEN wr.workstation = '底漆房' THEN wr.valid_qty ELSE 0 END) as primer_qty,
            SUM(CASE WHEN wr.workstation = '面漆房' THEN wr.valid_qty ELSE 0 END) as top_coat_qty,
            SUM(CASE WHEN wr.workstation = '装配区' THEN wr.valid_qty ELSE 0 END) as assembly_qty,
            SUM(CASE WHEN wr.workstation = '抛光区' THEN wr.valid_qty ELSE 0 END) as polishing_qty,
            SUM(CASE WHEN wr.workstation = '软包区' THEN wr.valid_qty ELSE 0 END) as lining_qty,

            /* 隐藏辅助字段：截至结束日的该工单工作站累计数 */
            MAX(IFNULL(wr_cumulative_totals.woodworking_qty_cumulative, 0)) as woodworking_qty_cumulative,
            MAX(IFNULL(wr_cumulative_totals.primer_qty_cumulative, 0)) as primer_qty_cumulative,
            MAX(IFNULL(wr_cumulative_totals.top_coat_qty_cumulative, 0)) as top_coat_qty_cumulative,
            MAX(IFNULL(wr_cumulative_totals.assembly_qty_cumulative, 0)) as assembly_qty_cumulative,
            MAX(IFNULL(wr_cumulative_totals.polishing_qty_cumulative, 0)) as polishing_qty_cumulative,
            MAX(IFNULL(wr_cumulative_totals.lining_qty_cumulative, 0)) as lining_qty_cumulative,
            
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
        LEFT JOIN (
            SELECT
                wr_cumulative.work_order,
                SUM(CASE WHEN wr_cumulative.workstation = '木工房' THEN wr_cumulative.valid_qty ELSE 0 END) as woodworking_qty_cumulative,
                SUM(CASE WHEN wr_cumulative.workstation = '底漆房' THEN wr_cumulative.valid_qty ELSE 0 END) as primer_qty_cumulative,
                SUM(CASE WHEN wr_cumulative.workstation = '面漆房' THEN wr_cumulative.valid_qty ELSE 0 END) as top_coat_qty_cumulative,
                SUM(CASE WHEN wr_cumulative.workstation = '装配区' THEN wr_cumulative.valid_qty ELSE 0 END) as assembly_qty_cumulative,
                SUM(CASE WHEN wr_cumulative.workstation = '抛光区' THEN wr_cumulative.valid_qty ELSE 0 END) as polishing_qty_cumulative,
                SUM(CASE WHEN wr_cumulative.workstation = '软包区' THEN wr_cumulative.valid_qty ELSE 0 END) as lining_qty_cumulative
            FROM
                `tabFWB Work Report` wr_cumulative
            WHERE
                wr_cumulative.docstatus < 2
                AND (
                    wr_cumulative.rework_type = '否'
                    OR wr_cumulative.rework_type IS NULL
                    OR wr_cumulative.rework_type = ''
                )
                {cumulative_conditions}
            GROUP BY
                wr_cumulative.work_order
        ) wr_cumulative_totals ON wr_cumulative_totals.work_order = wr.work_order
        
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
    for row in data:
        row["date_filter_active"] = int(date_filter_active)

    return data

def get_conditions(filters):
    conditions = ""
    
    # 1. 日期筛选：针对 FWB Work Report 的 created_at (报工时间)
    if filters.get("from_date"):
        filters["from_date"] = get_day_start(filters.get("from_date"))
        conditions += " AND wr.created_at >= %(from_date)s"
        
    if filters.get("to_date"):
        filters["to_date"] = get_day_end(filters.get("to_date"))
        conditions += " AND wr.created_at <= %(to_date)s"

    # 2. 工单号筛选：支持直接输入、局部匹配，并容错 W0-/WO- 混淆
    if filters.get("work_order"):
        filters["work_order"] = f"%{normalize_work_order_filter(filters.get('work_order'))}%"
        conditions += " AND wr.work_order LIKE %(work_order)s"

    # 3. 产品名筛选 (支持模糊搜索)
    if filters.get("product_name"):
        filters["product_name"] = f"%{str(filters.get('product_name')).strip()}%"
        # 注意：这里筛选的是工单上的 item_name
        conditions += " AND wo.item_name LIKE %(product_name)s"

    return conditions

def get_cumulative_conditions(filters):
    if filters.get("to_date"):
        return " AND wr_cumulative.created_at <= %(to_date)s"

    return ""

def normalize_work_order_filter(work_order):
    work_order = str(work_order).strip()
    if work_order.upper().startswith("W0-"):
        work_order = "WO-" + work_order[3:]

    return work_order

def get_day_start(date_value):
    return f"{getdate(date_value)} 00:00:00"

def get_day_end(date_value):
    return f"{getdate(date_value)} 23:59:59"
