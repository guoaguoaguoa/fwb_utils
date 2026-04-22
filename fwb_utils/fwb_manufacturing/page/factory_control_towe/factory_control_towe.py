# v2025.12.10.02 - Factory Control Tower backend
# - 顶部 KPI：工单总数 / 待产盒数 / 产量 / 次品率 / 计件工资（按日期区间）
# - 物料齐套进度：按工单汇总，链接指向任意一张 MRC
# - 交期预警：未来 7 天交货的工单，显示当前工站阶段
# - 生产总览：按工站 + 工单统计报工数、次品数、次品率

from __future__ import unicode_literals

import frappe
from frappe.utils import nowdate, now_datetime, flt, cint, add_days, getdate, get_datetime


WORKSTATION_FLOW = (
    ("木工房", "木工", "木工进度"),
    ("底漆房", "底漆", "底漆进度"),
    ("面漆房", "面漆", "面漆进度"),
    ("抛光区", "抛光", "抛光进度"),
    ("装配区", "装配", "装配进度"),
    ("软包区", "软包", "软包进度"),
    ("打包区", "打包", "打包进度"),
)

WORKSTATION_LABELS = {workstation: label for workstation, label, _ in WORKSTATION_FLOW}
WORKSTATION_PANELS = {workstation: panel for workstation, _, panel in WORKSTATION_FLOW}
WORKSTATION_ORDER = {workstation: idx for idx, (workstation, _, _) in enumerate(WORKSTATION_FLOW)}


@frappe.whitelist()
def get_dashboard_data(from_date=None, to_date=None):
    """Return aggregated data for Factory Control Tower page."""

    # 默认统计最近 7 天
    if not to_date:
        to_date = nowdate()
    if not from_date:
        from_date = add_days(to_date, -6)

    from_date = str(getdate(from_date))
    to_date = str(getdate(to_date))

    kpi = _get_kpi_block(from_date, to_date)
    mrc_list = _get_mrc_progress_list()
    due_warning = _get_due_warning_list()
    ws_progress = _get_workstation_progress(from_date, to_date)
    stage_overview = _get_stage_overview(from_date, to_date)

    return {
        "kpi": kpi,
        "mrc_list": mrc_list,
        "due_warning": due_warning,
        "workstation_progress": ws_progress,
        "stage_overview": stage_overview,
    }


# ----------------------------------------------------------------------
# 顶部 KPI
# ----------------------------------------------------------------------
def _get_kpi_block(from_date, to_date):
    """Compute top-level KPI numbers.

    - work_order_total: 区间内工单总数（docstatus < 2, planned_start_date 落在区间）
    - work_order_completed: 状态 = 'Completed'
    - work_order_unfinished: total - completed
    - pending_box_qty: 区间内所有未完成工单的 qty 总和
    - completed_box_qty: 区间内所有已完成工单的 qty 总和
    - range_output_qty: 区间内 FWB Work Report.valid_qty 之和
    - range_defect_rate: 区间内 SUM(defect_qty) / SUM(qty)
    - range_wage_amount: 区间内 FWB Work Report.total_amount 之和
    """

    # 工单数量 + 盒数（按 planned_start_date 过滤）
    wo_rows = frappe.db.sql(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) AS completed_count,
            SUM(
                CASE
                    WHEN status != 'Completed' THEN IFNULL(qty, 0)
                    ELSE 0
                END
            ) AS pending_qty,
            SUM(
                CASE
                    WHEN status = 'Completed' THEN IFNULL(qty, 0)
                    ELSE 0
                END
            ) AS completed_qty
        FROM `tabWork Order`
        WHERE
            docstatus < 2
            AND planned_start_date IS NOT NULL
            AND DATE(planned_start_date) BETWEEN %(from_date)s AND %(to_date)s
        """,
        {"from_date": from_date, "to_date": to_date},
        as_dict=True,
    )

    if wo_rows:
        wo_row = wo_rows[0]
        total_wo = cint(wo_row.total or 0)
        completed_count = cint(wo_row.completed_count or 0)
        unfinished_count = total_wo - completed_count
        pending_box_qty = flt(wo_row.pending_qty or 0)
        completed_box_qty = flt(wo_row.completed_qty or 0)
    else:
        total_wo = 0
        completed_count = 0
        unfinished_count = 0
        pending_box_qty = 0.0
        completed_box_qty = 0.0

    # 产量 & 次品（FWB Work Report）
    prod_rows = frappe.db.sql(
        """
        SELECT
            SUM(IFNULL(valid_qty, 0))   AS total_valid_qty,
            SUM(IFNULL(qty, 0))         AS total_qty,
            SUM(IFNULL(defect_qty, 0))  AS total_defect_qty
        FROM `tabFWB Work Report`
        WHERE
            docstatus = 1
            AND {normal_condition}
            AND created_at >= %(from_datetime)s
            AND created_at <= %(to_datetime)s
        """.format(normal_condition=_normal_work_report_condition()),
        _get_work_report_params(from_date, to_date),
        as_dict=True,
    )

    if prod_rows:
        total_valid = flt(prod_rows[0].total_valid_qty or 0)
        total_qty = flt(prod_rows[0].total_qty or 0)
        total_defect = flt(prod_rows[0].total_defect_qty or 0)
    else:
        total_valid = 0.0
        total_qty = 0.0
        total_defect = 0.0

    if total_qty > 0:
        defect_rate = (total_defect * 100.0) / total_qty
    else:
        defect_rate = 0.0

    # 工资合计：直接统计 FWB Work Report.total_amount（计件 + 计时）
    wage_rows = frappe.db.sql(
        """
        SELECT
            SUM(IFNULL(total_amount, 0)) AS total_amount
        FROM `tabFWB Work Report`
        WHERE
            docstatus = 1
            AND {normal_condition}
            AND created_at >= %(from_datetime)s
            AND created_at <= %(to_datetime)s
        """.format(normal_condition=_normal_work_report_condition()),
        _get_work_report_params(from_date, to_date),
        as_dict=True,
    )

    wage_total = flt(wage_rows[0].total_amount or 0) if wage_rows else 0.0

    return {
        "work_order_total": total_wo,
        "work_order_completed": completed_count,
        "work_order_unfinished": unfinished_count,
        "pending_box_qty": pending_box_qty,
        "completed_box_qty": completed_box_qty,
        "range_output_qty": total_valid,
        "range_defect_rate": defect_rate,
        "range_wage_amount": wage_total,
        "from_date": from_date,
        "to_date": to_date,
    }


# ----------------------------------------------------------------------
# 物料齐套进度（按工单）
# ----------------------------------------------------------------------
def _get_mrc_progress_list():
    """Return material readiness progress per Work Order."""

    rows = frappe.db.sql(
        """
        SELECT
            m.work_order,
            MAX(m.product_name) AS product_name,
            MAX(m.product_qty) AS product_qty,
            MAX(m.name)        AS any_mrc_name,
            SUM(1) AS total_rows,
            SUM(CASE WHEN COALESCE(i.is_confirmed, '') = '齐全' THEN 1 ELSE 0 END) AS ok_rows
        FROM `tabMaterial Readiness Check` m
        INNER JOIN `tabMaterial Readiness Check Item` i
            ON i.parent = m.name
        WHERE
            m.docstatus < 2
        GROUP BY
            m.work_order
        HAVING
            m.work_order IS NOT NULL
        ORDER BY
            m.work_order DESC
        LIMIT 50
        """,
        as_dict=True,
    )

    result = []
    for r in rows:
        total_rows = cint(r.total_rows or 0)
        ok_rows = cint(r.ok_rows or 0)

        if total_rows > 0:
            percent = (ok_rows * 100.0) / float(total_rows)
        else:
            percent = 0.0

        if percent >= 99.9:
            status = "全部齐套"
        elif percent <= 0.1:
            status = "尚未开始"
        else:
            status = "部分齐套"

        mrc_url = ""
        if r.any_mrc_name:
            # 注意这里用 URL，而不是 link_to_form 的 HTML
            mrc_url = frappe.utils.get_url_to_form(
                "Material Readiness Check", r.any_mrc_name
            )

        result.append(
            {
                "work_order": r.work_order,
                "product_name": r.product_name or "",
                "product_qty": flt(r.product_qty or 0),
                "total_rows": total_rows,
                "ok_rows": ok_rows,
                "progress_percent": percent,
                "status": status,
                "url": mrc_url,
            }
        )

    return result


# ----------------------------------------------------------------------
# 交期预警（未来 7 天）
# ----------------------------------------------------------------------
def _get_due_warning_list():
    """Return Work Orders with expected_delivery_date in next 7 days."""

    today = nowdate()
    end_date = add_days(today, 7)

    wo_rows = frappe.db.sql(
        """
        SELECT
            name,
            item_name,
            qty,
            expected_delivery_date,
            planned_start_date
        FROM `tabWork Order`
        WHERE
            docstatus < 2
            AND expected_delivery_date IS NOT NULL
            AND expected_delivery_date BETWEEN %(today)s AND %(end_date)s
        ORDER BY
            expected_delivery_date ASC, name ASC
        """,
        {"today": today, "end_date": end_date},
        as_dict=True,
    )

    result = []
    if not wo_rows:
        return result

    work_orders = [w.name for w in wo_rows]

    # 找到每个工单已报工的工站
    ws_rows = frappe.db.sql(
        """
        SELECT
            work_order,
            workstation
        FROM `tabFWB Work Report`
        WHERE
            docstatus = 1
            AND work_order IN %(wos)s
            AND {normal_condition}
        GROUP BY
            work_order, workstation
        """.format(normal_condition=_normal_work_report_condition()),
        {"wos": tuple(work_orders)},
        as_dict=True,
    )

    # 工站优先级：数字越大代表越靠后
    latest_stage = {}
    for r in ws_rows:
        ws = r.workstation
        if ws not in WORKSTATION_ORDER:
            continue
        prio = WORKSTATION_ORDER[ws]
        current = latest_stage.get(r.work_order)
        if (not current) or prio > current["prio"]:
            latest_stage[r.work_order] = {
                "prio": prio,
                "label": WORKSTATION_LABELS.get(ws, ws),
            }

    for w in wo_rows:
        stage = latest_stage.get(w.name)
        stage_text = stage["label"] if stage else "未报工"

        result.append(
            {
                "work_order": w.name,
                "item_name": w.item_name or "",
                "qty": flt(w.qty or 0),
                "expected_delivery_date": str(w.expected_delivery_date),
                "order_date": str(getdate(w.planned_start_date))
                if w.planned_start_date
                else "",
                "stage": stage_text,
                "url": frappe.utils.get_url_to_form("Work Order", w.name),
            }
        )

    return result


# ----------------------------------------------------------------------
# 各工站生产总览
# ----------------------------------------------------------------------
def _get_workstation_progress(from_date, to_date):
    """Summarize production and defects per workstation label."""

    params = _get_work_report_params(from_date, to_date)
    period_rows = frappe.db.sql(
        """
        SELECT
            w.work_order,
            w.workstation,
            SUM(IFNULL(w.qty, 0))        AS total_qty,
            SUM(IFNULL(w.valid_qty, 0))  AS total_valid_qty,
            SUM(IFNULL(w.defect_qty, 0)) AS total_defect_qty
        FROM `tabFWB Work Report` w
        WHERE
            w.docstatus = 1
            AND {normal_condition}
            AND w.created_at >= %(from_datetime)s
            AND w.created_at <= %(to_datetime)s
        GROUP BY
            w.work_order, w.workstation
        """.format(normal_condition=_normal_work_report_condition("w")),
        params,
        as_dict=True,
    )

    if not period_rows:
        return {}

    work_orders = {p.work_order for p in period_rows if p.work_order}
    cumulative_rows = frappe.db.sql(
        """
        SELECT
            w_cumulative.work_order,
            w_cumulative.workstation,
            SUM(IFNULL(w_cumulative.valid_qty, 0)) AS cumulative_valid_qty
        FROM `tabFWB Work Report` w_cumulative
        WHERE
            w_cumulative.docstatus = 1
            AND {normal_condition}
            AND w_cumulative.created_at <= %(to_datetime)s
            AND w_cumulative.work_order IN %(work_orders)s
        GROUP BY
            w_cumulative.work_order, w_cumulative.workstation
        """.format(normal_condition=_normal_work_report_condition("w_cumulative")),
        dict(params, work_orders=tuple(work_orders)),
        as_dict=True,
    )

    period_map = {
        (row.work_order, row.workstation): row
        for row in period_rows
        if row.work_order and row.workstation
    }
    cumulative_map = {
        (row.work_order, row.workstation): flt(row.cumulative_valid_qty or 0)
        for row in cumulative_rows
        if row.work_order and row.workstation
    }

    # 取相关工单信息
    wo_info_map = {}
    if work_orders:
        wo_info = frappe.db.sql(
            """
            SELECT
                name,
                item_name,
                qty,
                planned_start_date
            FROM `tabWork Order`
            WHERE name IN %(names)s
            """,
            {"names": tuple(work_orders)},
            as_dict=True,
        )
        for w in wo_info:
            wo_info_map[w.name] = w

    result = {}
    for _, _, label in WORKSTATION_FLOW:
        result[label] = []

    row_keys = set(period_map) | set(cumulative_map)
    for work_order, ws_name in row_keys:
        if ws_name not in WORKSTATION_PANELS:
            continue

        wo = wo_info_map.get(work_order)
        if not wo:
            continue

        period_row = period_map.get((work_order, ws_name)) or frappe._dict()
        total_qty = flt(period_row.get("total_qty") or 0)          # Σqty
        total_valid = flt(period_row.get("total_valid_qty") or 0)  # 本期 Σvalid_qty
        cumulative_valid = flt(cumulative_map.get((work_order, ws_name)) or 0)
        defect_qty = flt(period_row.get("total_defect_qty") or 0)  # 本期 Σdefect_qty

        if total_qty > 0:
            defect_rate = (defect_qty * 100.0) / total_qty
        else:
            defect_rate = 0.0

        row = {
            "work_order": work_order,
            "order_date": str(getdate(wo.planned_start_date))
            if wo.planned_start_date
            else "",
            "product_name": wo.item_name or "",
            "work_order_qty": flt(wo.qty or 0),
            "reported_qty": total_valid,
            "cumulative_reported_qty": cumulative_valid,
            "defect_qty": defect_qty,
            "defect_rate": defect_rate,
            "workstation": ws_name,  # 交给前端使用 frappe.set_route 过滤
        }

        label = WORKSTATION_PANELS[ws_name]
        result[label].append(row)

    # 每个工站按工单日期倒序，限制最多 30 行
    for label, rows in result.items():
        rows.sort(key=lambda x: x.get("order_date") or "", reverse=True)
        result[label] = rows[:30]

    return result


def _get_stage_overview(from_date, to_date):
    params = _get_work_report_params(from_date, to_date)
    period_work_orders = frappe.db.sql(
        """
        SELECT DISTINCT
            w.work_order
        FROM `tabFWB Work Report` w
        WHERE
            w.docstatus = 1
            AND {normal_condition}
            AND w.created_at >= %(from_datetime)s
            AND w.created_at <= %(to_datetime)s
            AND IFNULL(w.work_order, '') != ''
        """.format(normal_condition=_normal_work_report_condition("w")),
        params,
        as_dict=True,
    )
    work_order_names = {row.work_order for row in period_work_orders if row.work_order}
    if not work_order_names:
        return []

    stage_rows = frappe.db.sql(
        """
        SELECT
            w.work_order,
            w.workstation,
            SUM(IFNULL(w.valid_qty, 0)) AS total_valid_qty,
            MIN(w.created_at) AS first_created_at,
            MAX(w.created_at) AS last_created_at
        FROM `tabFWB Work Report` w
        WHERE
            w.docstatus = 1
            AND {normal_condition}
            AND w.created_at <= %(to_datetime)s
            AND w.work_order IN %(work_orders)s
        GROUP BY
            w.work_order, w.workstation
        """.format(normal_condition=_normal_work_report_condition("w")),
        dict(params, work_orders=tuple(work_order_names)),
        as_dict=True,
    )

    wo_rows = frappe.db.sql(
        """
        SELECT
            name,
            item_name,
            qty,
            planned_start_date
        FROM `tabWork Order`
        WHERE name IN %(names)s
        """,
        {"names": tuple(work_order_names)},
        as_dict=True,
    )
    work_orders = {row.name: row for row in wo_rows}

    return _build_stage_overview(
        work_orders,
        stage_rows,
        _get_stage_end_datetime(to_date),
    )


def _build_stage_overview(work_orders, stage_rows, end_datetime):
    by_work_order = {}
    for row in stage_rows:
        if row.work_order not in work_orders or row.workstation not in WORKSTATION_ORDER:
            continue

        by_work_order.setdefault(row.work_order, {})[row.workstation] = {
            "valid_qty": flt(row.total_valid_qty or 0),
            "first_created_at": _coerce_datetime(row.first_created_at),
            "last_created_at": _coerce_datetime(row.last_created_at),
        }

    result = []
    for work_order_name, wo in work_orders.items():
        station_map = by_work_order.get(work_order_name, {})
        qty = flt(wo.qty or 0)
        reported_stations = [
            ws for ws, _, _ in WORKSTATION_FLOW
            if flt(station_map.get(ws, {}).get("valid_qty") or 0) > 0
        ]

        if not reported_stations:
            current_stage = "未报工"
            flow_wait = "未开工"
            overall_tip = "未报工"
        else:
            current_ws = max(reported_stations, key=lambda ws: WORKSTATION_ORDER[ws])
            current_stage = WORKSTATION_LABELS[current_ws]
            partial_flow = _has_partial_flow(station_map, qty)
            flow_wait = _get_flow_wait_label(station_map, qty, end_datetime)

            current_valid = flt(station_map.get(current_ws, {}).get("valid_qty") or 0)
            if partial_flow:
                overall_tip = "部分流转"
            elif current_ws == WORKSTATION_FLOW[-1][0] and qty > 0 and current_valid >= qty:
                overall_tip = "已到最后工序"
            elif qty > 0 and current_valid >= qty:
                overall_tip = f"{current_stage}已完成"
            else:
                overall_tip = f"{current_stage}进行中"

        result.append(
            {
                "work_order": work_order_name,
                "work_order_url": frappe.utils.get_url_to_form("Work Order", work_order_name),
                "product_name": wo.item_name or "",
                "work_order_qty": qty,
                "current_stage": current_stage,
                "flow_wait": flow_wait,
                "overall_tip": overall_tip,
                "order_date": str(getdate(wo.planned_start_date))
                if getattr(wo, "planned_start_date", None)
                else "",
            }
        )

    result.sort(key=lambda row: (row.get("order_date") or "", row.get("work_order") or ""), reverse=True)
    return result[:50]


def _has_partial_flow(station_map, work_order_qty):
    if work_order_qty <= 0:
        return False

    for index, (ws, _, _) in enumerate(WORKSTATION_FLOW):
        valid_qty = flt(station_map.get(ws, {}).get("valid_qty") or 0)
        if valid_qty <= 0 or index == 0:
            continue

        previous_incomplete = any(
            flt(station_map.get(prev_ws, {}).get("valid_qty") or 0) < work_order_qty
            for prev_ws, _, _ in WORKSTATION_FLOW[:index]
        )
        if previous_incomplete:
            return True

    return False


def _get_flow_wait_label(station_map, work_order_qty, end_datetime):
    if work_order_qty <= 0:
        return "-"

    last_completed_index = None
    for index, (ws, _, _) in enumerate(WORKSTATION_FLOW):
        valid_qty = flt(station_map.get(ws, {}).get("valid_qty") or 0)
        if valid_qty >= work_order_qty:
            last_completed_index = index

    if last_completed_index is None:
        return "前道未完成"

    next_index = last_completed_index + 1
    if next_index >= len(WORKSTATION_FLOW):
        return "已完成"

    completed_ws = WORKSTATION_FLOW[last_completed_index][0]
    next_ws = WORKSTATION_FLOW[next_index][0]
    completed_at = station_map.get(completed_ws, {}).get("last_created_at")
    next_started_at = station_map.get(next_ws, {}).get("first_created_at")
    wait_until = next_started_at or end_datetime
    if not completed_at or not wait_until:
        return "-"

    return _format_duration(wait_until - completed_at)


def _format_duration(delta):
    seconds = max(cint(delta.total_seconds()), 0)
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60

    if days:
        return f"{days}天{hours}小时" if hours else f"{days}天"
    if hours:
        return f"{hours}小时{minutes}分钟" if minutes else f"{hours}小时"
    if minutes:
        return f"{minutes}分钟"
    return "刚刚"


def _get_work_report_params(from_date, to_date):
    from_date = str(getdate(from_date))
    to_date = str(getdate(to_date))
    return {
        "from_date": from_date,
        "to_date": to_date,
        "from_datetime": f"{from_date} 00:00:00",
        "to_datetime": f"{to_date} 23:59:59",
    }


def _normal_work_report_condition(alias=None):
    fieldname = f"{alias}.rework_type" if alias else "rework_type"
    return f"({fieldname} = '否' OR {fieldname} IS NULL OR {fieldname} = '')"


def _get_stage_end_datetime(to_date):
    to_date = str(getdate(to_date))
    if to_date == nowdate():
        return now_datetime()
    return get_datetime(f"{to_date} 23:59:59")


def _coerce_datetime(value):
    if not value:
        return None
    return get_datetime(value)
