# v2026.07.23.01 - 计件工资结算视图：向工资单口径靠拢
# - 行范围/罚款/手工行/单价/计时判据(duration_seconds>0) 全部复用工资单结算数据，
#   不再由本报表自行写 SQL CASE，杜绝「报表金额 ≠ 工人实发计件额」的漂移。
# - 有工资单（期间与工资单起止完全一致）读工资单 custom_piece_wage_details 明细，
#   含手工扣款/补贴行；否则按结算口径 `_collect_aggregated_rows` 实时预览。
# - 罚款行/负额红、计时行蓝，配色口径与 public/js/salary_slip.js 一致。

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, getdate

from fwb_utils.fwb_manufacturing.doctype.employee_wage_sheet.employee_wage_sheet import (
    _collect_aggregated_rows,
    _format_duration_display,
)

PIECE_WAGE_STRUCTURE = "无底薪计件工结构"
PIECE_WAGE_DETAIL_FIELD = "custom_piece_wage_details"

# 与 public/js/salary_slip.js 一致的整行文字配色
COLOR_RED = "#c62828"   # 罚款行 / 该行金额为负（扣款）
COLOR_BLUE = "#0066cc"  # 计时行


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

    # === 合计行（金额已按结算口径带符号：罚款/扣款为负，合计即净计件额）===
    if data:
        total_qty = 0.0
        total_amount = 0.0
        for row in data:
            total_qty += flt(row.get("produce_qty"))
            total_amount += flt(row.get("amount"))

        data.append({
            "report_date": "<b>合计</b>",
            "product_name": "",
            "wage_type": "",
            "remarks": "",
            "produce_qty": total_qty,
            "piece_rate": None,
            "duration_display": "",
            "amount": total_amount,
            "report_num": "",
            "work_order": "",
            "_style": "",
        })

    return columns, data


def get_columns():
    # === 设备检测：手机端工单号不可点，电脑端可点 ===
    user_agent = frappe.request.headers.get('User-Agent', '').lower() if frappe.request else ''
    is_mobile = 'mobile' in user_agent or 'android' in user_agent or 'iphone' in user_agent

    wo_fieldtype = "Data" if is_mobile else "Link"
    wo_options = None if is_mobile else "Work Order"

    return [
        {"fieldname": "report_date", "label": "日期", "fieldtype": "Data", "width": 80, "align": "left"},
        {"fieldname": "product_name", "label": "产品名", "fieldtype": "Data", "width": 120},
        {"fieldname": "wage_type", "label": "方式", "fieldtype": "Data", "width": 70},
        {"fieldname": "produce_qty", "label": "数", "fieldtype": "Int", "width": 50},
        {"fieldname": "piece_rate", "label": "单价", "fieldtype": "Float", "width": 60, "precision": 2},
        {"fieldname": "duration_display", "label": "工时", "fieldtype": "Data", "width": 110},
        {"fieldname": "amount", "label": "金额", "fieldtype": "Currency", "width": 110},
        # 备注移到倒数第三列；内容常被列宽截断，前端 formatter 让有备注的行可点击弹出完整内容。
        {"fieldname": "remarks", "label": "备注", "fieldtype": "Data", "width": 130},
        {"fieldname": "report_num", "label": "报工单号", "fieldtype": "Link", "options": "FWB Work Report", "width": 100},
        {"fieldname": "work_order", "label": "工单号", "fieldtype": wo_fieldtype, "options": wo_options, "width": 100},
    ]


def get_data(filters):
    filters = frappe._dict(filters or {})
    if not filters.get("from_date") or not filters.get("to_date"):
        return []

    from_date = getdate(filters.get("from_date"))
    to_date = getdate(filters.get("to_date"))

    user = get_current_user()
    if has_manager_view_access(user):
        employees = _resolve_target_employees(filters, from_date, to_date)
    else:
        # 工人：强制只看本人，忽略任何 employee_name 过滤，防止越权看他人工资。
        employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
        if not employee:
            frappe.msgprint(_("当前账号未关联员工档案，无法查看个人报表。"))
            return []
        employees = [employee]

    rows = []
    for employee in employees:
        rows.extend(_build_employee_rows(employee, from_date, to_date))

    rows = _apply_row_filters(rows, filters)
    _fill_report_dates(rows)
    rows.sort(key=lambda r: (r.get("_sort_ts") or ""), reverse=True)
    return rows


def _build_employee_rows(employee, from_date, to_date):
    """一个员工在该期间的计件结算行：有对应工资单读工资单，否则实时预览。"""
    slip = _find_exact_period_piece_wage_slip(employee, from_date, to_date)
    if slip:
        return [_normalize_slip_row(r) for r in _read_slip_detail_rows(slip)]

    raw_rows = _collect_aggregated_rows(employee, str(from_date), str(to_date))
    return [_normalize_preview_row(r) for r in raw_rows]


def _find_exact_period_piece_wage_slip(employee, from_date, to_date):
    """仅当报表期间与工资单起止完全一致时才读工资单，避免子区间被整月工资单放大。"""
    slips = frappe.get_all(
        "Salary Slip",
        filters={
            "employee": employee,
            "salary_structure": PIECE_WAGE_STRUCTURE,
            "start_date": from_date,
            "end_date": to_date,
            "docstatus": ["<", 2],
        },
        fields=["name"],
        order_by="docstatus desc, modified desc",
        limit=1,
    )
    return slips[0].name if slips else None


def _read_slip_detail_rows(slip_name):
    """读工资单计件明细子表（含手工扣款/补贴行、罚款行）。"""
    return frappe.get_all(
        "Employee Wage Sheet Detail",
        filters={
            "parent": slip_name,
            "parenttype": "Salary Slip",
            "parentfield": PIECE_WAGE_DETAIL_FIELD,
        },
        fields=[
            "source_work_report", "work_order", "product_name", "workstation",
            "qty", "rate", "duration_seconds", "duration_display",
            "amount", "is_penalty", "remarks",
        ],
        order_by="idx asc",
    )


def _normalize_slip_row(raw):
    is_penalty = cint(raw.get("is_penalty"))
    duration = cint(raw.get("duration_seconds"))
    amount = _display_amount(is_penalty, raw.get("amount"))
    source_wr = raw.get("source_work_report") or ""
    return frappe._dict({
        "report_date": "",  # 稍后按报工单 created_at 回填
        "product_name": raw.get("product_name") or "",
        "wage_type": _wage_type_label(is_penalty, source_wr, duration),
        "remarks": raw.get("remarks") or "",
        "produce_qty": flt(raw.get("qty")),
        "piece_rate": flt(raw.get("rate")),
        "duration_display": raw.get("duration_display") or "",
        "amount": amount,
        "report_num": source_wr,
        "work_order": raw.get("work_order") or "",
        "workstation": raw.get("workstation") or "",
        "_style": _row_style(is_penalty, amount, duration),
        "_source_wr": source_wr,
    })


def _normalize_preview_row(raw):
    is_penalty = cint(raw.get("is_penalty"))
    duration = cint(raw.get("total_duration_seconds"))
    qty = flt(raw.get("total_valid_qty"))
    rate = flt(raw.get("rate"))
    amount = _display_amount(is_penalty, _preview_row_amount(qty, duration, rate))
    source_wr = raw.get("work_report") or ""
    return frappe._dict({
        "report_date": "",
        "product_name": raw.get("product_name") or "",
        "wage_type": _wage_type_label(is_penalty, source_wr, duration),
        "remarks": raw.get("remarks") or "",
        "produce_qty": qty,
        "piece_rate": rate,
        "duration_display": _format_duration_display(duration),
        "amount": amount,
        "report_num": source_wr,
        "work_order": raw.get("work_order") or "",
        "workstation": raw.get("workstation") or "",
        "_style": _row_style(is_penalty, amount, duration),
        "_source_wr": source_wr,
    })


def _preview_row_amount(qty, duration_seconds, rate):
    """与工资单 _calculate_row_amount 一致：duration_seconds>0 走计时，否则计件。"""
    if cint(duration_seconds) > 0:
        return flt(duration_seconds) / 3600.0 * flt(rate)
    return flt(qty) * flt(rate)


def _display_amount(is_penalty, amount):
    """罚款行按扣款展示为负数，使合计=净计件额、且负额红字口径统一。"""
    amt = flt(amount)
    if cint(is_penalty):
        return -abs(amt)
    return amt


def _wage_type_label(is_penalty, source_work_report, duration_seconds):
    if cint(is_penalty):
        return "返工罚款"
    if not source_work_report:
        return "手工"
    return "计时" if cint(duration_seconds) > 0 else "计件"


def _row_style(is_penalty, amount, duration_seconds):
    """配色口径同 salary_slip.js：罚款/负额红（红优先），计时蓝。"""
    if cint(is_penalty) or flt(amount) < 0:
        return "red"
    if cint(duration_seconds) > 0:
        return "blue"
    return ""


def _apply_row_filters(rows, filters):
    product = (filters.get("product_name") or "").strip()
    work_order = (filters.get("work_order") or "").strip()
    workstation = (filters.get("workstation") or "").strip()

    if not (product or work_order or workstation):
        return rows

    out = []
    for r in rows:
        if product and product not in (r.get("product_name") or ""):
            continue
        if work_order and (r.get("work_order") or "") != work_order:
            continue
        if workstation and (r.get("workstation") or "") != workstation:
            continue
        out.append(r)
    return out


def _resolve_target_employees(filters, from_date, to_date):
    """管理视角的员工集合：按结算口径(docstatus=1)在期间内有报工的员工。

    员工姓名过滤与 employee_wage_summary 口径一致——ID 或姓名都能搜（去除漂移 A）。
    """
    keyword = (filters.get("employee_name") or "").strip()
    params = {
        "from_date": f"{from_date} 00:00:00",
        "to_date": f"{to_date} 23:59:59",
    }
    where = [
        "wr.docstatus = 1",
        "wr.created_at >= %(from_date)s",
        "wr.created_at <= %(to_date)s",
        "wr.employee IS NOT NULL",
        "wr.employee != ''",
    ]
    if keyword:
        params["kw"] = f"%{keyword}%"
        where.append("(wr.employee_name_display LIKE %(kw)s OR wr.employee LIKE %(kw)s)")

    sql = f"""
        SELECT DISTINCT wr.employee
        FROM `tabFWB Work Report` wr
        WHERE {" AND ".join(where)}
    """
    return [row[0] for row in frappe.db.sql(sql, params)]


def _fill_report_dates(rows):
    """按报工单 created_at 回填日期列并生成排序时间戳；手工行无报工单则留空。"""
    wr_names = tuple({r.get("_source_wr") for r in rows if r.get("_source_wr")})
    date_map = {}
    if wr_names:
        res = frappe.db.sql(
            "SELECT name, created_at FROM `tabFWB Work Report` WHERE name IN %(names)s",
            {"names": wr_names},
        )
        date_map = {name: ts for name, ts in res}

    for r in rows:
        ts = date_map.get(r.get("_source_wr"))
        if ts:
            dt = get_datetime(ts)
            r["report_date"] = dt.strftime("%m-%d")
            r["_sort_ts"] = dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            r["report_date"] = r.get("report_date") or ""
            r["_sort_ts"] = r.get("_sort_ts") or ""


def has_manager_view_access(user=None):
    user = user or get_current_user()
    if user == "Administrator":
        return True

    roles = set(frappe.get_roles(user))
    return bool(roles.intersection(MANAGER_VIEW_ROLES))


def get_current_user():
    session = getattr(frappe.local, "session", None)
    if getattr(session, "user", None):
        return session.user

    fallback_session = getattr(frappe, "session", None)
    return getattr(fallback_session, "user", None) or "Guest"
