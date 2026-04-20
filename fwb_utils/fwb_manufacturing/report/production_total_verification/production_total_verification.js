// v2026.01.10.01 - 生产总数核对报告前端配置

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
            "fieldtype": "Link",
            "options": "Work Order",
            "get_query": () => {
                // 仅允许选择未取消的工单
                return {
                    filters: { "docstatus": ["<", 2] }
                };
            }
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
    },

    // 格式化器：可以在这里给特定的单元格加颜色
    "formatter": function(value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);
        
        // 如果想高亮某些列，例如只要有数就变粗体
        if (["woodworking_qty", "primer_qty", "top_coat_qty", "assembly_qty", "polishing_qty", "lining_qty"].includes(column.fieldname)) {
            if (data[column.fieldname] > 0) {
                value = `<span style="font-weight:bold; color:#2c3e50;">${value}</span>`;
            } else {
                value = `<span style="color:#bdc3c7;">0</span>`;
            }
        }
        
        return value;
    }
};

function ptv_setup_month_shortcuts(report, prefix) {
    if (window.innerWidth >= 992) {
        report.page.add_inner_button(__("⬅️ 上一月"), function() {
            ptv_go_prev_month(report);
        });
        report.page.add_inner_button(__("📅 回当月"), function() {
            ptv_go_current_month(report);
        });
    }

    if (window.innerWidth < 992) {
        ptv_inject_kiosk_css(prefix);
        ptv_inject_mobile_toolbar(report, prefix);
    }
}

function ptv_go_prev_month(report) {
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

function ptv_go_current_month(report) {
    const today = new Date();
    const first_day = new Date(today.getFullYear(), today.getMonth(), 1);

    report.set_filter_value("from_date", frappe.datetime.obj_to_str(first_day));
    report.set_filter_value("to_date", frappe.datetime.obj_to_str(today));
    report.refresh();
}

function ptv_inject_mobile_toolbar(report, prefix) {
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
        ptv_go_prev_month(report);
    });

    $(report.page.wrapper).find(`#${current_btn_id}`).on("click", function() {
        ptv_go_current_month(report);
    });
}

function ptv_inject_kiosk_css(prefix) {
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
