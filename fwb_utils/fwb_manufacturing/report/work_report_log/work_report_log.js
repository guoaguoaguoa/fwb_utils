// v2026.05.05.01 - 工人/管理双视图报工记录

const WORK_REPORT_LOG_MANAGER_ROLES = [
    "Administrator",
    "HR Manager",
    "Manufacturing Manager",
    "Quality Manager",
    "Stock Manager",
    "Sales Master Manager",
    "Purchase Master Manager"
];

frappe.query_reports["Work Report Log"] = {
    "filters": get_work_report_log_filters(),

    "onload": function(report) {
        // === 1. 电脑端逻辑 ===
        if (window.innerWidth >= 992) {
            // PC 端也同步加上这两个逻辑的按钮
            report.page.add_inner_button(__("⬅️ 上一月"), function() {
                go_prev_month(report);
            });
            report.page.add_inner_button(__("📅 回当月"), function() {
                go_current_month(report);
            });
        }

        // === 2. 手机端逻辑 (底部悬浮按钮) ===
        if (window.innerWidth < 992) {
            // 注入防误触 CSS (隐藏顶部菜单)
            inject_kiosk_css();

            // 注入底部自定义按钮栏
            inject_mobile_toolbar(report);
        }

        // === 3. 备注点击弹出完整内容（委托绑定，翻页/重渲染后仍有效）===
        bind_remark_popup(report);
    },
    
    // 3. 整行配色（口径同 salary_slip.js）：罚款/计时蓝，红/蓝 token 由服务端 _style 决定。
    //    备注列：内容常被列宽截断，做成可点击、点开弹出完整备注（见 onload 的委托点击）。
    "formatter": function(value, row, column, data, default_formatter) {
        if (column.fieldname === "remarks" && data && data.remarks) {
            const enc = encodeURIComponent(data.remarks);
            value = `<span class="wrl-remark" data-remark="${enc}" `
                  + `title="${__("点击查看完整备注")}" `
                  + `style="cursor:pointer;border-bottom:1px dashed currentColor;">`
                  + `${frappe.utils.escape_html(data.remarks)}</span>`;
        } else {
            value = default_formatter(value, row, column, data);
        }

        if (data && data._style === "red") {
            return `<span style="color:#c62828;font-weight:700;">${value}</span>`;
        }
        if (data && data._style === "blue") {
            return `<span style="color:#0066cc;font-weight:600;">${value}</span>`;
        }
        return value;
    },

    // 合计由服务端按带符号金额追加（罚款/扣款为负），关掉 datatable 自带 sumRow 防重复。
    "get_datatable_options": function(options) {
        return Object.assign(options, {
            sumRow: false
        });
    }
};

function get_work_report_log_filters() {
    const filters = [
        {
            "fieldname": "from_date",
            "label": __("开始于"),
            "fieldtype": "Date",
            "default": frappe.datetime.get_today().substring(0, 8) + "01",
            "reqd": 1
        },
        {
            "fieldname": "to_date",
            "label": __("结束于"),
            "fieldtype": "Date",
            "default": frappe.datetime.get_today(),
            "reqd": 1
        },
        {
            "fieldname": "product_name",
            "label": __("产品"),
            "fieldtype": "Data"
        },
        {
            "fieldname": "work_order",
            "label": __("工单"),
            "fieldtype": "Link",
            "options": "Work Order"
        }
    ];

    if (frappe.user.has_role(WORK_REPORT_LOG_MANAGER_ROLES)) {
        filters.push(
            {
                "fieldname": "employee_name",
                "label": __("员工(ID/姓名)"),
                "fieldtype": "Data"
            },
            {
                "fieldname": "workstation",
                "label": __("工作站"),
                "fieldtype": "Link",
                "options": "Workstation"
            }
        );
    }

    return filters;
}

// ==========================================
// 核心逻辑函数
// ==========================================

// 逻辑：基于【当前筛选器里的开始日期】往前推一个月 (实现无限回溯)
function go_prev_month(report) {
    // 1. 获取当前筛选器里的 "开始日期"
    let current_from_str = report.get_filter_value("from_date");
    if (!current_from_str) current_from_str = frappe.datetime.get_today();

    // 2. 转成日期对象
    let currentObj = frappe.datetime.str_to_obj(current_from_str);

    // 3. 核心：月份减 1
    // JS 的 setMonth 会自动处理跨年（比如 1月减1变成去年的12月）
    currentObj.setMonth(currentObj.getMonth() - 1);

    // 4. 计算那个月的第一天和最后一天
    const year = currentObj.getFullYear();
    const month = currentObj.getMonth(); // 注意：0=1月, 11=12月

    const firstDay = new Date(year, month, 1);
    const lastDay = new Date(year, month + 1, 0); // 下个月的第0天 = 本月最后一天

    // 5. 赋值并刷新
    report.set_filter_value("from_date", frappe.datetime.obj_to_str(firstDay));
    report.set_filter_value("to_date", frappe.datetime.obj_to_str(lastDay));
    report.refresh();
}

// 逻辑：直接重置为【本月1号 ~ 今天】
function go_current_month(report) {
    const today = new Date();
    // 本月1号
    const firstDay = new Date(today.getFullYear(), today.getMonth(), 1);
    
    // 结束日期设为今天（实时看截止目前的）
    const toDate = today;

    report.set_filter_value("from_date", frappe.datetime.obj_to_str(firstDay));
    report.set_filter_value("to_date", frappe.datetime.obj_to_str(toDate));
    report.refresh();
}

// ==========================================
// UI 注入函数
// ==========================================

function inject_mobile_toolbar(report) {
    if ($('#custom-mobile-toolbar').length > 0) return;

    const toolbarHtml = `
        <div id="custom-mobile-toolbar" style="
            position: fixed;
            bottom: 20px;
            left: 0;
            width: 100%;
            display: flex;
            justify-content: center;
            gap: 20px; /* 增加一点间距 */
            z-index: 9999;
            pointer-events: none;
        ">
            <button id="btn-prev-month" class="btn btn-default" style="
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

            <button id="btn-this-month" class="btn btn-primary" style="
                pointer-events: auto;
                box-shadow: 0 4px 12px rgba(0,0,0,0.2);
                border-radius: 50px;
                padding: 10px 20px;
                font-weight: bold;
            ">
                📅 当 月
            </button>
        </div>
    `;

    $('body').append(toolbarHtml);

    // 绑定事件
    $('#btn-prev-month').on('click', function() {
        go_prev_month(report);
    });

    $('#btn-this-month').on('click', function() {
        go_current_month(report);
    });
}

function inject_kiosk_css() {
    const css = `
        @media only screen and (max-width: 992px) {
            /* 隐藏右上角操作区 */
            .page-actions { display: none !important; }
            /* 禁用 Logo */
            .navbar-brand, .navbar-home { pointer-events: none !important; opacity: 0.3; }
            /* 隐藏搜索 */
            .navbar-center, .navbar-search, .search-bar, form[role="search"] { display: none !important; }
            /* 底部留白 */
            .report-view { padding-bottom: 90px !important; }
        }
    `;
    if (!$('#report-kiosk-css').length) {
        $('<style id="report-kiosk-css">' + css + '</style>').appendTo('head');
    }
}

// 备注列内容常被列宽截断，工人看不全被扣原因。这里用「委托点击」在整个报表容器上监听
// .wrl-remark（由 formatter 渲染），点击后弹出小窗显示完整备注。委托绑定不受翻页/重渲染影响。
function bind_remark_popup(report) {
    const $wrapper = $(report.page.wrapper);
    $wrapper.off('click.wrlRemark').on('click.wrlRemark', '.wrl-remark', function(e) {
        e.stopPropagation();
        const enc = $(this).attr('data-remark');
        if (!enc) return;
        let full = '';
        try {
            full = decodeURIComponent(enc);
        } catch (err) {
            full = enc;
        }
        frappe.msgprint({
            title: __('备注详情'),
            indicator: 'blue',
            message: `<div style="white-space:pre-wrap;word-break:break-word;">${frappe.utils.escape_html(full)}</div>`
        });
    });
}
