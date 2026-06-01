// Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and contributors
// 考勤校对表（总览）—— 一员工一行、当天一列、紧凑码热力图；左 2 列冻结 + 月份快捷 + 图例

frappe.query_reports["Attendance Verification Overview"] = {
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
        if (column.fieldname && column.fieldname.indexOf("day_") === 0) {
            var bg = attn_fill_color(value);
            return (
                '<div style="background:' + bg + ';margin:-5px -10px;padding:5px 4px;text-align:center">' +
                (value || "") + "</div>"
            );
        }
        return value;
    },

    get_datatable_options: function (options) {
        // 去掉序号列/勾选列 → 员工=col-0、部门=col-1，冻结才对齐
        return Object.assign(options, { serialNoColumn: false, checkboxColumn: false });
    },

    after_datatable_render: function (datatable) {
        attn_apply_freeze();
    },

    onload: function (report) {
        $(report.page.wrapper).addClass("attn-overview-report");
        attn_inject_legend(report);
        attn_setup_buttons(report);
    },
};

// 左 2 列(员工/部门)冻结：scoped sticky CSS + 动态测量 员工列宽对齐部门列 left
// frappe-datatable 无原生冻结；已 serialNoColumn=false 去掉序号列，故 col-0=员工、col-1=部门
function attn_apply_freeze() {
    var $c0 = $(".attn-overview-report .dt-cell--col-0").first();
    if (!$c0.length) return;
    var w0 = Math.round($c0.outerWidth()); // 员工列实际宽 → 部门列偏移，避免重叠
    var css =
        ".attn-overview-report .dt-cell--col-0,.attn-overview-report .dt-cell--header-0" +
        "{position:sticky;left:0;z-index:11;background-color:#fff;}" +
        ".attn-overview-report .dt-cell--col-1,.attn-overview-report .dt-cell--header-1" +
        "{position:sticky;left:" + w0 + "px;z-index:10;background-color:#fff;}";
    $("#attn-freeze-css").remove();
    $("<style id='attn-freeze-css'>").text(css).appendTo("head");
}

// ---- 两报表共用小工具（与明细报表保持一致）----

function attn_fill_color(text) {
    text = text || "";
    if (text.indexOf("缺") >= 0 || text.indexOf("旷") >= 0) return "#fde7e9";
    if (text.indexOf("半") >= 0) return "#fff4d6";
    if (text.indexOf("假") >= 0) return "#e7f0fd";
    if (text.indexOf("出") >= 0) return "#e6f4ea";
    return "#f2f2f2";
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
