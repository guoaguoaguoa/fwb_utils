// v2025.12.10.02 - Factory Control Tower client
// - 顶部增加日期区间过滤
// - KPI：工单总数 / 待产盒数 / 产量 / 次品率 / 计件工资合计
// - 左侧：物料齐套进度（按工单）
// - 右侧：交期预警（未来 7 天）
// - 下方：生产总览（按工站拆成多个小面板，2 列布局）

frappe.provide("fwb_utils.factory_control_towe");

frappe.pages["factory-control-towe"].on_page_load = function (wrapper) {
    console.log(">>> Factory Control Tower page loaded");

    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: "工厂总览",
        single_column: true,
    });

    build_layout(page);
    init_date_filters(page);
    load_dashboard_data(page);
};

function build_layout(page) {
    const $main = $(page.main);

    $main.empty().append(`
        <div class="fct-container">
            <div class="fct-header">
                <div class="fct-title-block">
                    <h2 class="fct-title">工厂总览</h2>
                    <div class="fct-subtitle">关键生产与物料状态一目了然</div>
                </div>
                <div class="fct-actions">
                    <div class="fct-filter-group">
                        <span class="fct-filter-label">产品名</span>
                        <input type="text"
                               class="form-control input-sm fct-product-name"
                               placeholder="支持模糊搜索">
                    </div>
                    <div class="fct-filter-group fct-sample-filter"
                         title="0 不过滤；输入 N 后隐藏工单数小于等于 N 的工单">
                        <span class="fct-filter-label">样品阈值</span>
                        <input type="number"
                               min="0"
                               step="1"
                               value="0"
                               class="form-control input-sm fct-sample-threshold">
                        <span class="fct-filter-hint">0 不过滤；输入 N 隐藏 ≤ N</span>
                    </div>
                    <input type="date" class="form-control input-sm fct-date-input fct-date-from">
                    <span class="fct-date-sep">至</span>
                    <input type="date" class="form-control input-sm fct-date-input fct-date-to">
                    <button class="btn btn-default btn-sm fct-prev-month">
                        上一月
                    </button>
                    <button class="btn btn-default btn-sm fct-current-month">
                        回当月
                    </button>
                    <button class="btn btn-default btn-sm fct-apply-range">
                        应用
                    </button>
                    <button class="btn btn-primary btn-sm fct-refresh-btn">
                        刷新
                    </button>
                </div>
            </div>

            <div class="fct-kpi-row">
                <div class="fct-kpi-card" data-kpi="work-orders">
                    <div class="fct-kpi-label">工单总数</div>
                    <div class="fct-kpi-value" data-field="work_order_total">-</div>
                    <div class="fct-kpi-desc">
                        已完成：<span data-field="work_order_completed">-</span>，
                        未完成：<span data-field="work_order_unfinished">-</span>
                    </div>
                </div>

                <div class="fct-kpi-card" data-kpi="pending-box">
                    <div class="fct-kpi-label">待产盒数</div>
                    <div class="fct-kpi-value" data-field="pending_box_qty">-</div>
                    <div class="fct-kpi-desc">
                        已完成盒数：<span data-field="completed_box_qty">-</span>
                    </div>
                </div>

                <div class="fct-kpi-card" data-kpi="output">
                    <div class="fct-kpi-label">产量</div>
                    <div class="fct-kpi-value" data-field="range_output_qty">-</div>
                    <div class="fct-kpi-desc">
                        统计区间内有效产量
                    </div>
                </div>

                <div class="fct-kpi-card" data-kpi="defect">
                    <div class="fct-kpi-label">次品率</div>
                    <div class="fct-kpi-value" data-field="range_defect_rate">-</div>
                    <div class="fct-kpi-desc">
                        区间内所有工站的综合次品率
                    </div>
                </div>

                <div class="fct-kpi-card" data-kpi="wage">
                    <div class="fct-kpi-label">工资合计</div>
                    <div class="fct-kpi-value" data-field="range_wage_amount">-</div>
                    <div class="fct-kpi-desc">
                        统计区间内工资合计
                    </div>
                </div>
            </div>

            <div class="fct-grid-row">
                <div class="fct-panel fct-panel-half" data-panel="mrc">
                    <div class="fct-panel-header">
                        <div class="fct-panel-title">物料齐套进度</div>
                        <div class="fct-panel-subtitle">每个工单的物料齐套完成度</div>
                    </div>
                    <div class="fct-panel-body">
                        <div class="fct-table-wrapper">
                            <table class="table table-condensed table-bordered fct-table">
                                <thead>
                                    <tr>
                                        <th style="width: 40%;">产品名</th>
                                        <th style="width: 12%;">数量</th>
                                        <th style="width: 38%;">齐套进度</th>
                                        <th style="width: 10%;">打开</th>
                                    </tr>
                                </thead>
                                <tbody data-body="mrc-list">
                                    <tr>
                                        <td colspan="4" class="text-muted text-center">
                                            正在加载物料齐套数据...
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>

                <div class="fct-panel fct-panel-half" data-panel="due-warning">
                    <div class="fct-panel-header">
                        <div class="fct-panel-title">交期预警</div>
                        <div class="fct-panel-subtitle">未来 7 天内即将到期的工单</div>
                    </div>
                    <div class="fct-panel-body">
                        <div class="fct-table-wrapper">
                            <table class="table table-condensed table-bordered fct-table">
                                <thead>
                                    <tr>
                                        <th style="width: 13%;">开单日期</th>
                                        <th style="width: 15%;">交货日期</th>
                                        <th style="width: 20%;">工单号</th>
                                        <th style="width: 30%;">产品名</th>
                                        <th style="width: 12%;">数量</th>
                                        <th style="width: 10%;">状态</th>
                                    </tr>
                                </thead>
                                <tbody data-body="due-warning">
                                    <tr>
                                        <td colspan="6" class="text-muted text-center">
                                            正在加载交期预警数据...
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>

            <div class="fct-grid-row">
                <div class="fct-panel fct-panel-full" data-panel="stage-overview">
                    <div class="fct-panel-header">
                        <div class="fct-panel-title">工单阶段</div>
                        <div class="fct-panel-subtitle">按工单查看当前工序、流转等待与异常提示</div>
                    </div>
                    <div class="fct-panel-body">
                        <div class="fct-table-wrapper">
                            <table class="table table-condensed table-bordered fct-table">
                                <thead>
                                    <tr>
                                        <th style="width: 16%;">工单号</th>
                                        <th style="width: 32%;">产品名</th>
                                        <th style="width: 10%;">工单数</th>
                                        <th style="width: 12%;">当前阶段</th>
                                        <th style="width: 14%;">流转等待</th>
                                        <th style="width: 16%;">整体提示</th>
                                    </tr>
                                </thead>
                                <tbody data-body="stage-overview">
                                    <tr>
                                        <td colspan="6" class="text-muted text-center">
                                            正在加载工单阶段数据...
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>

            <div class="fct-grid-row">
                <div class="fct-panel fct-panel-full" data-panel="workstation-progress">
                    <div class="fct-panel-header">
                        <div class="fct-panel-title">生产总览</div>
                        <div class="fct-panel-subtitle" data-field="range-label">
                            统计最近 7 天的生产报工
                        </div>
                    </div>
                    <div class="fct-panel-body">
                        <div class="fct-ws-grid" data-panel="ws-grid">
                            <!-- 各工站小面板由 JS 渲染 -->
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `);

    inject_factory_control_css();

    const $actions = $main.find(".fct-actions");

    $actions.find(".fct-prev-month").on("click", function () {
        go_prev_month(page);
    });

    $actions.find(".fct-current-month").on("click", function () {
        go_current_month(page);
    });

    $actions.find(".fct-product-name, .fct-sample-threshold").on("keydown", function (event) {
        if (event.key === "Enter") {
            load_dashboard_data(page);
        }
    });

    // 应用：使用当前选择的日期区间
    $actions.find(".fct-apply-range").on("click", function () {
        load_dashboard_data(page);
    });

    // 刷新：重置为最近 7 天并重新加载
    $actions.find(".fct-refresh-btn").on("click", function () {
        init_date_filters(page);
        load_dashboard_data(page);
    });
}

function init_date_filters(page) {
    const $main = $(page.main);
    const today = frappe.datetime.get_today();
    const from = frappe.datetime.add_days(today, -6);

    $main.find(".fct-date-to").val(today);
    $main.find(".fct-date-from").val(from);
}

function go_prev_month(page) {
    const $main = $(page.main);
    let current_from = $main.find(".fct-date-from").val();
    if (!current_from) {
        current_from = frappe.datetime.get_today();
    }

    const current_obj = frappe.datetime.str_to_obj(current_from);
    current_obj.setDate(1);
    current_obj.setMonth(current_obj.getMonth() - 1);

    const year = current_obj.getFullYear();
    const month = current_obj.getMonth();
    const first_day = new Date(year, month, 1);
    const last_day = new Date(year, month + 1, 0);

    $main.find(".fct-date-from").val(frappe.datetime.obj_to_str(first_day));
    $main.find(".fct-date-to").val(frappe.datetime.obj_to_str(last_day));
    load_dashboard_data(page);
}

function go_current_month(page) {
    const $main = $(page.main);
    const today = new Date();
    const first_day = new Date(today.getFullYear(), today.getMonth(), 1);

    $main.find(".fct-date-from").val(frappe.datetime.obj_to_str(first_day));
    $main.find(".fct-date-to").val(frappe.datetime.obj_to_str(today));
    load_dashboard_data(page);
}

function inject_factory_control_css() {
    if ($("#fct-style").length) return;

    const css = `
    .fct-container {
        padding: 10px 15px 25px 15px;
    }
    .fct-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 12px;
        gap: 8px;
    }
    .fct-title {
        margin: 0;
        font-size: 22px;
        font-weight: 600;
    }
    .fct-subtitle {
        font-size: 12px;
        color: #888;
        margin-top: 3px;
    }
    .fct-actions {
        display: flex;
        align-items: center;
        gap: 6px;
        flex-wrap: wrap;
        justify-content: flex-end;
    }
    .fct-filter-group {
        display: flex;
        align-items: center;
        gap: 4px;
        min-height: 30px;
    }
    .fct-filter-label,
    .fct-filter-hint {
        font-size: 12px;
        color: #64748b;
        white-space: nowrap;
    }
    .fct-product-name {
        width: 150px;
    }
    .fct-sample-threshold {
        width: 76px;
    }
    .fct-filter-hint {
        color: #94a3b8;
    }
    .fct-date-input {
        width: 130px;
    }
    .fct-date-sep {
        font-size: 12px;
        color: #666;
    }
    .fct-kpi-row {
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        margin-bottom: 16px;
    }
    .fct-kpi-card {
        flex: 1 1 190px;
        background: #fff;
        border-radius: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06);
        padding: 10px 12px;
        border: 1px solid #e5e5e5;
    }
    .fct-kpi-label {
        font-size: 12px;
        color: #666;
        margin-bottom: 4px;
    }
    .fct-kpi-value {
        font-size: 22px;
        font-weight: 600;
        margin-bottom: 2px;
    }
    .fct-kpi-desc {
        font-size: 11px;
        color: #999;
    }
    .fct-grid-row {
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        margin-bottom: 16px;
    }
    .fct-panel {
        background: #fff;
        border-radius: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06);
        border: 1px solid #e5e5e5;
        display: flex;
        flex-direction: column;
    }
    .fct-panel-half {
        flex: 1 1 48%;
    }
    .fct-panel-full {
        flex: 1 1 100%;
    }
    .fct-panel-header {
        padding: 8px 12px 4px 12px;
        border-bottom: 1px solid #f0f0f0;
    }
    .fct-panel-title {
        font-size: 14px;
        font-weight: 600;
        margin-bottom: 2px;
    }
    .fct-panel-subtitle {
        font-size: 11px;
        color: #999;
    }
    .fct-panel-body {
        padding: 6px 10px 8px 10px;
    }
    .fct-table-wrapper {
        max-height: 310px;
        overflow-y: auto;
    }
    .fct-table th,
    .fct-table td {
        font-size: 12px;
    }
    .fct-progress {
        position: relative;
        width: 100%;
        height: 12px;
        border-radius: 8px;
        background: #f1f1f1;
        overflow: hidden;
    }
    .fct-progress-bar {
        position: absolute;
        left: 0;
        top: 0;
        bottom: 0;
        width: 0;
        transition: width 0.4s ease;
    }
    .fct-progress-label {
        font-size: 11px;
        color: #555;
        margin-top: 2px;
    }
    .fct-badge-link a {
        font-size: 11px;
    }
    .fct-muted-qty {
        color: #9ca3af;
        font-weight: 400;
    }
    .fct-stage-tip {
        display: inline-block;
        padding: 1px 6px;
        border-radius: 999px;
        background: #f3f4f6;
        color: #4b5563;
        font-size: 11px;
    }
    .fct-stage-tip-warning {
        background: #fff7ed;
        color: #c2410c;
    }
    .fct-ws-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 12px;
    }
    .fct-ws-panel-title {
        font-size: 13px;
        font-weight: 600;
        margin-bottom: 4px;
    }
    .fct-ws-panel-subtitle {
        font-size: 11px;
        color: #999;
        margin-bottom: 4px;
    }
    @media (max-width: 1100px) {
        .fct-ws-grid {
            grid-template-columns: repeat(1, minmax(0, 1fr));
        }
    }
    @media (max-width: 900px) {
        .fct-header {
            flex-direction: column;
            align-items: flex-start;
        }
        .fct-actions {
            justify-content: flex-start;
        }
        .fct-kpi-row {
            flex-direction: column;
        }
        .fct-grid-row {
            flex-direction: column;
        }
    }
    `;

    $("<style id='fct-style'>").text(css).appendTo("head");
}

function load_dashboard_data(page) {
    const $main = $(page.main);
    const from_date = $main.find(".fct-date-from").val();
    const to_date = $main.find(".fct-date-to").val();
    const product_name = ($main.find(".fct-product-name").val() || "").trim();
    const sample_qty_threshold = get_sample_qty_threshold($main);

    frappe.dom.freeze("正在加载工厂总览数据...");

    frappe.call({
        method: "fwb_utils.fwb_manufacturing.page.factory_control_towe.factory_control_towe.get_dashboard_data",
        args: {
            from_date: from_date,
            to_date: to_date,
            product_name: product_name,
            sample_qty_threshold: sample_qty_threshold,
        },
        callback: function (r) {
            frappe.dom.unfreeze();

            if (!r.message) {
                frappe.msgprint("未能获取工厂总览数据。");
                return;
            }

            const data = r.message;

            try {
                render_kpi_block($main, data.kpi || {});
                render_mrc_list($main, data.mrc_list || []);
                render_due_warning($main, data.due_warning || []);
                render_stage_overview($main, data.stage_overview || []);
                render_workstation_progress($main, data.workstation_progress || {}, data.kpi || {});
            } catch (e) {
                console.error("Error rendering Factory Control Tower:", e);
                frappe.msgprint("渲染总控台时发生错误，请查看控制台日志。");
            }
        },
        error: function () {
            frappe.dom.unfreeze();
            frappe.msgprint("获取工厂总览数据失败。");
        },
    });
}

function get_sample_qty_threshold($root) {
    const rawValue = $root.find(".fct-sample-threshold").val();
    const threshold = parseFloat(rawValue);

    if (!isFinite(threshold) || threshold <= 0) {
        return 0;
    }

    return threshold;
}

function render_kpi_block($root, kpi) {
    const $kpis = $root.find(".fct-kpi-card");

    $kpis.find("[data-field='work_order_total']").text(kpi.work_order_total || 0);
    $kpis.find("[data-field='work_order_completed']").text(kpi.work_order_completed || 0);
    $kpis.find("[data-field='work_order_unfinished']").text(kpi.work_order_unfinished || 0);

    const pending_box = parseFloat(kpi.pending_box_qty || 0) || 0;
    const completed_box = parseFloat(kpi.completed_box_qty || 0) || 0;
    $kpis.find("[data-field='pending_box_qty']").text(pending_box.toFixed(0));
    $kpis.find("[data-field='completed_box_qty']").text(completed_box.toFixed(0));

    const output = parseFloat(kpi.range_output_qty || 0) || 0;
    const defect_rate = parseFloat(kpi.range_defect_rate || 0) || 0;
    const wage = parseFloat(kpi.range_wage_amount || 0) || 0;

    $kpis.find("[data-field='range_output_qty']").text(
        output % 1 === 0 ? output.toFixed(0) : output.toFixed(2)
    );
    $kpis.find("[data-field='range_defect_rate']").text(defect_rate.toFixed(2) + "%");
    $kpis.find("[data-field='range_wage_amount']").text("¥ " + wage.toFixed(2));

    const rangeLabel =
        kpi.from_date && kpi.to_date
            ? `统计区间：${kpi.from_date} 至 ${kpi.to_date}`
            : "";

    if (rangeLabel) {
        $root.find("[data-field='range-label']").text(rangeLabel);
    }
}

function render_mrc_list($root, list) {
    const $tbody = $root.find("tbody[data-body='mrc-list']");
    $tbody.empty();

    if (!list.length) {
        $tbody.append(`
            <tr>
                <td colspan="4" class="text-muted text-center">
                    当前没有物料齐套单。
                </td>
            </tr>
        `);
        return;
    }

    list.forEach(function (row) {
        let pct = parseFloat(row.progress_percent || 0);
        if (pct < 0) pct = 0;
        if (pct > 100) pct = 100;

        let color;
        if (pct >= 99.9) {
            color = "#4caf50";
        } else if (pct <= 40) {
            color = "#f44336";
        } else {
            color = "#ff9800";
        }

        const pct_txt = pct.toFixed(1).replace(/\.0$/, "") + "%";

        const $tr = $(`
            <tr>
                <td>${frappe.utils.escape_html(row.product_name || "")}</td>
                <td style="text-align:right;">${row.product_qty || 0}</td>
                <td>
                    <div class="fct-progress">
                        <div class="fct-progress-bar" style="background:${color}; width: ${pct}%"></div>
                    </div>
                    <div class="fct-progress-label">
                        ${pct_txt} （齐套 ${row.ok_rows || 0} / 共 ${row.total_rows || 0} 行）
                    </div>
                </td>
                <td class="fct-badge-link">
                    <a href="${row.url || "#"}" class="btn btn-xs btn-default" target="_blank">
                        打开
                    </a>
                </td>
            </tr>
        `);

        $tbody.append($tr);
    });
}

function render_due_warning($root, list) {
    const $tbody = $root.find("tbody[data-body='due-warning']");
    $tbody.empty();

    if (!list.length) {
        $tbody.append(`
            <tr>
                <td colspan="6" class="text-muted text-center">
                    未来 7 天内暂无交期预警工单。
                </td>
            </tr>
        `);
        return;
    }

    list.forEach(function (row) {
        const url = row.url || "#";
        const qty = parseFloat(row.qty || 0) || 0;

        const $tr = $(`
            <tr>
                <td>${frappe.utils.escape_html(row.order_date || "")}</td>
                <td>${frappe.utils.escape_html(row.expected_delivery_date || "")}</td>
                <td>
                    <a href="${url}" target="_blank">
                        ${frappe.utils.escape_html(row.work_order || "")}
                    </a>
                </td>
                <td>${frappe.utils.escape_html(row.item_name || "")}</td>
                <td style="text-align:right;">${qty.toFixed(0)}</td>
                <td>${frappe.utils.escape_html(row.stage || "")}</td>
            </tr>
        `);

        $tbody.append($tr);
    });
}

function render_stage_overview($root, list) {
    const $tbody = $root.find("tbody[data-body='stage-overview']");
    $tbody.empty();

    if (!list.length) {
        $tbody.append(`
            <tr>
                <td colspan="6" class="text-muted text-center">
                    当前统计区间内暂无工单阶段数据。
                </td>
            </tr>
        `);
        return;
    }

    list.forEach(function (row) {
        const qty = parseFloat(row.work_order_qty || 0) || 0;
        const tip = row.overall_tip || "";
        const tip_class = tip === "部分流转" ? "fct-stage-tip fct-stage-tip-warning" : "fct-stage-tip";

        $tbody.append(`
            <tr>
                <td>
                    <a href="${row.work_order_url || "#"}" target="_blank">
                        ${frappe.utils.escape_html(row.work_order || "")}
                    </a>
                </td>
                <td>${frappe.utils.escape_html(row.product_name || "")}</td>
                <td style="text-align:right;">${qty.toFixed(0)}</td>
                <td>${frappe.utils.escape_html(row.current_stage || "")}</td>
                <td>${frappe.utils.escape_html(row.flow_wait || "")}</td>
                <td><span class="${tip_class}">${frappe.utils.escape_html(tip)}</span></td>
            </tr>
        `);
    });
}

function render_workstation_progress($root, wsProgress, kpi) {
    const $grid = $root.find(".fct-ws-grid");
    $grid.empty();

    const rangeLabel =
        kpi && kpi.from_date && kpi.to_date
            ? `统计区间：${kpi.from_date} 至 ${kpi.to_date}`
            : null;
    if (rangeLabel) {
        $root.find("[data-field='range-label']").text(rangeLabel);
    }

    const order = [
        "木工进度",
        "裱纸进度",
        "贴皮进度",
        "底漆进度",
        "面漆进度",
        "抛光进度",
        "装配进度",
        "软包进度",
        "打包进度",
    ];

    let hasAny = false;

    order.forEach(function (label) {
        const list = wsProgress[label] || [];
        if (!list.length) {
            return;
        }
        hasAny = true;

        let rowsHtml = "";
        list.forEach(function (row) {
            const wo_qty = parseFloat(row.work_order_qty || 0) || 0;
            const reported = parseFloat(row.reported_qty || 0) || 0;
            const cumulative = parseFloat(row.cumulative_reported_qty || 0) || 0;
            const defect_qty = parseFloat(row.defect_qty || 0) || 0;

            // 完成度 = 已报工数 / 工单数
            let completion = 0;
            if (wo_qty > 0) {
                completion = (reported * 100.0) / wo_qty;
            }

            if (completion < 0) completion = 0;
            // 如果超太多，最大宽度限制一下，防止进度条撑爆
            if (completion > 200) completion = 200;

            // 颜色：红-橙-黄-绿（按完成度）
            let color;
            if (completion >= 100) {
                color = "#4caf50"; // 绿：已完成或超额
            } else if (completion >= 80) {
                color = "#ffeb3b"; // 黄：80% 以上
            } else if (completion >= 50) {
                color = "#ff9800"; // 橙：50%~80%
            } else {
                color = "#f44336"; // 红：50% 以下
            }

            const completion_txt = completion.toFixed(1).replace(/\.0$/, "") + "%";
            const over_qty = reported - wo_qty;
            const cumulative_over_qty = cumulative - wo_qty;
            const extra_text =
                over_qty > 0
                    ? `（超出 ${over_qty.toFixed(0)} 件）`
                    : cumulative_over_qty > 0
                    ? `（累计超出 ${cumulative_over_qty.toFixed(0)} 件）`
                    : "";
            const reported_class = reported <= 0 && cumulative > 0 ? "fct-muted-qty" : "";
            const cumulative_class = reported <= 0 && cumulative > 0 ? "fct-muted-qty" : "";

            rowsHtml += `
                <tr>
                    <td>${frappe.utils.escape_html(row.order_date || "")}</td>
                    <td>
                        <a href="#"
                           class="fct-ws-link"
                           data-work-order="${frappe.utils.escape_html(row.work_order || "")}"
                           data-workstation="${frappe.utils.escape_html(row.workstation || "")}">
                            ${frappe.utils.escape_html(row.product_name || "")}
                        </a>
                    </td>
                    <td style="text-align:right;">${wo_qty.toFixed(0)}</td>
                    <td style="text-align:right;" class="${reported_class}">${reported.toFixed(0)}</td>
                    <td style="text-align:right;" class="${cumulative_class}">${cumulative.toFixed(0)}</td>
                    <td style="text-align:right;">${defect_qty.toFixed(0)}</td>
                    <td>
                        <div class="fct-progress">
                            <div class="fct-progress-bar" style="background:${color}; width:${completion}%;"></div>
                        </div>
                        <div class="fct-progress-label">
                            完成度：${completion_txt}${extra_text}
                        </div>
                    </td>
                </tr>
            `;
        });

        const $panel = $(`
            <div class="fct-ws-panel">
                <div class="fct-ws-panel-title">${label}</div>
                <div class="fct-ws-panel-subtitle">
                    按工单汇总报工数与进度
                </div>
                <div class="fct-table-wrapper">
                    <table class="table table-condensed table-bordered fct-table">
                        <thead>
                            <tr>
                                <th style="width: 14%;">工单日期</th>
                                <th style="width: 24%;">产品名</th>
                                <th style="width: 12%;">工单数</th>
                                <th style="width: 12%;">本期报工</th>
                                <th style="width: 12%;">截至累计</th>
                                <th style="width: 12%;">次品数</th>
                                <th style="width: 14%;">进度</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${
                                rowsHtml ||
                                `
                                <tr>
                                    <td colspan="7" class="text-muted text-center">
                                        暂无数据。
                                    </td>
                                </tr>
                                `
                            }
                        </tbody>
                    </table>
                </div>
            </div>
        `);

        $grid.append($panel);
    });

    // 点击产品名，跳转到 FWB Work Report 列表（带工单 + 工站过滤）
    $grid.off("click", ".fct-ws-link").on("click", ".fct-ws-link", function (e) {
        e.preventDefault();
        const $a = $(this);
        const work_order = $a.data("work-order");
        const workstation = $a.data("workstation");
        if (!work_order || !workstation) return;

        frappe.set_route("List", "FWB Work Report", {
            work_order: work_order,
            workstation: workstation,
        });
    });


    if (!hasAny) {
        $grid.append(`
            <div class="text-muted" style="font-size:12px;">
                当前统计区间内暂无生产报工数据。
            </div>
        `);
    }
}
