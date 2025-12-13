// Copyright (c) 2025, WenZhou Furui Handicraft Co.,Ltd. and contributors
// For license information, please see license.txt

// v2025.12.08.06 - Material Readiness Check client script
// - Top bar blue button: "从工单同步物料"
// - Per-row is_confirmed change -> set check_date = now
// - Auto compute progress and render in HTML field "status"
// - checked_by:
//   * auto-fill from current user (if mapped to Employee)
//   * sync checked_by_name for list view filtering
//   * filter to departments under group(s) containing "办公职能" or "销售部" (server-side query)

/* global frappe */

function update_material_progress(frm) {
    const items = frm.doc.items || [];
    const total = items.length;

    let full = 0;
    let partial = 0;
    let wrong = 0;

    items.forEach(row => {
        const v = (row.is_confirmed || "").trim();
        if (v === "齐全") {
            full++;
        } else if (v === "部分") {
            partial++;
        } else if (v === "错误") {
            wrong++;
        }
        // "未到" or empty will be treated as not-ready but not counted separately
    });

    let percent = 0.0;
    if (total > 0) {
        percent = (full / total) * 100.0;
    }

    let status_text = "部分确认";
    if (total === 0) {
        status_text = "部分确认";
    } else if (wrong > 0) {
        status_text = "未通过";
    } else if (full === total) {
        status_text = "全部确认";
    } else {
        status_text = "部分确认";
    }

    let color = "#cc0000"; // red
    if (percent >= 99.9) {
        color = "#009933"; // green
    } else if (percent >= 50) {
        color = "#ff9900"; // orange
    }

    const pct_str = total > 0 ? (percent.toFixed(0) + "%") : "0%";

    const html = `
        <div class="mrc-progress-wrapper" style="margin-top:4px;">
            <div style="font-size:12px; color:#666; margin-bottom:4px;">
                状态：<b>${status_text}</b>，
                物料到位进度：<b>${pct_str}</b> （齐全 ${full}/${total}）
            </div>
            <div style="width:100%; height:12px; border-radius:6px; background:#eee; overflow:hidden;">
                <div style="
                    width:${percent}%;
                    height:100%;
                    background:${color};
                    transition: width 0.3s ease-out;
                "></div>
            </div>
        </div>
    `;

    if (frm.fields_dict["status"]) {
        frm.set_df_property("status", "options", html);
        frm.refresh_field("status");
    }
}

// sync checked_by_name from checked_by
function sync_checked_by_name(frm) {
    if (!frm.doc.checked_by) {
        if (frm.fields_dict["checked_by_name"]) {
            frm.set_value("checked_by_name", "");
        }
        return;
    }

    frappe.db.get_value(
        "Employee",
        frm.doc.checked_by,
        "employee_name",
        (r) => {
            if (!r) return;
            if (frm.fields_dict["checked_by_name"]) {
                frm.set_value("checked_by_name", r.employee_name || "");
            }
        }
    );
}

// checked_by behavior: filter + sync checked_by_name
function setup_checked_by_field(frm) {
    // 1）仍然保留过滤条件（只列出「办公职能」「销售部」等员工）
    if (frm.fields_dict["checked_by"]) {
        frm.set_query("checked_by", function () {
            return {
                query: "fwb_utils.fwb_manufacturing.doctype.material_readiness_check.material_readiness_check.get_checker_employee_query"
            };
        });
    }

    // 2）✂️ 去掉“自动填当前登录人”的逻辑，只在已有值时同步姓名
    if (frm.doc.checked_by) {
        sync_checked_by_name(frm);
    }

    // ✅ 不再有：
    // if (frm.doc.docstatus === 0 && !frm.doc.checked_by) { ... 自动带出当前用户 ... }
}


frappe.ui.form.on("Material Readiness Check", {
    refresh(frm) {
        // top bar blue button: sync from Work Order
        if (frm.doc.docstatus === 0 && frm.doc.work_order) {
            const btn = frm.add_custom_button(
                "从工单同步物料",
                () => {
                    if (!frm.doc.name) {
                        frappe.msgprint("请先保存表单，再同步物料。");
                        return;
                    }

                    frappe.call({
                        method: "fwb_utils.fwb_manufacturing.doctype.material_readiness_check.material_readiness_check.pull_from_work_order",
                        args: { check_name: frm.doc.name },
                        freeze: true,
                        freeze_message: "正在从工单 / BOM 拉取物料...",
                        callback(r) {
                            const msg = r && r.message ? r.message : {};
                            const count = msg.total_items || 0;
                            frappe.msgprint({
                                title: "同步完成",
                                message: `已同步 ${count} 条物料明细。`,
                                indicator: "green"
                            });
                            frm.reload_doc();
                        }
                    });
                }
            );
            if (btn && btn.removeClass) {
                btn.removeClass("btn-default").addClass("btn-primary");
            }
        }

        setup_checked_by_field(frm);
        update_material_progress(frm);
    },

    work_order(frm) {
        // if user manually selects Work Order on an existing doc, sync once
        if (!frm.doc.name) {
            return;
        }
        if (frm.doc.work_order) {
            frappe.call({
                method: "fwb_utils.fwb_manufacturing.doctype.material_readiness_check.material_readiness_check.pull_from_work_order",
                args: { check_name: frm.doc.name },
                freeze: true,
                freeze_message: "正在从工单 / BOM 拉取物料...",
                callback() {
                    frm.reload_doc();
                }
            });
        }
    },

    checked_by(frm) {
        // whenever user changes checked_by manually, sync checked_by_name
        sync_checked_by_name(frm);
    },

    validate(frm) {
        update_material_progress(frm);
    }
});

frappe.ui.form.on("Material Readiness Check Item", {
    is_confirmed(frm, cdt, cdn) {
        const row = locals[cdt][cdn];

        if (row.is_confirmed) {
            // 1）用 set_value 写入 check_date（更稳）
            frappe.model.set_value(cdt, cdn, "check_date", frappe.datetime.now_datetime());

            // 2）根据当前登录人写入 check_person（员工姓名）
            frappe.call({
                method: "frappe.client.get_value",
                args: {
                    doctype: "Employee",
                    filters: { user_id: frappe.session.user },
                    fieldname: "employee_name"
                },
                callback(r) {
                    const emp_name = r && r.message && r.message.employee_name;
                    if (emp_name) {
                        frappe.model.set_value(cdt, cdn, "check_person", emp_name);
                    }
                }
            });
        }
        // 如果 is_confirmed 清空，就保留原来的 check_date / check_person 作为历史，不动它

        update_material_progress(frm);
    },

    actual_available_qty(frm) {
        update_material_progress(frm);
    },

    items_add(frm) {
        update_material_progress(frm);
    },

    items_remove(frm) {
        update_material_progress(frm);
    }
});
