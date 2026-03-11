// Copyright (c) 2025, WenZhou Furui Handicraft Co.,Ltd. and contributors
// For license information, please see license.txt

// === Helper: inject CSS for time-based & penalty rows ===
function inject_wage_sheet_css() {
    if ($("#wage-sheet-css").length) return;

    const css = `
        /* highlight time-based rows (Blue) */
        .time-based-wage-row [data-fieldname="rate"],
        .time-based-wage-row [data-fieldname="duration_display"],
        .time-based-wage-row [data-fieldname="amount"] {
            color: #0066cc !important;
            font-weight: 600 !important;
        }

        .time-based-wage-row [data-fieldname="rate"] input,
        .time-based-wage-row [data-fieldname="duration_display"] input,
        .time-based-wage-row [data-fieldname="amount"] input {
            color: #0066cc !important;
            font-weight: 600 !important;
        }

        /* highlight penalty rows (Red) */
        .penalty-wage-row [data-fieldname="product_name"] {
            color: red !important;
            font-weight: bold !important;
        }
        .penalty-wage-row [data-fieldname="product_name"] div {
            color: red !important;
            font-weight: bold !important;
        }

        /* top buttons: force visible colors */
        .btn-wage-generate {
            background-color: #007bff !important;
            border-color: #007bff !important;
            color: #ffffff !important;
            font-weight: 600 !important;
        }

        .btn-wage-slip {
            background-color: #28a745 !important;
            border-color: #28a745 !important;
            color: #ffffff !important;
            font-weight: 600 !important;
        }
    `;
    $("<style id='wage-sheet-css'>")
        .text(css)
        .appendTo("head");
}

// === Helper: format duration (seconds -> "X小时Y分钟") ===
function format_duration_display(seconds) {
    const sec = cint(seconds || 0);
    if (sec <= 0) {
        return "";
    }
    const hours = Math.floor(sec / 3600);
    const minutes = Math.floor((sec % 3600) / 60);
    const h_str = hours > 0 ? `${hours}小时` : "";
    const m_str = minutes > 0 ? `${minutes}分钟` : (hours > 0 ? "0分钟" : "");
    return (h_str + m_str) || "";
}

// === Helper: recompute one child row amount based on mode ===
function recompute_row_amount(row) {
    const seconds = cint(row.duration_seconds || 0);
    const rate = flt(row.rate || 0);
    const qty = flt(row.qty || 0);

    let amount = flt(row.amount || 0);

    if (seconds > 0) {
        // time-based wage: hours * rate
        const hours = seconds / 3600.0;
        amount = hours * rate;
    } else {
        // piece-based wage: qty * rate
        amount = qty * rate;
    }

    row.amount = amount;
}

// === Helper: recompute parent totals (handling penalty deduction) ===
function recompute_totals(frm) {
    let total_qty = 0.0;
    let total_amount = 0.0;

    (frm.doc.details || []).forEach(row => {
        total_qty += flt(row.qty || 0);

        // Handle penalty deduction in JS preview too
        if (cint(row.is_penalty) === 1) {
            total_amount -= flt(row.amount || 0);
        } else {
            total_amount += flt(row.amount || 0);
        }
    });

    frm.set_value("total_qty", total_qty);
    frm.set_value("total_amount", total_amount);
}

// === Helper: refresh styles on grid rows ===
function refresh_grid_row_styles(frm) {
    if (!frm.fields_dict["details"] || !frm.fields_dict["details"].grid) return;

    const grid = frm.fields_dict["details"].grid;

    grid.grid_rows.forEach(row => {
        const doc = row.doc;
        const $data_row = $(row.row || row.$row || []);
        if (!$data_row.length) return;

        // 1. Blue Style for Time-based
        const seconds = cint(doc.duration_seconds || 0);
        if (seconds > 0) {
            $data_row.addClass("time-based-wage-row");
        } else {
            $data_row.removeClass("time-based-wage-row");
        }

        // 2. Red Style for Penalty
        const is_penalty = cint(doc.is_penalty || 0);
        if (is_penalty === 1) {
            $data_row.addClass("penalty-wage-row");
        } else {
            $data_row.removeClass("penalty-wage-row");
        }
    });
}

// === Parent DocType: Employee Wage Sheet ===
frappe.ui.form.on("Employee Wage Sheet", {
    refresh(frm) {
        inject_wage_sheet_css();
        recompute_totals(frm);
        refresh_grid_row_styles(frm);

        if (frm.is_new()) {
            return;
        }

        // --- Button 1: 从报工生成明细（草稿态） ---
        if (frm.doc.docstatus === 0) {
            const btn_generate = frm.add_custom_button(
                "从报工生成明细",
                function () {
                    if (!frm.doc.employee || !frm.doc.from_date || !frm.doc.to_date) {
                        frappe.msgprint({
                            title: "缺少必要信息",
                            message: "请先选择员工、开始日期和结束日期，再生成明细。",
                            indicator: "red"
                        });
                        return;
                    }

                    frappe.call({
                        method: "fwb_utils.fwb_manufacturing.doctype.employee_wage_sheet.employee_wage_sheet.generate_wage_details",
                        args: {
                            wage_sheet_name: frm.doc.name
                        },
                        freeze: true,
                        freeze_message: "正在从报工汇总，稍候...",
                        callback(r) {
                            console.log("generate_wage_details result:", r);

                            if (r && r.message) {
                                const rows = r.message.rows || 0;
                                const qty = frappe.format(r.message.total_qty || 0, { fieldtype: "Float" });
                                const amt = frappe.format(r.message.total_amount || 0, { fieldtype: "Currency" });

                                frappe.msgprint({
                                    title: "已更新明细",
                                    message: `本次共汇总 <b>${rows}</b> 行明细，合计数量 <b>${qty}</b>，合计金额 <b>${amt}</b>。`,
                                    indicator: "green"
                                });

                                frm.reload_doc();
                            } else {
                                frappe.msgprint({
                                    title: "未发现报工数据",
                                    message: "在指定时间范围内未找到该员工的已提交 FWB Work Report。",
                                    indicator: "orange"
                                });
                            }
                        }
                    });
                }
            );
            if (btn_generate) {
                btn_generate
                    .addClass("btn-wage-generate")
                    .prepend('<i class="fa fa-magic" style="margin-right:4px;"></i>');
            }
        }

        // --- Button 2: 生成工资单（已提交态） ---
        if (frm.doc.docstatus === 1) {
            const btn_slip = frm.add_custom_button(
                "生成工资单",
                function () {
                    frappe.call({
                        method: "fwb_utils.fwb_manufacturing.doctype.employee_wage_sheet.employee_wage_sheet.make_salary_slip_from_wage_sheet",
                        args: {
                            wage_sheet: frm.doc.name
                        },
                        freeze: true,
                        freeze_message: "正在生成工资单，请稍候...",
                        callback(r) {
                            console.log("make_salary_slip_from_wage_sheet result:", r);

                            const payload = (r && r.message) ? r.message : {};

                            const slip = payload.salary_slip || payload.name || "";
                            const amt = (payload.total_amount !== undefined && payload.total_amount !== null)
                                ? frappe.format(payload.total_amount, { fieldtype: "Currency" })
                                : "（未返回金额）";

                            const lines = [];
                            lines.push(`本工资结算单合计金额：<b>${amt}</b>`);

                            if (slip) {
                                lines.push(`写入工资条编号：<b>${slip}</b>`);
                            } else {
                                lines.push("后台未返回工资条编号，请在【工资单】列表中按员工 + 期间过滤查看。");
                            }

                            const html = lines.join("<br>");

                            frappe.msgprint({
                                title: "工资单已生成",
                                message: html,
                                indicator: "green",
                                wide: true
                            });

                            frm.reload_doc();
                        }
                    });
                }
            );
            if (btn_slip) {
                btn_slip
                    .addClass("btn-wage-slip")
                    .prepend('<i class="fa fa-credit-card" style="margin-right:4px;"></i>');
            }
        }
    },

    // 自动带出员工姓名
    employee(frm) {
        if (!frm.doc.employee) {
            frm.set_value("employee_name", "");
            return;
        }

        frappe.db.get_value(
            "Employee",
            frm.doc.employee,
            "employee_name",
            (r) => {
                if (r && r.employee_name) {
                    frm.set_value("employee_name", r.employee_name);
                }
            }
        );
    }
});

// === Child Table: Employee Wage Sheet Detail ===
frappe.ui.form.on("Employee Wage Sheet Detail", {
    qty(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        recompute_row_amount(row);
        recompute_totals(frm);
        refresh_grid_row_styles(frm);
        frm.refresh_field("details");
    },

    rate(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        recompute_row_amount(row);
        recompute_totals(frm);
        refresh_grid_row_styles(frm);
        frm.refresh_field("details");
    },

    duration_seconds(frm, cdt, cdn) {
        const row = locals[cdt][cdn];

        row.duration_display = format_duration_display(row.duration_seconds);

        recompute_row_amount(row);
        recompute_totals(frm);
        frm.refresh_field("details");
        refresh_grid_row_styles(frm);
    },

    amount(frm, cdt, cdn) {
        // manual override
        recompute_totals(frm);
        refresh_grid_row_styles(frm);
        frm.refresh_field("details");
    },

    details_add(frm, cdt, cdn) {
        recompute_totals(frm);
        refresh_grid_row_styles(frm);
        frm.refresh_field("details");
    },

    details_remove(frm, cdt, cdn) {
        recompute_totals(frm);
        refresh_grid_row_styles(frm);
        frm.refresh_field("details");
    }
});
