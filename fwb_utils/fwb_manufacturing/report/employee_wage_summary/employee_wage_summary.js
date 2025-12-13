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
    ]
};
