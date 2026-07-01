# Copyright (c) 2025, WenZhou Furui Handicraft Co.,Ltd. and contributors
# For license information, please see license.txt
import frappe
from frappe.model.document import Document
from frappe.utils import flt

# 8 个生产工位（工序）。报工身份识别、扫码足量提醒、员工过滤共用这一份清单。
# 注意：扫码 Client Script (fixtures/client_script.json) 里的 prod_stations /
# auto_prod_stations 两个数组必须与此常量保持一致，
# 由 tests/test_workstation_constant_sync.py 断言防止静默漂移。
PRODUCTION_WORKSTATIONS = ("木工房", "裱纸区", "贴皮区", "底漆房", "面漆房", "装配区", "抛光区", "软包区")


class FWBWorkReport(Document):
    pass


@frappe.whitelist()
def get_bom_hour_rate(work_order=None, workstation=None):
    """
    Server-side lookup for BOM Operation.hour_rate used by worker-side FWB Work Report.

    The browser should not read BOM Operation directly because shop-floor users
    usually don't have read permission on that child table.
    """
    return _get_bom_hour_rate_info(work_order, workstation)


def calculate_effective_qty(qty, defect_qty=0, recovered_qty=0, total_quality_inspected=0):
    """Return settlement qty using inspected qty as base once QC exists."""
    inspected_qty = flt(total_quality_inspected or 0)
    base_qty = inspected_qty if inspected_qty > 0 else flt(qty or 0)
    return base_qty - flt(defect_qty or 0) + flt(recovered_qty or 0)


def get_total_quality_inspected(from_work_report, excluded_rework_record=None):
    """Read the submitted QC total stored on Rework Record."""
    if not from_work_report:
        return 0.0

    params = [from_work_report]
    excluded_sql = ""
    if excluded_rework_record:
        excluded_sql = " AND name != %s"
        params.append(excluded_rework_record)

    total_quality_inspected = (
        frappe.db.sql(
            f"""
            SELECT MAX(IFNULL(total_quality_inspected, 0))
            FROM `tabRework Record`
            WHERE from_work_report = %s
              AND docstatus = 1
              {excluded_sql}
            """,
            tuple(params),
        )[0][0]
        or 0
    )
    return flt(total_quality_inspected)


def effective_qty_sql(alias="wr"):
    """
    Return a SQL scalar expression (string) for the *effective settlement qty*
    of one FWB Work Report row, kept formula-equivalent to
    ``calculate_effective_qty``.

    Rule (single source of truth, shared by all reports + wage sheet):
      base = MAX(submitted Rework Record.total_quality_inspected) if > 0
             else <alias>.qty
      effective = base - <alias>.defect_qty + <alias>.recovered_qty

    ``NULLIF(..., 0)`` + ``COALESCE`` makes the correlated subquery evaluate
    once and fall back to qty when there is no submitted QC total.

    Args:
        alias: table alias of `tabFWB Work Report` in the caller's query.

    Returns:
        str: a parenthesised SQL expression safe to drop into SELECT / SUM().
    """
    a = alias
    return f"""(
        COALESCE(
            NULLIF(
                (
                    SELECT MAX(IFNULL(rr_eq.total_quality_inspected, 0))
                    FROM `tabRework Record` rr_eq
                    WHERE rr_eq.from_work_report = {a}.name
                      AND rr_eq.docstatus = 1
                ),
                0
            ),
            IFNULL({a}.qty, 0)
        )
        - IFNULL({a}.defect_qty, 0)
        + IFNULL({a}.recovered_qty, 0)
    )"""


def apply_quality_totals_to_work_report(target_doc, excluded_rework_record=None):
    """
    Sync settlement qty on an FWB Work Report document.

    If Rework Record has a submitted total_quality_inspected value, valid_qty is
    based on that total instead of the worker-entered production qty.
    """
    total_quality_inspected = get_total_quality_inspected(
        target_doc.name,
        excluded_rework_record=excluded_rework_record,
    )

    target_doc.valid_qty = calculate_effective_qty(
        qty=target_doc.qty,
        defect_qty=target_doc.defect_qty,
        recovered_qty=target_doc.recovered_qty,
        total_quality_inspected=total_quality_inspected,
    )
    return total_quality_inspected


def is_overproduced(reported_qty, order_qty):
    """本工序累计有效数量是否已达到 / 超过工单总数（含等于）。

    阈值口径集中在此一处：order_qty<=0（工单未设数量）一律不触发，避免误弹。
    """
    order_qty = flt(order_qty)
    if order_qty <= 0:
        return False
    return flt(reported_qty) >= order_qty


@frappe.whitelist()
def get_production_progress(work_order=None, workstation=None):
    """扫码报工「足量提醒」的服务端口径。

    返回某工单 + 某生产工位（工序）下已提交、非返工报工的累计有效结算数量，
    并与工单总数比较。数量口径复用 ``effective_qty_sql``（与 Employee Wage
    Sheet / 生产总数核对报表同一函数），不新增第二套口径。

    仅 `PRODUCTION_WORKSTATIONS` 生产工位参与；非生产工位或入参不全时安全返回 ``exceeded=False``。
    """
    result = {
        "work_order": work_order,
        "workstation": workstation,
        "product_name": "",
        "order_qty": 0.0,
        "reported_qty": 0.0,
        "is_production_station": False,
        "exceeded": False,
    }

    if not work_order or not workstation:
        return result

    result["is_production_station"] = workstation in PRODUCTION_WORKSTATIONS
    if not result["is_production_station"]:
        return result

    wo = frappe.db.get_value(
        "Work Order", work_order, ["qty", "item_name"], as_dict=True
    )
    if not wo:
        return result

    order_qty = flt(wo.qty)
    result["order_qty"] = order_qty
    result["product_name"] = wo.item_name or ""

    eff = effective_qty_sql("wr")
    reported_qty = (
        frappe.db.sql(
            f"""
            SELECT COALESCE(SUM({eff}), 0)
            FROM `tabFWB Work Report` wr
            WHERE wr.work_order = %s
              AND wr.workstation = %s
              AND wr.docstatus = 1
              AND (
                  wr.rework_type = '否'
                  OR wr.rework_type IS NULL
                  OR wr.rework_type = ''
              )
            """,
            (work_order, workstation),
        )[0][0]
        or 0
    )
    reported_qty = flt(reported_qty)
    result["reported_qty"] = reported_qty
    result["exceeded"] = is_overproduced(reported_qty, order_qty)
    return result


@frappe.whitelist()
def get_production_employee_query(doctype, txt, searchfield, start, page_len, filters):
    """FWB Work Report 用的员工过滤：
    - 只要 Active 员工
    - 默认：在 Employee Operation 里，至少有一个工作站是 `PRODUCTION_WORKSTATIONS` 生产工位之一
    - 如果前端传入 filters.workstation，则只按该工作站过滤
    """
    text = f"%{txt or ''}%"

    # 确保 filters 一定是字典
    filters = filters or {}
    ws_filter = filters.get("workstation")

    # 如果指定了 workstation，则只按这个工作站过滤；
    # 否则退回到默认的 `PRODUCTION_WORKSTATIONS` 生产工位列表。
    if ws_filter:
        workstations = (ws_filter,)
    else:
        workstations = PRODUCTION_WORKSTATIONS

    return frappe.db.sql(
        f"""
        SELECT
            e.name,
            e.employee_name
        FROM `tabEmployee` e
        INNER JOIN `tabEmployee Operation` op
            ON op.parent = e.name
        WHERE
            e.status = 'Active'
            AND e.docstatus < 2
            AND op.workstation IN %(ws)s
            AND (
                e.{searchfield} LIKE %(text)s
                OR e.employee_name LIKE %(text)s
            )
        GROUP BY e.name
        ORDER BY e.employee_name ASC
        LIMIT %(page_len)s OFFSET %(start)s
        """,
        {
            "ws": workstations,
            "text": text,
            "page_len": page_len,
            "start": start,
        },
    )


def _get_bom_hour_rate_info(work_order, workstation):
    if not work_order or not workstation:
        return {"bom_no": "", "hour_rate": 0.0}

    wo = frappe.db.get_value("Work Order", work_order, ["bom_no"], as_dict=True)
    bom_no = (wo.bom_no if wo else "") or ""
    if not bom_no:
        return {"bom_no": "", "hour_rate": 0.0}

    op = frappe.get_all(
        "BOM Operation",
        filters={"parent": bom_no, "workstation": workstation},
        fields=["hour_rate"],
        ignore_permissions=True,
        limit=1,
    )
    hour_rate = flt((op[0] or {}).get("hour_rate")) if op else 0.0

    return {
        "bom_no": bom_no,
        "hour_rate": hour_rate,
    }
