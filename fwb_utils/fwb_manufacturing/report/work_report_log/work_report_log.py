# v2026.05.18.01 - 工人/管理双视图报工记录
# - valid_qty / 金额 改用集中 effective_qty_sql 口径 (与工资表/各报表统一)

import frappe
from frappe import _
from frappe.utils import flt

from fwb_utils.fwb_manufacturing.doctype.fwb_work_report.fwb_work_report import (
    effective_qty_sql,
)


MANAGER_VIEW_ROLES = (
	"HR Manager",
	"Manufacturing Manager",
	"Quality Manager",
	"Stock Manager",
	"Sales Master Manager",
	"Purchase Master Manager",
)

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
    filters = frappe._dict(filters or {})
    where_clauses = ["wr.docstatus < 2"]

    employee_scope = get_employee_scope_condition()
    if employee_scope is None:
        return []

    scope_condition, scope_params = employee_scope
    if scope_condition:
        where_clauses.append(scope_condition)

    conditions, condition_params = get_conditions(filters)
    where_clauses.extend(conditions)
    params = {}
    params.update(scope_params)
    params.update(condition_params)
    where_sql = " AND ".join(where_clauses)

    # 统一有效结算数量口径 (与 Employee Wage Sheet / 其它报表共用同一函数)
    eff_qty = effective_qty_sql("wr")

    # 2. 核心 SQL 查询
    sql = f"""
        SELECT
            DATE_FORMAT(wr.created_at, '%%m-%%d') as report_date,

            wr.name as report_num,

            wr.work_order,
            COALESCE(wo.item_name, wo.production_item) as product_name,
            wr.wage_type,
            CASE WHEN wr.rework_type = '否' THEN '' ELSE wr.rework_type END as rework_type,
            {eff_qty} as produce_qty,
            
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
                    {eff_qty} * wr.rework_rate

                /* 普通计件 / 无偿返工: BOM custom_piece_rate -> 报工 custom_piece_rate */
                ELSE
                    {eff_qty} *
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
            {where_sql}
            
        ORDER BY
            wr.created_at DESC
    """
    
    data = frappe.db.sql(sql, params, as_dict=True)
    return data

def get_conditions(filters):
    filters = frappe._dict(filters or {})
    conditions = []
    params = {}

    if filters.get("from_date"):
        params["from_date"] = f"{filters.get('from_date')} 00:00:00"
        conditions.append("wr.created_at >= %(from_date)s")
    if filters.get("to_date"):
        params["to_date"] = f"{filters.get('to_date')} 23:59:59"
        conditions.append("wr.created_at <= %(to_date)s")
    if filters.get("work_order"):
        params["work_order"] = filters.get("work_order")
        conditions.append("wr.work_order = %(work_order)s")

    product_name = (filters.get("product_name") or "").strip()
    if product_name:
        params["product_name"] = f"%{product_name}%"
        conditions.append("wo.item_name LIKE %(product_name)s")

    employee_name = (filters.get("employee_name") or "").strip()
    if employee_name:
        params["employee_name"] = f"%{employee_name}%"
        conditions.append(
            "COALESCE(NULLIF(wr.employee_name_display, ''), NULLIF(wr.employee_name, ''), wr.employee, '') LIKE %(employee_name)s"
        )

    if filters.get("workstation"):
        params["workstation"] = filters.get("workstation")
        conditions.append("wr.workstation = %(workstation)s")

    return conditions, params


def has_manager_view_access(user=None):
    user = user or get_current_user()
    if user == "Administrator":
        return True

    roles = set(frappe.get_roles(user))
    return bool(roles.intersection(MANAGER_VIEW_ROLES))


def get_employee_scope_condition(user=None):
    user = user or get_current_user()
    if has_manager_view_access(user):
        return "", {}

    employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
    if not employee:
        frappe.msgprint(_("当前账号未关联员工档案，无法查看个人报表。"))
        return None

    return "wr.employee = %(scope_employee)s", {"scope_employee": employee}


def get_current_user():
    session = getattr(frappe.local, "session", None)
    if getattr(session, "user", None):
        return session.user

    fallback_session = getattr(frappe, "session", None)
    return getattr(fallback_session, "user", None) or "Guest"
