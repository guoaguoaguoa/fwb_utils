// Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and contributors
// For license information, please see license.txt

(function () {
	const existing_settings = frappe.listview_settings["Salary Slip"] || {};
	const existing_onload = existing_settings.onload;

	const setup_salary_slip_quick_filters = (listview) => {
		if (listview._fwb_salary_slip_quick_filters_setup) {
			return;
		}
		listview._fwb_salary_slip_quick_filters_setup = true;
		inject_salary_slip_list_css();
		listview.page.wrapper.addClass("fwb-salary-slip-list-page");

		["name", "company", "branch", "employee_name", "start_date", "end_date"].forEach((fieldname) => {
			hide_standard_filter(listview, fieldname);
		});
		style_standard_filter(listview, "employee", "员工(ID/姓名)");
		style_standard_filter(listview, "department", "部门(含下级)", "descendants of (inclusive)");
		style_standard_filter(listview, "salary_structure");

		const quick_filter_parent = get_quick_filter_parent(listview);

		const from_date_field = listview.page.add_field({
			label: "工资开始",
			fieldtype: "Date",
			fieldname: "fwb_salary_slip_from_date_filter"
		}, quick_filter_parent);

		const to_date_field = listview.page.add_field({
			label: "工资结束",
			fieldtype: "Date",
			fieldname: "fwb_salary_slip_to_date_filter"
		}, quick_filter_parent);

		const workstation_field = listview.page.add_field({
			label: "工作站",
			fieldtype: "Link",
			options: "Workstation",
			fieldname: "fwb_salary_slip_workstation_filter"
		}, quick_filter_parent);

		[from_date_field, to_date_field, workstation_field].forEach((field) => {
			style_quick_filter(field);
		});

		from_date_field._real_get_value = from_date_field.get_value.bind(from_date_field);
		to_date_field._real_get_value = to_date_field.get_value.bind(to_date_field);
		workstation_field._real_get_value = workstation_field.get_value.bind(workstation_field);

		from_date_field.get_value = function () {
			return null;
		};
		to_date_field.get_value = function () {
			return null;
		};
		workstation_field.get_value = function () {
			return null;
		};

		const controlled_filters = [
			["Salary Slip", "start_date"],
			["Salary Slip", "end_date"],
			["Employee Wage Sheet Detail", "workstation"]
		];
		const hidden_standard_filters = [
			["Salary Slip", "name"],
			["Salary Slip", "company"],
			["Salary Slip", "branch"],
			["Salary Slip", "employee_name"]
		];
		const removable_filters = controlled_filters.concat(hidden_standard_filters);
		let setting_filter_values = false;
		let applying_quick_filters = Promise.resolve();

		const is_removable_filter = (filter_value) => {
			return removable_filters.some(([doctype, fieldname]) => {
				return filter_value[0] === doctype && filter_value[1] === fieldname;
			});
		};

		const remove_existing_quick_filters = () => {
			const filter_list = listview.filter_area.filter_list;

			filter_list.filters = filter_list.filters.filter((filter) => {
				const filter_value = filter.field && filter.get_value();
				const should_remove = filter_value && is_removable_filter(filter_value);

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
				const from_date = from_date_field._real_get_value();
				const to_date = to_date_field._real_get_value();
				const workstation = workstation_field._real_get_value();

				remove_existing_quick_filters();

				const filters = [];
				if (from_date) {
					filters.push(["Salary Slip", "start_date", ">=", from_date]);
				}
				if (to_date) {
					filters.push(["Salary Slip", "end_date", "<=", to_date]);
				}
				if (workstation) {
					filters.push(["Employee Wage Sheet Detail", "workstation", "=", workstation]);
				}

				return listview.filter_area.add(filters, false).then(() => {
					listview.start = 0;
					listview.refresh();
				});
			};

			applying_quick_filters = applying_quick_filters.then(apply, apply);
			return applying_quick_filters;
		};

		const set_date_range = (from_date, to_date) => {
			setting_filter_values = true;
			return frappe
				.run_serially([
					() => from_date_field.set_value(from_date),
					() => to_date_field.set_value(to_date)
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
				from_date_field._real_get_value() ||
				to_date_field._real_get_value() ||
				frappe.datetime.get_today();
			const base = frappe.datetime.str_to_obj(active_date);

			if (!base) {
				return get_current_month_range();
			}
			return {
				...get_month_range(base, month_offset)
			};
		};

		const clear_date_filter = () => {
			return set_date_range("", "");
		};

		from_date_field.$input.on("change", () => {
			apply_quick_filters();
		});
		to_date_field.$input.on("change", () => {
			apply_quick_filters();
		});
		workstation_field.$input.on("change", () => {
			apply_quick_filters();
		});

		remove_existing_quick_filters();

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
	};

	const inject_salary_slip_list_css = () => {
		if ($("#salary-slip-list-filter-css").length) {
			return;
		}

		const css = `
			.fwb-salary-slip-list-page .page-form {
				align-items: flex-start;
				gap: 2px 6px;
			}

			.fwb-salary-slip-list-page .page-form .standard-filter-section {
				display: flex;
				flex: 1 1 100%;
				flex-wrap: wrap;
				gap: 6px;
				align-items: center;
			}

			.fwb-salary-slip-list-page .page-form .standard-filter-section .form-group {
				flex: 0 0 132px;
				min-width: 132px;
				max-width: 170px;
				padding: 0;
				margin: 3px 0;
			}

			.fwb-salary-slip-list-page .page-form .standard-filter-section .form-group[data-fwb-fieldname="employee"] {
				flex-basis: 170px;
				max-width: 190px;
			}

			.fwb-salary-slip-list-page .page-form .standard-filter-section .form-group[data-fwb-fieldname="salary_structure"] {
				flex-basis: 150px;
				max-width: 170px;
			}

			.fwb-salary-slip-list-page .page-form .standard-filter-section .form-group[data-fwb-fieldname="department"] {
				flex-basis: 150px;
				max-width: 170px;
			}

			.fwb-salary-slip-list-page .page-form .standard-filter-section .form-group[data-fwb-fieldname="fwb_salary_slip_from_date_filter"],
			.fwb-salary-slip-list-page .page-form .standard-filter-section .form-group[data-fwb-fieldname="fwb_salary_slip_to_date_filter"],
			.fwb-salary-slip-list-page .page-form .standard-filter-section .form-group[data-fwb-fieldname="fwb_salary_slip_workstation_filter"] {
				flex-basis: 128px;
			}

			.fwb-salary-slip-list-page .page-form .filter-section {
				flex: 1 1 100%;
				padding: 0;
				align-items: center;
			}
		`;

		$("<style id='salary-slip-list-filter-css'>")
			.text(css)
			.appendTo("head");
	};

	const get_quick_filter_parent = (listview) => {
		return listview.page.page_form.find(".standard-filter-section");
	};

	const style_standard_filter = (listview, fieldname, placeholder, condition) => {
		const field = listview.page.fields_dict[fieldname];
		if (!field) {
			return;
		}

		$(field.wrapper).attr("data-fwb-fieldname", fieldname);
		if (condition) {
			field.df.condition = condition;
		}
		if (placeholder && field.$input) {
			field.$input.attr("placeholder", placeholder);
			$(field.wrapper).attr("title", placeholder);
		}
	};

	const style_quick_filter = (field) => {
		if (!field) {
			return;
		}
		$(field.wrapper)
			.addClass("fwb-salary-slip-quick-filter")
			.attr("data-fwb-fieldname", field.df.fieldname);
	};

	const hide_standard_filter = (listview, fieldname) => {
		const field = listview.page.fields_dict[fieldname];
		if (!field) {
			return;
		}

		if (!field._fwb_real_get_value && field.get_value) {
			field._fwb_real_get_value = field.get_value.bind(field);
			field.get_value = function () {
				return null;
			};
		}

		if (field.$wrapper) {
			field.$wrapper.hide();
		} else if (field.wrapper) {
			$(field.wrapper).hide();
		}
	};

	frappe.listview_settings["Salary Slip"] = {
		...existing_settings,
		hide_name_filter: true,
		onload(listview) {
			if (existing_onload) {
				existing_onload(listview);
			}
			setup_salary_slip_quick_filters(listview);
		}
	};
})();
