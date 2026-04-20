// Copyright (c) 2025, WenZhou Furui Handicraft Co.,Ltd. and contributors
// For license information, please see license.txt

// v2025.12.09.01 - Employee Wage Summary report JS
// - Add employee filter
// - When workstation is selected, employee options are limited to employees
//   who have FWB Work Reports on that workstation
// - Workstation filter excludes 发货台 / 打包区 / 质检区

frappe.query_reports["Employee Wage Summary"] = {
    filters: [
        {
            fieldname: "from_date",
            label: __("开始于"),
            fieldtype: "Date",
            reqd: 0,
        },
        {
            fieldname: "to_date",
            label: __("结束于"),
            fieldtype: "Date",
            reqd: 0,
        },
        {
            fieldname: "employee",
            label: __("员工"),
            fieldtype: "Link",
            options: "Employee",
            reqd: 0,
            get_query: function () {
                const ws = frappe.query_report.get_filter_value("workstation") || "";

                return {
                    query: "fwb_utils.fwb_manufacturing.report.employee_wage_summary.employee_wage_summary.get_employee_for_wage_summary",
                    filters: {
                        workstation: ws
                    }
                };
            }
        },
        {
            fieldname: "workstation",
            label: __("工作站"),
            fieldtype: "Link",
            options: "Workstation",
            reqd: 0,
            get_query: function () {
                return {
                    query: "fwb_utils.fwb_manufacturing.report.employee_wage_summary.employee_wage_summary.get_workstation_for_wage_summary"
                };
            }
        }
    ],

    onload: function(report) {
        ews_setup_month_shortcuts(report, "employee-wage-summary");
    }
};

function ews_setup_month_shortcuts(report, prefix) {
    if (window.innerWidth >= 992) {
        report.page.add_inner_button(__("⬅️ 上一月"), function() {
            ews_go_prev_month(report);
        });
        report.page.add_inner_button(__("📅 回当月"), function() {
            ews_go_current_month(report);
        });
    }

    if (window.innerWidth < 992) {
        ews_inject_kiosk_css(prefix);
        ews_inject_mobile_toolbar(report, prefix);
    }
}

function ews_go_prev_month(report) {
    let current_from_str = report.get_filter_value("from_date");
    if (!current_from_str) {
        current_from_str = frappe.datetime.get_today();
    }

    const current_obj = frappe.datetime.str_to_obj(current_from_str);
    current_obj.setMonth(current_obj.getMonth() - 1);

    const year = current_obj.getFullYear();
    const month = current_obj.getMonth();
    const first_day = new Date(year, month, 1);
    const last_day = new Date(year, month + 1, 0);

    report.set_filter_value("from_date", frappe.datetime.obj_to_str(first_day));
    report.set_filter_value("to_date", frappe.datetime.obj_to_str(last_day));
    report.refresh();
}

function ews_go_current_month(report) {
    const today = new Date();
    const first_day = new Date(today.getFullYear(), today.getMonth(), 1);

    report.set_filter_value("from_date", frappe.datetime.obj_to_str(first_day));
    report.set_filter_value("to_date", frappe.datetime.obj_to_str(today));
    report.refresh();
}

function ews_inject_mobile_toolbar(report, prefix) {
    const toolbar_id = `${prefix}-toolbar`;
    const prev_btn_id = `${prefix}-prev-month`;
    const current_btn_id = `${prefix}-current-month`;

    $(report.page.wrapper).find(`#${toolbar_id}`).remove();

    const toolbar_html = `
        <div id="${toolbar_id}" style="
            position: fixed;
            bottom: 20px;
            left: 0;
            width: 100%;
            display: flex;
            justify-content: center;
            gap: 20px;
            z-index: 9999;
            pointer-events: none;
        ">
            <button id="${prev_btn_id}" class="btn btn-default" style="
                pointer-events: auto;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                border-radius: 50px;
                padding: 10px 20px;
                background-color: white;
                border: 1px solid #d1d8dd;
                font-weight: bold;
                color: #555;
            ">
                ⬅️ 上一月
            </button>
            <button id="${current_btn_id}" class="btn btn-primary" style="
                pointer-events: auto;
                box-shadow: 0 4px 12px rgba(0,0,0,0.2);
                border-radius: 50px;
                padding: 10px 20px;
                font-weight: bold;
            ">
                📅 回当月
            </button>
        </div>
    `;

    $(report.page.wrapper).append(toolbar_html);

    $(report.page.wrapper).find(`#${prev_btn_id}`).on("click", function() {
        ews_go_prev_month(report);
    });

    $(report.page.wrapper).find(`#${current_btn_id}`).on("click", function() {
        ews_go_current_month(report);
    });
}

function ews_inject_kiosk_css(prefix) {
    const css_id = `${prefix}-kiosk-css`;
    if ($(`#${css_id}`).length) {
        return;
    }

    const css = `
        @media only screen and (max-width: 992px) {
            .page-actions { display: none !important; }
            .navbar-brand, .navbar-home { pointer-events: none !important; opacity: 0.3; }
            .navbar-center, .navbar-search, .search-bar, form[role="search"] { display: none !important; }
            .report-view { padding-bottom: 90px !important; }
        }
    `;

    $("<style>")
        .attr("id", css_id)
        .text(css)
        .appendTo("head");
}
