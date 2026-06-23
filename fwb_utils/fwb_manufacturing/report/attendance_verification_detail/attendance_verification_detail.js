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
            // 颜色由服务端 color_for(row) 算好放在 data._bg（单一口径，含被扣→红）
            var bg = data && data._bg ? data._bg : "transparent";
            value =
                '<div style="background:' + bg + ';margin:-5px -10px;padding:5px 10px;text-align:center">' +
                value + "</div>";
        }
        return value;
    },

    onload: function (report) {
        attn_inject_legend(report);
        attn_inject_help(report);
        attn_setup_buttons(report);
        attn_fill_threshold(report);
    },
};

// 动态填入「迟到早退起扣阈值」(读薪资考勤参数，避免说明里写死分钟数)
function attn_fill_threshold(report) {
    frappe.db.get_single_value("Payroll Attendance Parameter", "deduction_threshold_minutes").then(function (v) {
        if (v === undefined || v === null || v === "") return;
        $(report.page.wrapper).find(".attn-threshold").text(v);
    });
}

// ---- 报表小工具（口径与服务端 color_for / attendance_result_summary 对齐）----

// 明细图例：状态格颜色 + 迟到/早退列为缺勤分钟（本表格内不出现 △/⚠/💪 符号）
function attn_legend_html() {
    var sw = function (c, t) {
        return (
            '<span style="display:inline-block;width:14px;height:14px;background:' + c +
            ';border:1px solid #ccc;border-radius:3px;vertical-align:middle;margin:0 4px 0 12px"></span>' + t
        );
    };
    return (
        '<div style="padding:6px 10px;margin:4px 0 8px;background:#fafafa;border:1px solid #eee;border-radius:6px;font-size:12px;color:#555">图例：' +
        sw("#e6f4ea", "出勤") + sw("#faf4e6", "未到(没来·无薪)") + sw("#fde7e9", "旷工/迟到早退被扣") +
        sw("#fff4d6", "半天") + sw("#e7f0fd", "请假") + sw("#f2f2f2", "休息/无记录") +
        '　·　迟到/早退列为缺勤分钟（满<span class="attn-threshold">15</span>分起扣）</div>'
    );
}

function attn_inject_legend(report) {
    var id = "attn-legend";
    if ($(report.page.wrapper).find("#" + id).length) return;
    var $form = $(report.page.wrapper).find(".page-form").first();
    $('<div id="' + id + '">' + attn_legend_html() + "</div>").insertAfter($form);
}

// 底部说明面板：用通用打卡串讲清「缺卡判定 + 是否扣款」，方便接手者（两报表一致）
function attn_help_html() {
    var li = function (t) { return '<div style="margin:2px 0">· ' + t + "</div>"; };
    return (
        '<div style="padding:8px 12px;margin:10px 0 4px;background:#fafafa;border:1px solid #eee;border-radius:6px;font-size:12px;color:#555;line-height:1.6">' +
        '<b>考勤判定与扣款</b>（普工4卡 07:30/11:30/12:30/17:00，午休 11:30–12:30 为界；括号=(上班1,下班1,上班2,下班2)，"-"为缺卡）' +
        li('4卡齐 / 只缺中间卡(下班1或上班2) → <b>出勤·不扣</b>。如 (07:25,-,12:01,17:01) 漏下班1，照常出勤。') +
        li('缺<b>开头卡(上班1)</b> → 出勤，上班时间塌到中午 → 按<b>迟到</b>扣≈半天。如 (-,11:31,11:58,17:04)。') +
        li('缺<b>结尾卡(下班2)</b> → 出勤，下班时间塌到中午 → 按<b>早退</b>扣≈半天。如 (07:23,11:31,11:53,-)。') +
        li('整天没卡 / 只打上班或只打下班(单边卡) → <b>未到(无薪)</b>。如 (-,-,-,-)。') +
        li('旷工(钉钉判定) → 红色<b>旷工</b>。') +
        li('迟到/早退满<span class="attn-threshold">15</span>分钟才起扣，一旦起扣从第1分钟全扣，每天最多扣1个工日。') +
        '<div style="margin-top:4px">颜色 绿=出勤　米=未到(无薪)　红=旷工/被扣　黄=半天　蓝=请假　灰=无记录/休息</div>' +
        "</div>"
    );
}

function attn_inject_help(report) {
    var id = "attn-help";
    if ($(report.page.wrapper).find("#" + id).length) return;
    var $host = $(report.page.wrapper).find(".layout-main-section").first();
    if (!$host.length) $host = $(report.page.wrapper);
    $('<div id="' + id + '">' + attn_help_html() + "</div>").appendTo($host);
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
