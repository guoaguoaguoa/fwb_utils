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

// ---- 报表小工具（口径与明细报表 color_for / compact_code 对齐）----

// 按紧凑码文字取色：旷/⚠=红，未=米，半=黄，假=蓝，出=绿，余灰。
function attn_fill_color(text) {
    text = text || "";
    if (text.indexOf("旷") >= 0 || text.indexOf("⚠") >= 0) return "#fde7e9"; // 红：旷工/迟到早退被扣
    if (text.indexOf("未") >= 0) return "#faf4e6"; // 米：未到（没来，无薪非违规）
    if (text.indexOf("半") >= 0) return "#fff4d6"; // 黄：半天
    if (text.indexOf("假") >= 0) return "#e7f0fd"; // 蓝：请假
    if (text.indexOf("出") >= 0) return "#e6f4ea"; // 绿：出勤
    return "#f2f2f2"; // 灰：休息/无记录
}

// 总览图例：含紧凑码符号（与本表实际输出一致，△/⚠/💪 都会出现）
function attn_legend_html() {
    var sw = function (c, t) {
        return (
            '<span style="display:inline-block;width:14px;height:14px;background:' + c +
            ';border:1px solid #ccc;border-radius:3px;vertical-align:middle;margin:0 4px 0 12px"></span>' + t
        );
    };
    return (
        '<div style="padding:6px 10px;margin:4px 0 8px;background:#fafafa;border:1px solid #eee;border-radius:6px;font-size:12px;color:#555">图例：' +
        sw("#e6f4ea", "出勤") + sw("#faf4e6", "未到") + sw("#fde7e9", "旷工/被扣") +
        sw("#fff4d6", "半天") + sw("#e7f0fd", "请假") + sw("#f2f2f2", "休息/无记录") +
        '　·　△漏卡(不扣)　⚠漏卡被扣/迟到早退　💪加班</div>'
    );
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
        '<div style="margin-top:4px">颜色 绿=出勤　米=未到(无薪)　红=旷工/被扣　黄=半天　蓝=请假　灰=无记录/休息　｜　符号 △漏卡(不扣)　⚠漏卡被扣/迟到早退　💪加班</div>' +
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
