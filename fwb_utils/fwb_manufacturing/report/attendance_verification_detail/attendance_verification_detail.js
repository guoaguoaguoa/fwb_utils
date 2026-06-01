// Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and contributors
// 考勤校对表（明细）—— 一天一行，状态格填充色 + 月份快捷 + 异常/加班切换 + 顶部图例

frappe.query_reports["Attendance Verification Detail"] = {
    filters: [
        { fieldname: "from_date", label: __("开始于"), fieldtype: "Date", default: frappe.datetime.month_start() },
        { fieldname: "to_date", label: __("结束于"), fieldtype: "Date", default: frappe.datetime.month_end() },
        { fieldname: "employee", label: __("员工"), fieldtype: "Link", options: "Employee" },
        { fieldname: "department", label: __("部门"), fieldtype: "Link", options: "Department" },
        { fieldname: "only_abnormal", label: __("只看异常"), fieldtype: "Check" },
        { fieldname: "only_overtime", label: __("只看加班"), fieldtype: "Check" },
    ],

    formatter: function (value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);
        if (data && data.is_summary) {
            return '<b style="color:#555">' + value + "</b>";
        }
        if (column.fieldname === "status_label") {
            var bg = attn_fill_color(data ? data.status_label : value);
            value =
                '<div style="background:' + bg + ';margin:-5px -10px;padding:5px 10px;text-align:center">' +
                value + "</div>";
        }
        return value;
    },

    onload: function (report) {
        attn_inject_legend(report);
        attn_setup_buttons(report);
    },
};

// ---- 以下为两报表共用的小工具（明细/总览各存一份，保持一致）----

function attn_fill_color(text) {
    text = text || "";
    if (text.indexOf("缺") >= 0 || text.indexOf("旷") >= 0) return "#fde7e9"; // 红
    if (text.indexOf("半") >= 0) return "#fff4d6"; // 黄
    if (text.indexOf("假") >= 0) return "#e7f0fd"; // 蓝
    if (text.indexOf("出") >= 0) return "#e6f4ea"; // 绿
    return "#f2f2f2"; // 灰：休息/无记录
}

function attn_legend_html() {
    var sw = function (c, t) {
        return (
            '<span style="display:inline-block;width:14px;height:14px;background:' + c +
            ';border:1px solid #ccc;border-radius:3px;vertical-align:middle;margin:0 4px 0 12px"></span>' + t
        );
    };
    return (
        '<div style="padding:6px 10px;margin:4px 0 8px;background:#fafafa;border:1px solid #eee;border-radius:6px;font-size:12px;color:#555">图例：' +
        sw("#e6f4ea", "出勤") + sw("#fde7e9", "缺勤/旷工") + sw("#fff4d6", "半天") +
        sw("#e7f0fd", "请假") + sw("#f2f2f2", "休息/无记录") +
        '　·　💪加班　△缺卡　⚠迟到/早退</div>'
    );
}

function attn_inject_legend(report) {
    var id = "attn-legend";
    if ($(report.page.wrapper).find("#" + id).length) return;
    var $form = $(report.page.wrapper).find(".page-form").first();
    $('<div id="' + id + '">' + attn_legend_html() + "</div>").insertAfter($form);
}

function attn_setup_buttons(report) {
    report.page.add_inner_button(__("⬅️ 上一月"), function () { attn_shift_month(report, -1); });
    report.page.add_inner_button(__("📅 回当月"), function () { attn_this_month(report); });
    report.page.add_inner_button(__("➡️ 下一月"), function () { attn_shift_month(report, 1); });
    report.page.add_inner_button(__("⚠️ 只看异常"), function () { attn_toggle(report, "only_abnormal"); });
    report.page.add_inner_button(__("💪 只看加班"), function () { attn_toggle(report, "only_overtime"); });
}

function attn_shift_month(report, delta) {
    var f = report.get_filter_value("from_date") || frappe.datetime.get_today();
    var o = frappe.datetime.str_to_obj(f);
    o.setMonth(o.getMonth() + delta);
    var first = new Date(o.getFullYear(), o.getMonth(), 1);
    var last = new Date(o.getFullYear(), o.getMonth() + 1, 0);
    report.set_filter_value("from_date", frappe.datetime.obj_to_str(first));
    report.set_filter_value("to_date", frappe.datetime.obj_to_str(last));
    report.refresh();
}

function attn_this_month(report) {
    report.set_filter_value("from_date", frappe.datetime.month_start());
    report.set_filter_value("to_date", frappe.datetime.month_end());
    report.refresh();
}

function attn_toggle(report, field) {
    report.set_filter_value(field, report.get_filter_value(field) ? 0 : 1);
    report.refresh();
}
