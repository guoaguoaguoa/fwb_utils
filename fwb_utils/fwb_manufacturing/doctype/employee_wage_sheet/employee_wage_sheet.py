# v2025.12.06.06 - Employee Wage Sheet backend
# - Aggregate FWB Work Report into Employee Wage Sheet Detail
# - Split time-based / piece-based rows
# - Push totals into Salary Slip (Manufacturing Wage Detail + earning component)
# - Auto status:
#   * draft -> status = "草稿"
#   * on submit -> status = "已确认" (if not already "已生成工资单")
#   * after make_salary_slip -> status = "已生成工资单"
# - New: on new (including amendment) always clear salary_slip to avoid linking to cancelled slips

import frappe
from frappe.model.document import Document
from frappe.utils import flt, cint, getdate


class EmployeeWageSheet(Document):
    """Main DocType class."""

    def before_insert(self):
        # initial status on first save
        if not self.status:
            self.status = "草稿"

        # for any new doc (including amendment), do NOT carry over old salary_slip
        # wage sheet <-> salary slip link must be recreated by make_salary_slip_from_wage_sheet
        self.salary_slip = None

    def validate(self):
        # keep status consistent in draft
        if self.docstatus == 0 and not self.status:
            self.status = "草稿"

    def on_submit(self):
        # when submitted, mark as "已确认" unless already "已生成工资单"
        if self.status != "已生成工资单":
            self.status = "已确认"
            self.db_set("status", "已确认", update_modified=False)


@frappe.whitelist()
def generate_wage_details(wage_sheet_name: str):
    """
    Aggregate FWB Work Report data into Employee Wage Sheet Detail rows.

    Rules:
    - Group by work_order + workstation + wage_type for the given employee and date range.
      => If both time-based and piece-based exist, they will appear as two separate rows.
    - qty = sum(valid_qty)
    - defect_qty = sum(defect_qty)
    - defect_rate = defect_qty / (valid_qty + defect_qty) * 100 (if denominator > 0)
    - duration_seconds = sum(duration) for time-based rows (wage_type = '计时')
    - If duration_seconds > 0:
        -> time-based mode: amount = (duration_seconds / 3600) * rate
        -> rate from BOM Operation.hour_rate first, then fallback to FWB hourly_rate
      Else:
        -> piece-based mode: amount = qty * rate
        -> rate from BOM Operation.custom_piece_rate first, then fallback to FWB custom_piece_rate
    """
    if not wage_sheet_name:
        frappe.throw("Missing wage_sheet_name")

    ws = frappe.get_doc("Employee Wage Sheet", wage_sheet_name)

    if not ws.employee:
        frappe.throw("Employee is required on Employee Wage Sheet")

    if not ws.from_date or not ws.to_date:
        frappe.throw("From Date and To Date are required on Employee Wage Sheet")

    # Auto-fill employee_name if missing
    if ws.employee and not ws.employee_name:
        emp_name = frappe.db.get_value("Employee", ws.employee, "employee_name")
        if emp_name:
            ws.employee_name = emp_name

    # Clear existing detail rows
    ws.set("details", [])

    rows = _collect_aggregated_rows(
        employee=ws.employee,
        from_date=ws.from_date,
        to_date=ws.to_date,
    )

    for r in rows:
        child = ws.append("details", {})

        child.work_order = r.work_order
        child.product_name = r.product_name
        child.size_l = r.size_l
        child.size_w = r.size_w
        child.size_h = r.size_h
        child.workstation = r.workstation

        child.qty = r.total_valid_qty
        child.defect_qty = r.total_defect_qty
        child.defect_rate = r.defect_rate

        child.duration_seconds = r.total_duration_seconds
        child.duration_display = _format_duration_display(r.total_duration_seconds)
        child.is_penalty = r.get("is_penalty", 0)

        # initial rate decided on server side
        child.rate = r.rate or 0.0

        # amount: follow the same rule as JS
        if child.duration_seconds and child.duration_seconds > 0:
            hours = flt(child.duration_seconds) / 3600.0
            child.amount = hours * flt(child.rate or 0)
        else:
            child.amount = flt(child.qty or 0) * flt(child.rate or 0)

    # Recompute parent totals
    total_qty = 0.0
    total_amount = 0.0

    for d in ws.details:
        total_qty += flt(d.qty or 0)
        if d.is_penalty:
            total_amount -= flt(d.amount or 0)
        else:
            total_amount += flt(d.amount or 0)

    ws.total_qty = total_qty
    ws.total_amount = total_amount

    # keep status in "草稿" while editing if it is some strange value
    if ws.docstatus == 0 and ws.status not in ("草稿", "已确认", "已生成工资单"):
        ws.status = "草稿"

    ws.save()

    return {
        "rows": len(ws.details or []),
        "total_qty": total_qty,
        "total_amount": total_amount,
    }


def _collect_aggregated_rows(employee: str, from_date: str, to_date: str):
    """
    按【单张 FWB Work Report】生成一行工资明细，不再按工单+工位+计时/计件做汇总。

    - 只取 docstatus = 1 的报工
    - 过滤条件：员工 + created_at 日期区间
    - 一条报工 = 一条工资明细
    - rate 由单行报工 + BOM 决定（不做平均）
    """
    sql = """
        SELECT
            w.name                AS work_report,
            w.work_order,
            w.workstation,
            w.wage_type,
            IFNULL(w.valid_qty, 0)       AS valid_qty,
            IFNULL(w.defect_qty, 0)      AS defect_qty,
            IFNULL(w.duration, 0)        AS duration_seconds,
            w.product_name,
            w.hourly_rate,
            w.custom_piece_rate,
            w.rework_type,
            w.rework_rate
        FROM `tabFWB Work Report` w
        WHERE
            w.docstatus = 1
            AND w.employee = %(employee)s
            AND DATE(w.created_at) >= %(from_date)s
            AND DATE(w.created_at) <= %(to_date)s
            AND (
                IFNULL(w.valid_qty, 0) > 0
                OR (w.wage_type = '计时' AND IFNULL(w.duration, 0) > 0)
            )
        ORDER BY w.created_at, w.name
    """

    params = {
        "employee": employee,
        "from_date": from_date,
        "to_date": to_date,
    }

    records = frappe.db.sql(sql, params, as_dict=True)

    if not records:
        return []

    result = []

    for row in records:
        work_order = row.work_order
        workstation = row.workstation

        size_l = ""
        size_w = ""
        size_h = ""
        product_name = row.product_name or ""
        rate = 0.0

        # Work Order -> BOM / Item info
        bom_no = None
        if work_order:
            wo = frappe.db.get_value(
                "Work Order",
                work_order,
                ["bom_no", "production_item", "item_name"],
                as_dict=True,
            )
            if wo:
                bom_no = wo.bom_no
                if not product_name:
                    product_name = wo.item_name or ""

                # Get custom size from BOM custom fields
                if bom_no:
                    bom = frappe.db.get_value(
                        "BOM",
                        bom_no,
                        ["custom_size_l", "custom_size_w", "custom_size_h"],
                        as_dict=True,
                    )
                    if bom:
                        size_l = bom.custom_size_l or ""
                        size_w = bom.custom_size_w or ""
                        size_h = bom.custom_size_h or ""

        total_valid_qty = flt(row.valid_qty or 0)
        total_defect_qty = flt(row.defect_qty or 0)

        # 计时单：只在 wage_type = '计时' 时，把 duration 写进去，否则按 0 处理
        total_duration = cint(row.duration_seconds or 0) if (row.wage_type == "计时") else 0

        # Compute defect rate
        denom = total_valid_qty + total_defect_qty
        if denom > 0:
            defect_rate = (total_defect_qty / denom) * 100.0
        else:
            defect_rate = 0.0

        # Decide rate（不再平均，每行独立）
        if total_duration > 0:
            # time-based mode
            rate = _get_time_rate(
                bom_no=bom_no,
                workstation=workstation,
                row_hourly_rate=row.hourly_rate,
            )
        else:
            # piece-based mode
            rate = _get_piece_rate(
                bom_no=bom_no,
                workstation=workstation,
                row_custom_piece_rate=row.custom_piece_rate,
                row_rework_type=row.rework_type,
                row_rework_rate=row.rework_rate,
            )

        result.append(
            frappe._dict(
                {
                    "work_order": work_order,
                    "workstation": workstation,
                    "product_name": product_name,
                    "size_l": size_l,
                    "size_w": size_w,
                    "size_h": size_h,
                    "total_valid_qty": total_valid_qty,
                    "total_defect_qty": total_defect_qty,
                    "defect_rate": defect_rate,
                    "total_duration_seconds": total_duration,
                    "rate": flt(rate or 0),
                }
            )
        )

    # Collect Penalty Records (Rework Record with is_penalty=1)
    penalty_rows = _collect_penalty_rows(employee, from_date, to_date)
    # frappe.msgprint(f"Debug: Found {len(penalty_rows)} penalty rows between {from_date} and {to_date}")
    result.extend(penalty_rows)

    return result


def _collect_penalty_rows(employee, from_date, to_date):
    """
    Fetch Rework Records marked as 'is_penalty' = 1.
    These will be treated as deduction rows.
    """
    sql = """
        SELECT
            r.name,
            r.work_order,
            r.workstation,
            COALESCE(r.product_name, w.product_name) as product_name,
            IFNULL(r.defective_qty, 0) as qty,
            r.created_at
        FROM `tabRework Record` r
        INNER JOIN `tabFWB Work Report` w ON r.from_work_report = w.name
        WHERE
            r.docstatus = 1
            AND r.is_penalty = 1
            AND r.employee = %(employee)s
            AND DATE(w.created_at) >= %(from_date)s
            AND DATE(w.created_at) <= %(to_date)s
    """
    params = {
        "employee": employee,
        "from_date": from_date,
        "to_date": to_date,
    }
    
    records = frappe.db.sql(sql, params, as_dict=True)
    if not records:
        return []
        
    res = []
    for row in records:
        # Fetch dimensions from Work Order -> BOM if possible (optional, for display)
        size_l, size_w, size_h = "", "", ""
        if row.work_order:
            bom_no = frappe.db.get_value("Work Order", row.work_order, "bom_no")
            if bom_no:
                 bom = frappe.db.get_value("BOM", bom_no, ["custom_size_l", "custom_size_w", "custom_size_h"], as_dict=True)
                 if bom:
                     size_l = bom.custom_size_l
                     size_w = bom.custom_size_w
                     size_h = bom.custom_size_h
                     
        res.append(frappe._dict({
            "work_order": row.work_order,
            "workstation": row.workstation,
            "product_name": row.product_name,
            "size_l": size_l,
            "size_w": size_w,
            "size_h": size_h,
            "total_valid_qty": row.qty, # Mapped to qty column
            "total_defect_qty": 0,
            "defect_rate": 0,
            "total_duration_seconds": 0,
            "rate": 0.0, # Default rate is 0, to be filled by user
            "is_penalty": 1
        }))
    return res


def _get_time_rate(bom_no, workstation, row_hourly_rate):
    """
    计时行的单价（每行 = 一张 FWB Work Report）

    优先级：
    1) BOM Operation.hour_rate（按 BOM + 工作站）
    2) 当前这张报工行上的 hourly_rate
    3) 0.0
    """
    # 1) BOM Operation.hour_rate
    if bom_no:
        op = frappe.db.get_value(
            "BOM Operation",
            {"parent": bom_no, "workstation": workstation},
            ["hour_rate"],
            as_dict=True,
        )
        if op:
            hr = flt(op.hour_rate or 0)
            if hr > 0:
                return hr

    # 2) 当前 FWB Work Report 的 hourly_rate
    hr = flt(row_hourly_rate or 0)
    if hr > 0:
        return hr

    # 3) 默认 0
    return 0.0


def _get_piece_rate(bom_no, workstation, row_custom_piece_rate, row_rework_type, row_rework_rate):
    """
    计件行的单价（每行 = 一张 FWB Work Report）

    优先级：
    1) 若为“有偿返工”且 FWB Work Report.rework_rate > 0，则直接用 rework_rate
    2) BOM Operation.custom_piece_rate（按 BOM + 工作站）
    3) 当前这张报工行上的 custom_piece_rate
    4) 0.0
    """
    # 1) 有偿返工优先：用当前报工的 rework_rate
    if (row_rework_type or "").strip() == "有偿返工":
        pr = flt(row_rework_rate or 0)
        if pr > 0:
            return pr

    # 2) BOM Operation.custom_piece_rate
    if bom_no:
        op = frappe.db.get_value(
            "BOM Operation",
            {"parent": bom_no, "workstation": workstation},
            ["custom_piece_rate"],
            as_dict=True,
        )
        if op:
            pr = flt(op.custom_piece_rate or 0)
            if pr > 0:
                return pr

    # 3) 当前 FWB Work Report 上的 custom_piece_rate
    pr = flt(row_custom_piece_rate or 0)
    if pr > 0:
        return pr

    # 4) 默认 0
    return 0.0


def _format_duration_display(seconds):
    """Convert seconds to a human readable string."""
    sec = cint(seconds or 0)
    if sec <= 0:
        return ""

    hours = sec // 3600
    minutes = (sec % 3600) // 60

    h_str = f"{hours}小时" if hours > 0 else ""
    if hours > 0:
        m_str = f"{minutes}分钟"
    else:
        m_str = f"{minutes}分钟" if minutes > 0 else ""

    text = f"{h_str}{m_str}"
    return text or ""


@frappe.whitelist()
def make_salary_slip_from_wage_sheet(wage_sheet: str) -> dict:
    """
    Create or update a Salary Slip from given Employee Wage Sheet.

    Logic:
    - Ensure wage sheet is submitted and has employee + date range.
    - Try to reuse linked Salary Slip (if any).
    - Else search for existing Salary Slip of same employee and date range.
    - Else create a new Salary Slip (draft).
    - If found Salary Slip is submitted (docstatus = 1), do NOT modify it.
      Raise an error and ask user to cancel it first.
    - Sync child rows into Manufacturing Wage Detail on Salary Slip.
    - Set / update earning component '无底薪计件工' to total_amount.
    - After success, set Employee Wage Sheet.status = '已生成工资单'.
    """
    if not wage_sheet:
        frappe.throw("Missing wage_sheet name.")

    ws = frappe.get_doc("Employee Wage Sheet", wage_sheet)

    if ws.docstatus != 1:
        frappe.throw("Employee Wage Sheet must be submitted before generating Salary Slip.")

    if not ws.employee:
        frappe.throw("Employee is required on Employee Wage Sheet.")

    if not ws.from_date or not ws.to_date:
        frappe.throw("From Date and To Date are required on Employee Wage Sheet.")

    # 1) find or create Salary Slip
    ss = None
    slip_name = ws.salary_slip

    # 1.1 use already linked Salary Slip if present
    if slip_name:
        try:
            ss = frappe.get_doc("Salary Slip", slip_name)
        except frappe.DoesNotExistError:
            ss = None

    # 1.2 else search existing Salary Slip for same employee + period
    if not ss:
        existing = frappe.get_all(
            "Salary Slip",
            filters={
                "employee": ws.employee,
                "start_date": ws.from_date,
                "end_date": ws.to_date,
                "docstatus": ["<", 2],
            },
            fields=["name", "docstatus"],
            limit=1,
        )
        if existing:
            slip_name = existing[0].name
            ss = frappe.get_doc("Salary Slip", slip_name)

    # 1.3 else create new draft Salary Slip
    if not ss:
        ss = frappe.new_doc("Salary Slip")
        ss.employee = ws.employee
        ss.start_date = ws.from_date
        ss.end_date = ws.to_date
        ss.posting_date = ws.to_date or getdate()
        ss.insert()
        slip_name = ss.name

    # safety: do not modify cancelled or submitted slips
    if ss.docstatus == 2:
        frappe.throw(f"Salary Slip {ss.name} is cancelled and cannot be updated.")

    if ss.docstatus == 1:
        # here we stop and ask user to cancel the slip manually
        frappe.throw(
            f"Salary Slip {ss.name} is already submitted. "
            f"Please cancel it before regenerating from Employee Wage Sheet."
        )

    # 2) sync Manufacturing Wage Detail child rows
    child_fieldname = "custom_manufacturing_wage_details"

    if not ss.meta.get_field(child_fieldname):
        frappe.throw(
            f"Salary Slip has no child table field '{child_fieldname}'. "
            f"Please confirm the fieldname on Salary Slip and update backend if needed."
        )

    ss.set(child_fieldname, [])

    for row in (ws.details or []):
        ss.append(child_fieldname, {
            "work_order": row.work_order,
            "product_name": row.product_name,
            "size_l": row.size_l,
            "size_w": row.size_w,
            "size_h": row.size_h,
            "workstation": row.workstation,
            "qty": row.qty,
            "rate": row.rate,
            "duration_seconds": row.duration_seconds,
            "duration_display": row.duration_display,
            "amount": row.amount,
            "defect_qty": row.defect_qty,
            "defect_rate": row.defect_rate,
            "remarks": row.remarks,
        })

    # 3) update earning component "无底薪计件工"
    component_name = "无底薪计件工"
    target_amount = float(ws.total_amount or 0)

    earning_row = None
    for e in (ss.earnings or []):
        if e.salary_component == component_name:
            earning_row = e
            break

    if not earning_row:
        earning_row = ss.append("earnings", {
            "salary_component": component_name,
        })

    earning_row.amount = target_amount

    # save but do not submit
    ss.save()

    # 4) link back to wage sheet + update status
    if ws.salary_slip != ss.name:
        ws.db_set("salary_slip", ss.name, update_modified=False)

    if ws.status != "已生成工资单":
        ws.db_set("status", "已生成工资单", update_modified=False)

    return {
        "salary_slip": ss.name,
        "total_amount": target_amount,
    }
