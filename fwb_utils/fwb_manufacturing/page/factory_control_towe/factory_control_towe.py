# v2025.12.10.02 - Factory Control Tower backend
# - 顶部 KPI：工单总数 / 待产盒数 / 产量 / 次品率 / 计件工资（按日期区间）
# - 物料齐套进度：按工单汇总，链接指向任意一张 MRC
# - 交期预警：未来 7 天交货的工单，显示当前工站阶段
# - 生产总览：按工站 + 工单统计报工数、次品数、次品率

from __future__ import unicode_literals

import frappe
from frappe.utils import nowdate, flt, cint, add_days, getdate


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

    return {
        "kpi": kpi,
        "mrc_list": mrc_list,
        "due_warning": due_warning,
        "workstation_progress": ws_progress,
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
            AND DATE(created_at) BETWEEN %(from_date)s AND %(to_date)s
        """,
        {"from_date": from_date, "to_date": to_date},
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
            AND DATE(created_at) BETWEEN %(from_date)s AND %(to_date)s
        """,
        {"from_date": from_date, "to_date": to_date},
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
        GROUP BY
            work_order, workstation
        """,
        {"wos": tuple(work_orders)},
        as_dict=True,
    )

    # 工站优先级：数字越大代表越靠后
    stage_priority = {
        "木工房": 1,
        "底漆房": 2,
        "面漆房": 3,
        "抛光区": 4,
        "装配区": 5,
        "软包区": 6,
        "打包区": 7,
    }
    stage_label = {
        "木工房": "木工",
        "底漆房": "底漆",
        "面漆房": "面漆",
        "抛光区": "抛光",
        "装配区": "装配",
        "软包区": "软包",
        "打包区": "打包",
    }

    latest_stage = {}
    for r in ws_rows:
        ws = r.workstation
        if ws not in stage_priority:
            continue
        prio = stage_priority[ws]
        current = latest_stage.get(r.work_order)
        if (not current) or prio > current["prio"]:
            latest_stage[r.work_order] = {
                "prio": prio,
                "label": stage_label.get(ws, ws),
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

    prod_rows = frappe.db.sql(
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
            AND DATE(w.created_at) BETWEEN %(from_date)s AND %(to_date)s
        GROUP BY
            w.work_order, w.workstation
        """,
        {"from_date": from_date, "to_date": to_date},
        as_dict=True,
    )

    if not prod_rows:
        return {}

    # 取相关工单信息
    work_orders = {p.work_order for p in prod_rows if p.work_order}
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

    # 工站到面板标题的映射
    ws_targets = {
        "木工房": "木工进度",
        "底漆房": "底漆进度",
        "面漆房": "面漆进度",
        "抛光区": "抛光进度",
        "装配区": "装配进度",
        "软包区": "软包进度",
        "打包区": "打包进度",
    }

    result = {}
    for ws_name, label in ws_targets.items():
        result[label] = []

    for p in prod_rows:
        ws_name = p.workstation
        if ws_name not in ws_targets:
            continue

        wo = wo_info_map.get(p.work_order)
        if not wo:
            continue

        total_qty = flt(p.total_qty or 0)          # Σqty
        total_valid = flt(p.total_valid_qty or 0)  # Σvalid_qty = 已报工数
        defect_qty = flt(p.total_defect_qty or 0)  # Σdefect_qty

        if total_qty > 0:
            defect_rate = (defect_qty * 100.0) / total_qty
        else:
            defect_rate = 0.0

        row = {
            "work_order": p.work_order,
            "order_date": str(getdate(wo.planned_start_date))
            if wo.planned_start_date
            else "",
            "product_name": wo.item_name or "",
            "work_order_qty": flt(wo.qty or 0),
            "reported_qty": total_valid,
            "defect_qty": defect_qty,
            "defect_rate": defect_rate,
            "workstation": ws_name,  # 交给前端使用 frappe.set_route 过滤
        }

        label = ws_targets[ws_name]
        result[label].append(row)

    # 每个工站按工单日期倒序，限制最多 30 行
    for label, rows in result.items():
        rows.sort(key=lambda x: x.get("order_date") or "", reverse=True)
        result[label] = rows[:30]

    return result
