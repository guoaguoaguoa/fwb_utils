// Copyright (c) 2025, WenZhou Furui Handicraft Co.,Ltd. and contributors
// For license information, please see license.txt

// v2025.12.09.01 - Employee Defect Rate Report client script
// - Add workstation filter exclusion (no 发货台 / 打包区 / 质检区)
// - Add employee filter query depending on selected workstation
// - Keep finished_bom filter using custom BOM query

/* global frappe */

frappe.query_reports["Employee Defect Rate Report"] = {
    filters: [
        {
            fieldname: "from_date",
            label: "开始于",
            fieldtype: "Date",
            default: frappe.datetime.add_months(frappe.datetime.get_today(), -1)
        },
        {
            fieldname: "to_date",
            label: "结束于",
            fieldtype: "Date",
            default: frappe.datetime.get_today()
        },
        {
            fieldname: "employee",
            label: "员工ID",
            fieldtype: "Link",
            options: "Employee",
            get_query: function () {
                const ws = frappe.query_report.get_filter_value("workstation") || "";
                return {
                    query: "fwb_utils.fwb_manufacturing.report.employee_defect_rate_report.employee_defect_rate_report.employee_for_workstation",
                    filters: {
                        workstation: ws
                    }
                };
            }
        },
        {
            fieldname: "workstation",
            label: "工作站",
            fieldtype: "Link",
            options: "Workstation",
            get_query: function () {
                // exclude some special workstations from dropdown
                return {
                    filters: {
                        name: ["not in", ["发货台", "打包区", "质检区"]]
                    }
                };
            }
        },
        {
            fieldname: "work_order",
            label: "工单号",
            fieldtype: "Link",
            options: "Work Order"
        },
        {
            fieldname: "finished_bom",
            label: "成品物料",
            fieldtype: "Link",
            options: "BOM",
            get_query: function () {
                return {
                    query: "fwb_utils.fwb_manufacturing.report.employee_defect_rate_report.employee_defect_rate_report.bom_for_finished_items"
                };
            }
        }
    ]
};
