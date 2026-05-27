// Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and contributors
// For license information, please see license.txt

frappe.listview_settings["Rework Record"] = {
	onload(listview) {
		if (listview._fwb_rework_quick_filters_setup) {
			return;
		}
		listview._fwb_rework_quick_filters_setup = true;

		const start_date_field = listview.page.add_field({
			label: "开始时间",
			fieldtype: "Date",
			fieldname: "fwb_rework_start_date_filter"
		});

		const end_date_field = listview.page.add_field({
			label: "结束时间",
			fieldtype: "Date",
			fieldname: "fwb_rework_end_date_filter"
		});

		const employee_name_field = listview.page.add_field({
			label: "责任人姓名",
			fieldtype: "Data",
			fieldname: "fwb_rework_employee_name_filter"
		});

		const inspector_name_field = listview.page.add_field({
			label: "质检员姓名",
			fieldtype: "Data",
			fieldname: "fwb_rework_inspector_name_filter"
		});

		const workstation_field = listview.page.add_field({
			label: "工作站",
			fieldtype: "Link",
			options: "Workstation",
			fieldname: "fwb_rework_workstation_filter"
		});

		const product_name_field = listview.page.add_field({
			label: "产品名",
			fieldtype: "Data",
			fieldname: "fwb_rework_product_name_filter"
		});

		const work_report_field = listview.page.add_field({
			label: "对应的报工号",
			fieldtype: "Data",
			fieldname: "fwb_rework_work_report_filter"
		});

		const work_order_field = listview.page.add_field({
			label: "生产工单号",
			fieldtype: "Data",
			fieldname: "fwb_rework_work_order_filter"
		});

		// Detach all quick-filter controls from the standard collector so that they
		// never leak into the default listview filter pipeline.
		const all_quick_fields = [
			start_date_field,
			end_date_field,
			employee_name_field,
			inspector_name_field,
			workstation_field,
			product_name_field,
			work_report_field,
			work_order_field
		];
		all_quick_fields.forEach((field) => {
			field._real_get_value = field.get_value.bind(field);
			field.get_value = function () {
				return null;
			};
		});

		// The DocType-level fields we ourselves manage. Anything in this list will
		// be removed before a re-apply so user-driven Add Filter rows remain intact.
		const controlled_filters = [
			["Rework Record", "created_at"],
			["Rework Record", "employee_name_display"],
			["Rework Record", "inspector_name_display"],
			["Rework Record", "workstation"],
			["Rework Record", "product_name"],
			["Rework Record", "from_work_report"],
			["Rework Record", "work_order"]
		];

		let setting_filter_values = false;
		let applying_quick_filters = Promise.resolve();

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
			if (setting_filter_values) {
				return Promise.resolve();
			}

			const apply = () => {
				const start_date = start_date_field._real_get_value();
				const end_date = end_date_field._real_get_value();
				const employee_name = (employee_name_field._real_get_value() || "").trim();
				const inspector_name = (inspector_name_field._real_get_value() || "").trim();
				const workstation = workstation_field._real_get_value();
				const product_name = (product_name_field._real_get_value() || "").trim();
				const work_report = (work_report_field._real_get_value() || "").trim();
				const work_order = (work_order_field._real_get_value() || "").trim();

				remove_existing_quick_filters();

				const filters = [];
				if (start_date) {
					filters.push([
						"Rework Record",
						"created_at",
						">=",
						`${start_date} 00:00:00`
					]);
				}
				if (end_date) {
					filters.push([
						"Rework Record",
						"created_at",
						"<=",
						`${end_date} 23:59:59`
					]);
				}
				if (employee_name) {
					filters.push([
						"Rework Record",
						"employee_name_display",
						"like",
						`%${employee_name}%`
					]);
				}
				if (inspector_name) {
					filters.push([
						"Rework Record",
						"inspector_name_display",
						"like",
						`%${inspector_name}%`
					]);
				}
				if (workstation) {
					filters.push(["Rework Record", "workstation", "=", workstation]);
				}
				if (product_name) {
					filters.push([
						"Rework Record",
						"product_name",
						"like",
						`%${product_name}%`
					]);
				}
				if (work_report) {
					filters.push([
						"Rework Record",
						"from_work_report",
						"like",
						`%${work_report}%`
					]);
				}
				if (work_order) {
					filters.push([
						"Rework Record",
						"work_order",
						"like",
						`%${work_order}%`
					]);
				}

				return listview.filter_area.add(filters, false).then(() => {
					listview.start = 0;
					listview.refresh();
				});
			};

			applying_quick_filters = applying_quick_filters.then(apply, apply);
			return applying_quick_filters;
		};

		const set_date_range = (start_date, end_date) => {
			setting_filter_values = true;
			return frappe
				.run_serially([
					() => start_date_field.set_value(start_date),
					() => end_date_field.set_value(end_date)
				])
				.then(() => {
					setting_filter_values = false;
					return apply_quick_filters();
				})
				.catch((error) => {
					setting_filter_values = false;
					throw error;
				});
		};

		const get_month_range = (base_date, month_offset = 0) => {
			const first_day = new Date(
				base_date.getFullYear(),
				base_date.getMonth() + month_offset,
				1
			);
			const last_day = new Date(first_day.getFullYear(), first_day.getMonth() + 1, 0);

			return {
				from_date: frappe.datetime.obj_to_str(first_day),
				to_date: frappe.datetime.obj_to_str(last_day)
			};
		};

		const get_current_month_range = () => {
			return get_month_range(frappe.datetime.str_to_obj(frappe.datetime.get_today()));
		};

		const get_adjacent_month_range = (month_offset) => {
			const active_date =
				start_date_field._real_get_value() ||
				end_date_field._real_get_value() ||
				frappe.datetime.get_today();
			const base = frappe.datetime.str_to_obj(active_date);

			if (!base) {
				return get_current_month_range();
			}
			return get_month_range(base, month_offset);
		};

		const clear_date_filter = () => set_date_range("", "");

		// Refresh on any quick-filter change.
		all_quick_fields.forEach((field) => {
			if (field.$input) {
				field.$input.on("change", () => {
					apply_quick_filters();
				});
			}
		});

		listview.page.add_inner_button("应用筛选", apply_quick_filters);

		listview.page.add_inner_button("本月", () => {
			const range = get_current_month_range();
			set_date_range(range.from_date, range.to_date);
		});

		listview.page.add_inner_button("上一月", () => {
			const range = get_adjacent_month_range(-1);
			set_date_range(range.from_date, range.to_date);
		});

		listview.page.add_inner_button("下一月", () => {
			const range = get_adjacent_month_range(1);
			set_date_range(range.from_date, range.to_date);
		});

		listview.page.add_inner_button("清空日期", clear_date_filter);
	}
};
