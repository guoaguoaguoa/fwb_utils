// v2026.01.10.01 - 生产总数核对报告前端配置

const PTV_WORKSTATION_FIELDS = [
    "woodworking_qty",
    "mounting_qty",
    "veneer_qty",
    "primer_qty",
    "top_coat_qty",
    "assembly_qty",
    "polishing_qty",
    "lining_qty"
];

frappe.query_reports["Production Total Verification"] = {
    "filters": [
        {
            "fieldname": "from_date",
            "label": __("开始于"),
            "fieldtype": "Date",
            "default": frappe.datetime.add_months(frappe.datetime.get_today(), -1),
            "reqd": 0
        },
        {
            "fieldname": "to_date",
            "label": __("结束于"),
            "fieldtype": "Date",
            "default": frappe.datetime.get_today(),
            "reqd": 0
        },
        {
            "fieldname": "work_order",
            "label": __("工单号"),
            "fieldtype": "Data"
        },
        {
            "fieldname": "product_name",
            "label": __("产品名 (支持模糊)"),
            "fieldtype": "Data"
            // 使用 Data 类型，配合 Python 里的 LIKE 语句实现模糊搜索
        }
    ],

    "onload": function(report) {
        ptv_setup_month_shortcuts(report, "production-total-verification");
        ptv_inject_report_legend(report, "production-total-verification");
    },

    // 格式化器：可以在这里给特定的单元格加颜色
    "formatter": function(value, row, column, data, default_formatter) {
        if (PTV_WORKSTATION_FIELDS.includes(column.fieldname)) {
            const current_qty = flt(data[column.fieldname] || 0);
            const cumulative_qty = flt(data[`${column.fieldname}_cumulative`] || 0);
            const date_filter_active = cint(data.date_filter_active || 0);

            if (current_qty > 0) {
                const current_value = default_formatter(value, row, column, data);
                return `<span style="font-weight:bold; color:#111827;">${current_value}</span>`;
            }

            if (!date_filter_active && cumulative_qty > 0) {
                const cumulative_value = default_formatter(cumulative_qty, row, column, data);
                return `<span style="font-weight:bold; color:#111827;">${cumulative_value}</span>`;
            }

            if (cumulative_qty > 0) {
                const cumulative_value = default_formatter(cumulative_qty, row, column, data);
                return `<span style="font-weight:400; color:#9ca3af;">${cumulative_value}</span>`;
            } else {
                return `<span style="font-weight:400; color:#cbd5e1;">0</span>`;
            }
        }

        return default_formatter(value, row, column, data);
    }
};

function ptv_setup_month_shortcuts(report, prefix) {
    if (!ptv_is_mobile_width()) {
        report.page.add_inner_button(__("⬅️ 上一月"), function() {
            ptv_go_prev_month(report);
        });
        report.page.add_inner_button(__("📅 回当月"), function() {
            ptv_go_current_month(report);
        });
        report.page.add_inner_button(__("清空日期"), function() {
            ptv_clear_dates(report);
        });
    }

    if (ptv_is_mobile_width()) {
        ptv_inject_kiosk_css(prefix);
        ptv_inject_mobile_toolbar(report, prefix);
    }
}

function ptv_is_mobile_width() {
    return window.innerWidth < 768;
}

function ptv_inject_report_legend(report, prefix) {
    const legend_id = `${prefix}-legend`;
    const $wrapper = $(report.page.wrapper);

    $wrapper.find(`#${legend_id}`).remove();

    const legend_html = `
        <div id="${legend_id}" style="
            margin: 8px 0 12px 0;
            padding: 8px 12px;
            border: 1px solid #e5e7eb;
            border-radius: 6px;
            background: #f9fafb;
            color: #4b5563;
            font-size: 12px;
            line-height: 1.6;
        ">
            <span style="font-weight:700; color:#111827;">黑色加粗</span>：当前筛选日期范围内生产数量；清空日期后表示全部历史生产数量。
            <span style="margin-left:12px; color:#9ca3af;">浅灰数字</span>：当前范围内为 0；若数字大于 0，表示截至结束日已有历史报工累计。
            <span style="margin-left:12px; color:#cbd5e1;">浅灰 0</span>：截至结束日未找到该工作站报工。
        </div>
    `;

    const $report_wrapper = $wrapper.find(".report-wrapper").first();
    if ($report_wrapper.length) {
        $report_wrapper.before(legend_html);
    } else {
        $wrapper.find(".page-form").after(legend_html);
    }
}

function ptv_go_prev_month(report) {
    let current_from_str = report.get_filter_value("from_date");
    if (!current_from_str) {
        current_from_str = frappe.datetime.get_today();
    }

    const current_obj = frappe.datetime.str_to_obj(current_from_str);
    current_obj.setDate(1);
    current_obj.setMonth(current_obj.getMonth() - 1);

    const year = current_obj.getFullYear();
    const month = current_obj.getMonth();
    const first_day = new Date(year, month, 1);
    const last_day = new Date(year, month + 1, 0);

    report.set_filter_value("from_date", frappe.datetime.obj_to_str(first_day));
    report.set_filter_value("to_date", frappe.datetime.obj_to_str(last_day));
    report.refresh();
}

function ptv_go_current_month(report) {
    const today = new Date();
    const first_day = new Date(today.getFullYear(), today.getMonth(), 1);

    report.set_filter_value("from_date", frappe.datetime.obj_to_str(first_day));
    report.set_filter_value("to_date", frappe.datetime.obj_to_str(today));
    report.refresh();
}

function ptv_clear_dates(report) {
    report.set_filter_value("from_date", "");
    report.set_filter_value("to_date", "");
    report.refresh();
}

function ptv_inject_mobile_toolbar(report, prefix) {
    const toolbar_id = `${prefix}-toolbar`;
    const prev_btn_id = `${prefix}-prev-month`;
    const current_btn_id = `${prefix}-current-month`;
    const clear_btn_id = `${prefix}-clear-dates`;

    $(report.page.wrapper).find(`#${toolbar_id}`).remove();

    const toolbar_html = `
        <div id="${toolbar_id}" style="
            position: fixed;
            bottom: 20px;
            left: 0;
            width: 100%;
            display: flex;
            justify-content: center;
            gap: 8px;
            flex-wrap: wrap;
            padding: 0 12px;
            z-index: 9999;
            pointer-events: none;
        ">
            <button id="${prev_btn_id}" class="btn btn-default" style="
                pointer-events: auto;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                border-radius: 50px;
                padding: 10px 14px;
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
                padding: 10px 14px;
                font-weight: bold;
            ">
                📅 回当月
            </button>
            <button id="${clear_btn_id}" class="btn btn-default" style="
                pointer-events: auto;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                border-radius: 50px;
                padding: 10px 14px;
                background-color: white;
                border: 1px solid #d1d8dd;
                font-weight: bold;
                color: #555;
            ">
                清空日期
            </button>
        </div>
    `;

    $(report.page.wrapper).append(toolbar_html);

    $(report.page.wrapper).find(`#${prev_btn_id}`).on("click", function() {
        ptv_go_prev_month(report);
    });

    $(report.page.wrapper).find(`#${current_btn_id}`).on("click", function() {
        ptv_go_current_month(report);
    });

    $(report.page.wrapper).find(`#${clear_btn_id}`).on("click", function() {
        ptv_clear_dates(report);
    });
}

function ptv_inject_kiosk_css(prefix) {
    const css_id = `${prefix}-kiosk-css`;
    if ($(`#${css_id}`).length) {
        return;
    }

    const css = `
        @media only screen and (max-width: 767px) {
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
