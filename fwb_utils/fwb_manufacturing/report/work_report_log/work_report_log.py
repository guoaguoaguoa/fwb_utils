# v2026.01.10.06 - 工人个人报工记录 (修复合计行类型错误)

import frappe
from frappe import _
from frappe.utils import flt # 引入浮点转换工具

def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    
    # === [修复点] 计算合计行 ===
    if data:
        total_qty = 0.0 # 初始化为浮点数
        total_amount = 0.0
        
        for row in data:
            # 使用 flt() 强制转换为数字，防止数据库返回字符串导致报错
            total_qty += flt(row.get("produce_qty"))
            total_amount += flt(row.get("amount"))
            
        # 在数据末尾追加一行合计
        data.append({
            "report_date": "<b>合计</b>", 
            "report_num": "",
            "work_order": "",
            "product_name": "",
            "wage_type": "",
            "rework_type": "",
            "produce_qty": total_qty,     
            "piece_rate": None,
            "duration_display": "",
            "amount": total_amount        
        })
        
    return columns, data

def get_columns():
    # === 设备检测逻辑 ===
    user_agent = frappe.request.headers.get('User-Agent', '').lower()
    is_mobile = 'mobile' in user_agent or 'android' in user_agent or 'iphone' in user_agent
    
    # 手机端：工单号 = Data (不可点)
    # 电脑端：工单号 = Link (可点)
    wo_fieldtype = "Data" if is_mobile else "Link"
    wo_options = None if is_mobile else "Work Order"

    return [
        {
            "fieldname": "report_date",
            "label": "日期",
            "fieldtype": "Data", 
            "width": 80,
            "align": "left"
        },
        {
            "fieldname": "product_name",
            "label": "产品名",
            "fieldtype": "Data",
            "width": 120
        },
        {
            "fieldname": "wage_type",
            "label": "方式",
            "fieldtype": "Data",
            "width": 50
        },
        {
            "fieldname": "rework_type",
            "label": "是否返工",
            "fieldtype": "Data",
            "width": 90
        },
        {
            "fieldname": "produce_qty",
            "label": "数",
            "fieldtype": "Int",
            "width": 50
        },
        {
            "fieldname": "piece_rate",
            "label": "价",
            "fieldtype": "Float",
            "width": 60,
            "precision": 2
        },
        {
            "fieldname": "duration_display",
            "label": "工时",
            "fieldtype": "Data",
            "width": 120
        },
        {
            "fieldname": "amount",
            "label": "金额",
            "fieldtype": "Currency",
            "width": 120
        },
        # === 报工单号 ===
        {
            "fieldname": "report_num",
            "label": "报工单号",
            "fieldtype": "Link",
            "options": "FWB Work Report",
            "width": 100
        },
        # === 工单号 (动态类型) ===
        {
            "fieldname": "work_order",
            "label": "工单号",
            "fieldtype": wo_fieldtype, 
            "options": wo_options,
            "width": 100
        }
    ]

def get_data(filters):
    user = frappe.session.user
    # 1. 权限控制
    if user == "Administrator":
        employee_condition = ""
    else:
        employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
        if not employee:
            frappe.msgprint("当前账号未关联员工档案，无法查看个人报表。")
            return []
        employee_condition = f"AND wr.employee = '{employee}'"

    conditions = get_conditions(filters)
    
    # 2. 核心 SQL 查询
    sql = f"""
        SELECT
            DATE_FORMAT(wr.created_at, '%%m-%%d') as report_date,
            
            wr.name as report_num, 
            
            wr.work_order,
            COALESCE(wo.item_name, wo.production_item) as product_name,
            wr.wage_type,
            CASE WHEN wr.rework_type = '否' THEN '' ELSE wr.rework_type END as rework_type,
            wr.valid_qty as produce_qty,
            
            /* ========== 单价优先级逻辑 ========== */
            CASE 
                /* 第1层：【返工单价】 */
                WHEN wr.rework_type = '有偿返工' AND IFNULL(wr.rework_rate, 0) > 0 
                    THEN wr.rework_rate
                
                /* 第2层：【BOM 工时费】 */
                WHEN IFNULL(bom_op.hour_rate, 0) > 0 
                    THEN bom_op.hour_rate
                
                /* 第3层：【BOM 计件单价】 */
                WHEN IFNULL(bom_op.custom_piece_rate, 0) > 0 
                    THEN bom_op.custom_piece_rate
                
                /* 第4层：【报工单 时薪】 */
                WHEN IFNULL(wr.hourly_rate, 0) > 0 
                    THEN wr.hourly_rate
                
                /* 第5层：【报工单 计件单价】 (默认保底) */
                ELSE IFNULL(wr.custom_piece_rate, 0)
            END as piece_rate,
            
            wr.duration_display,

            /* ========== 金额实时计算 (与 Employee Wage Summary 口径对齐) ==========
               原本读 wr.total_amount 会把陈旧值带出来 (例如老报工 hourly_rate=0
               但 BOM hour_rate 后来设过来), 改为按当前 BOM + 报工字段实时算. */
            CASE
                /* 计时: BOM hour_rate -> 报工 hourly_rate */
                WHEN wr.wage_type = '计时' THEN
                    (IFNULL(wr.duration, 0) / 3600.0) *
                    CASE
                        WHEN IFNULL(bom_op.hour_rate, 0) > 0 THEN bom_op.hour_rate
                        ELSE IFNULL(wr.hourly_rate, 0)
                    END

                /* 有偿返工: 报工 rework_rate */
                WHEN wr.rework_type = '有偿返工' AND IFNULL(wr.rework_rate, 0) > 0 THEN
                    IFNULL(wr.valid_qty, 0) * wr.rework_rate

                /* 普通计件 / 无偿返工: BOM custom_piece_rate -> 报工 custom_piece_rate */
                ELSE
                    IFNULL(wr.valid_qty, 0) *
                    CASE
                        WHEN IFNULL(bom_op.custom_piece_rate, 0) > 0 THEN bom_op.custom_piece_rate
                        ELSE IFNULL(wr.custom_piece_rate, 0)
                    END
            END as amount

        FROM
            `tabFWB Work Report` wr
        LEFT JOIN
            `tabWork Order` wo ON wr.work_order = wo.name
        
        LEFT JOIN
            `tabBOM Operation` bom_op 
            ON bom_op.parent = wo.bom_no 
            AND bom_op.workstation = wr.workstation
        
        WHERE
            wr.docstatus < 2
            {employee_condition}
            {conditions}
            
        ORDER BY
            wr.created_at DESC
    """
    
    data = frappe.db.sql(sql, filters, as_dict=True)
    return data

def get_conditions(filters):
    conditions = ""
    if filters.get("from_date"):
        filters["from_date"] = f"{filters.get('from_date')} 00:00:00"
        conditions += " AND wr.created_at >= %(from_date)s"
    if filters.get("to_date"):
        filters["to_date"] = f"{filters.get('to_date')} 23:59:59"
        conditions += " AND wr.created_at <= %(to_date)s"
    if filters.get("work_order"):
        conditions += " AND wr.work_order = %(work_order)s"
    if filters.get("product_name"):
        filters["product_name"] = f"%{filters.get('product_name')}%"
        conditions += " AND wo.item_name LIKE %(product_name)s"
    return conditions
