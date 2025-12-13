# Copyright (c) 2025, WenZhou Furui Handicraft Co.,Ltd. and contributors
# For license information, please see license.txt

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
    Collect aggregated data from FWB Work Report.

    - Only docstatus = 1 rows.
    - Filter by employee and created_at date range.
    - Group by work_order + workstation + wage_type.
      => This allows one time-based row and one piece-based row
         for the same work_order + workstation.
    - Summarize valid_qty, defect_qty, duration (for time-based).
    - Enrich each group with:
        * work_order info (BOM, Item)
        * BOM custom size fields: custom_size_l / custom_size_w / custom_size_h
        * rate (hour_rate or custom_piece_rate) with fallback from Work Report itself.
    """
    sql = """
        SELECT
            w.work_order,
            w.workstation,
            w.wage_type,
            SUM(IFNULL(w.valid_qty, 0))       AS total_valid_qty,
            SUM(IFNULL(w.defect_qty, 0))      AS total_defect_qty,
            SUM(
                CASE
                    WHEN w.wage_type = '计时' THEN IFNULL(w.duration, 0)
                    ELSE 0
                END
            )                                 AS total_duration_seconds,
            MAX(w.product_name)               AS product_name
        FROM `tabFWB Work Report` w
        WHERE
            w.docstatus = 1
            AND w.employee = %(employee)s
            AND DATE(w.created_at) >= %(from_date)s
            AND DATE(w.created_at) <= %(to_date)s
        GROUP BY w.work_order, w.workstation, w.wage_type
        HAVING
            total_valid_qty > 0
            OR total_duration_seconds > 0
    """

    params = {
        "employee": employee,
        "from_date": from_date,
        "to_date": to_date,
    }

    aggregated = frappe.db.sql(sql, params, as_dict=True)

    if not aggregated:
        return []

    result = []

    for row in aggregated:
        work_order = row.work_order
        workstation = row.workstation

        size_l = ""
        size_w = ""
        size_h = ""
        product_name = row.product_name or ""
        rate = 0.0

        # Get Work Order -> BOM / Item info
        wo = frappe.db.get_value(
            "Work Order",
            work_order,
            ["bom_no", "production_item", "item_name"],
            as_dict=True,
        )

        bom_no = None
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

        total_duration = cint(row.total_duration_seconds or 0)
        total_valid_qty = flt(row.total_valid_qty or 0)
        total_defect_qty = flt(row.total_defect_qty or 0)

        # Compute defect rate
        denom = total_valid_qty + total_defect_qty
        if denom > 0:
            defect_rate = (total_defect_qty / denom) * 100.0
        else:
            defect_rate = 0.0

        # Decide rate
        if total_duration > 0:
            # time-based mode
            rate = _get_time_rate(
                employee=employee,
                work_order=work_order,
                workstation=workstation,
                bom_no=bom_no,
            )
        else:
            # piece-based mode
            rate = _get_piece_rate(
                employee=employee,
                work_order=work_order,
                workstation=workstation,
                bom_no=bom_no,
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

    return result


def _get_time_rate(employee: str, work_order: str, workstation: str, bom_no):
    """
    Decide hourly rate for time-based rows.

    Priority:
    1) BOM Operation.hour_rate for given BOM + workstation
    2) Average hourly_rate from FWB Work Report for this employee + work_order + workstation
       (only wage_type = '计时')
    3) 0.0
    """
    # 1) try BOM Operation.hour_rate
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

    # 2) fallback: average hourly_rate from FWB Work Report (time-based only)
    val = frappe.db.sql(
        """
        SELECT AVG(IFNULL(hourly_rate, 0))
        FROM `tabFWB Work Report`
        WHERE
            docstatus = 1
            AND employee = %s
            AND work_order = %s
            AND workstation = %s
            AND wage_type = '计时'
        """,
        (employee, work_order, workstation),
    )

    if val and val[0] and val[0][0] is not None:
        avg_rate = flt(val[0][0] or 0)
        if avg_rate > 0:
            return avg_rate

    # 3) default
    return 0.0


def _get_piece_rate(employee: str, work_order: str, workstation: str, bom_no):
    """
    Decide piece rate for quantity-based rows.

    Priority:
    1) BOM Operation.custom_piece_rate for given BOM + workstation
    2) Average custom_piece_rate from FWB Work Report for this employee + work_order + workstation
       (exclude wage_type = '计时')
    3) 0.0
    """
    # 1) try BOM Operation.custom_piece_rate
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

    # 2) fallback: average custom_piece_rate from FWB Work Report (non-time-based)
    val = frappe.db.sql(
        """
        SELECT AVG(IFNULL(custom_piece_rate, 0))
        FROM `tabFWB Work Report`
        WHERE
            docstatus = 1
            AND employee = %s
            AND work_order = %s
            AND workstation = %s
            AND (wage_type IS NULL OR wage_type != '计时')
        """,
        (employee, work_order, workstation),
    )

    if val and val[0] and val[0][0] is not None:
        avg_rate = flt(val[0][0] or 0)
        if avg_rate > 0:
            return avg_rate

    # 3) default
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
