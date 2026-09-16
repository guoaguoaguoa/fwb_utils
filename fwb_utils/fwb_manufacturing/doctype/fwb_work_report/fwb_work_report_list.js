// Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and contributors
// For license information, please see license.txt
//
// 生产报工表列表页(app/fwb-work-report/view/list)快捷筛选：
// - 报工日期：按 FWB Work Report.created_at 过滤（业务报工时间点，非单据建立时间 creation）
// - 工单日期：按本地快照字段 custom_work_order_date（=关联工单建立日期）过滤
// 两个维度各用一个 DateRange 控件（一个框选起止），与工单号/姓名/产品/工作站/是否返工等原生标准筛选并存。

frappe.listview_settings["FWB Work Report"] = {
	onload(listview) {
		if (listview._fwb_wr_quick_filters_setup) {
			return;
		}
		listview._fwb_wr_quick_filters_setup = true;

		// 必须把控件放进 .standard-filter-section（原生标准筛选所在的同一个 flex 容器）。
		// page.add_field(df, parent) 不传 parent 会落到 page_form，与该 section 成为兄弟节点；
		// section 是 flex:1 且 .form-group{min-width:150px}，被挤窄后原生筛选会竖着堆成一列（排版事故）。
		const filter_wrapper =
			listview.filter_area.standard_filters_wrapper ||
			listview.page.page_form.find(".standard-filter-section");

		const report_date_field = listview.page.add_field(
			{
				label: "报工日期",
				fieldtype: "DateRange",
				fieldname: "fwb_wr_report_date_range"
			},
			filter_wrapper
		);

		const wo_date_field = listview.page.add_field(
			{
				label: "工单日期",
				fieldtype: "DateRange",
				fieldname: "fwb_wr_wo_date_range"
			},
			filter_wrapper
		);

		const all_quick_fields = [report_date_field, wo_date_field];

		// 摘出：让这些自定义控件不进入原生 filter 收集器（get_standard_filters 会遍历所有 page 字段）。
		all_quick_fields.forEach((field) => {
			field._real_get_value = field.get_value.bind(field);
			field.get_value = function () {
				return null;
			};
		});

		// 本 JS 自己管理的过滤字段；重新套用前先移除它们，保留用户手动 Add Filter 的行。
		const controlled_filters = [
			["FWB Work Report", "created_at"],
			["FWB Work Report", "custom_work_order_date"]
		];

		let applying_quick_filters = Promise.resolve();

		const range_of = (field) => {
			const value = field._real_get_value();
			return Array.isArray(value) ? value : [];
		};

		const is_controlled_filter = (filter_value) => {
			return controlled_filters.some(([doctype, fieldname]) => {
				return filter_value[0] === doctype && filter_value[1] === fieldname;
			});
		};

		const remove_existing_quick_filters = () => {
			const filter_list = listview.filter_area.filter_list;
			filter_list.filters = filter_list.filters.filter((filter) => {
				const filter_value = filter.field && filter.get_value();
				const should_remove = filter_value && is_controlled_filter(filter_value);
				if (should_remove) {
					filter.remove();
					return false;
				}
				return true;
			});
			filter_list.update_filter_button();
			filter_list.filters.length === 0 && filter_list.toggle_empty_filters(true);
		};

		const apply_quick_filters = () => {
			const apply = () => {
				const [report_from, report_to] = range_of(report_date_field);
				const [wo_from, wo_to] = range_of(wo_date_field);

				remove_existing_quick_filters();

				const filters = [];
				if (report_from) {
					filters.push(["FWB Work Report", "created_at", ">=", `${report_from} 00:00:00`]);
				}
				if (report_to) {
					filters.push(["FWB Work Report", "created_at", "<=", `${report_to} 23:59:59`]);
				}
				if (wo_from) {
					filters.push(["FWB Work Report", "custom_work_order_date", ">=", wo_from]);
				}
				if (wo_to) {
					filters.push(["FWB Work Report", "custom_work_order_date", "<=", wo_to]);
				}

				return listview.filter_area.add(filters, false).then(() => {
					listview.start = 0;
					listview.refresh();
				});
			};

			applying_quick_filters = applying_quick_filters.then(apply, apply);
			return applying_quick_filters;
		};

		const clear_dates = () => {
			return frappe
				.run_serially(all_quick_fields.map((field) => () => field.set_value("")))
				.then(() => apply_quick_filters());
		};

		// 选完日期区间即重新套用。
		all_quick_fields.forEach((field) => {
			if (field.$input) {
				field.$input.on("change", () => {
					apply_quick_filters();
				});
			}
		});

		listview.page.add_inner_button("应用筛选", apply_quick_filters);
		listview.page.add_inner_button("清空日期", clear_dates);
	}
};
