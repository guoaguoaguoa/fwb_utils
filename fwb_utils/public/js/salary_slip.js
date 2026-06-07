const PIECE_WAGE_STRUCTURE = "无底薪计件工结构";
const PIECE_WAGE_DETAIL_FIELD = "custom_piece_wage_details";
const LEGACY_WAGE_DETAIL_FIELD = "custom_manufacturing_wage_details";

function is_piece_wage_salary_slip(frm) {
	return (frm.doc.salary_structure || "") === PIECE_WAGE_STRUCTURE;
}

function has_child_rows(frm, fieldname) {
	return ((frm.doc[fieldname] || []).length || 0) > 0;
}

function format_piece_duration(seconds) {
	const sec = cint(seconds || 0);
	if (sec <= 0) {
		return "";
	}
	const hours = Math.floor(sec / 3600);
	const minutes = Math.floor((sec % 3600) / 60);
	const h_str = hours > 0 ? `${hours}小时` : "";
	const m_str = minutes > 0 ? `${minutes}分钟` : (hours > 0 ? "0分钟" : "");
	return (h_str + m_str) || "";
}

function inject_salary_slip_piece_wage_css() {
	if ($("#salary-slip-piece-wage-css").length) return;

	const css = `
		.salary-slip-piece-time-row [data-fieldname="rate"],
		.salary-slip-piece-time-row [data-fieldname="duration_display"],
		.salary-slip-piece-time-row [data-fieldname="amount"] {
			color: #0066cc !important;
			font-weight: 600 !important;
		}

		.salary-slip-piece-penalty-row .grid-static-col,
		.salary-slip-piece-penalty-row .grid-static-col * {
			color: #c62828 !important;
			font-weight: 700 !important;
		}
	`;

	$("<style id='salary-slip-piece-wage-css'>")
		.text(css)
		.appendTo("head");
}

function toggle_piece_wage_fields(frm) {
	const show_piece_tab = is_piece_wage_salary_slip(frm) || has_child_rows(frm, PIECE_WAGE_DETAIL_FIELD);
	const show_legacy = has_child_rows(frm, LEGACY_WAGE_DETAIL_FIELD);

	[
		"custom_piece_wage_tab",
		"custom_piece_wage_summary_section",
		"custom_piece_wage_total_qty",
		"custom_piece_wage_qty_column_break",
		"custom_piece_wage_total_duration_seconds",
		"custom_piece_wage_totals_column_break",
		"custom_piece_wage_total_amount",
		"custom_piece_wage_detail_section",
		PIECE_WAGE_DETAIL_FIELD,
	].forEach(fieldname => {
		if (frm.fields_dict[fieldname]) {
			frm.toggle_display(fieldname, show_piece_tab);
		}
	});

	["custom_section_break_ap1nx", LEGACY_WAGE_DETAIL_FIELD].forEach(fieldname => {
		if (frm.fields_dict[fieldname]) {
			frm.toggle_display(fieldname, show_legacy);
		}
	});
}

function recompute_piece_row_amount(row) {
	const seconds = cint(row.duration_seconds || 0);
	const rate = flt(row.rate || 0);
	const qty = flt(row.qty || 0);
	row.amount = seconds > 0 ? (seconds / 3600.0) * rate : qty * rate;
}

function recompute_piece_totals(frm) {
	if (!frm.fields_dict[PIECE_WAGE_DETAIL_FIELD]) {
		return;
	}

	let total_qty = 0.0;
	let total_amount = 0.0;
	let total_duration_seconds = 0;

	(frm.doc[PIECE_WAGE_DETAIL_FIELD] || []).forEach(row => {
		total_qty += flt(row.qty || 0);
		total_duration_seconds += cint(row.duration_seconds || 0);
		if (cint(row.is_penalty || 0) === 1) {
			total_amount -= flt(row.amount || 0);
		} else {
			total_amount += flt(row.amount || 0);
		}
	});

	frm.set_value("custom_piece_wage_total_qty", total_qty);
	frm.set_value("custom_piece_wage_total_duration_seconds", total_duration_seconds);
	frm.set_value("custom_piece_wage_total_amount", total_amount);
}

function refresh_piece_grid_row_styles(frm) {
	if (!frm.fields_dict[PIECE_WAGE_DETAIL_FIELD] || !frm.fields_dict[PIECE_WAGE_DETAIL_FIELD].grid) return;

	const grid = frm.fields_dict[PIECE_WAGE_DETAIL_FIELD].grid;
	grid.grid_rows.forEach(row => {
		const doc = row.doc;
		const $data_row = $(row.row || row.$row || []);
		if (!$data_row.length) return;

		if (cint(doc.duration_seconds || 0) > 0) {
			$data_row.addClass("salary-slip-piece-time-row");
		} else {
			$data_row.removeClass("salary-slip-piece-time-row");
		}

		if (cint(doc.is_penalty || 0) === 1) {
			$data_row.addClass("salary-slip-piece-penalty-row");
		} else {
			$data_row.removeClass("salary-slip-piece-penalty-row");
		}
	});
}

function schedule_piece_grid_style_refresh(frm) {
	if (!frm || !frm.fields_dict[PIECE_WAGE_DETAIL_FIELD]) return;

	if (frm._salary_slip_piece_style_timer) {
		clearTimeout(frm._salary_slip_piece_style_timer);
	}

	frm._salary_slip_piece_style_timer = setTimeout(() => {
		refresh_piece_grid_row_styles(frm);
	}, 80);
}

function setup_piece_grid_style_refresh(frm) {
	if (!frm.fields_dict[PIECE_WAGE_DETAIL_FIELD] || !frm.fields_dict[PIECE_WAGE_DETAIL_FIELD].grid) return;

	const grid = frm.fields_dict[PIECE_WAGE_DETAIL_FIELD].grid;
	if (!grid._fwb_piece_wage_style_refresh_patched && typeof grid.refresh === "function") {
		const original_refresh = grid.refresh.bind(grid);
		grid.refresh = function () {
			const result = original_refresh(...arguments);
			schedule_piece_grid_style_refresh(frm);
			return result;
		};
		grid._fwb_piece_wage_style_refresh_patched = true;
	}
}

function add_piece_wage_button(frm) {
	if (frm.doc.docstatus !== 0 || !is_piece_wage_salary_slip(frm)) {
		return;
	}
	if (!frm.doc.employee || !frm.doc.start_date || !frm.doc.end_date) {
		return;
	}

	frm.add_custom_button(__("从报工生成明细"), () => {
		frappe.call({
			method: "fwb_utils.fwb_manufacturing.salary_slip_piece_wage.generate_piece_wage_details_for_salary_slip",
			args: {
				salary_slip: frm.doc.name,
			},
			freeze: true,
			freeze_message: __("正在从报工生成计件明细..."),
			callback(r) {
				const data = r.message || {};
				frm.reload_doc();
				frappe.show_alert({
					message: __("已生成 {0} 行，保留手工 {1} 行，总金额 {2}", [
						data.rows || 0,
						data.manual_rows || 0,
						frappe.format(data.total_amount || 0, { fieldtype: "Currency" }),
					]),
					indicator: "green",
				});
			},
		});
	});
}

function add_attendance_recalculate_button(frm) {
	if (frm.doc.docstatus !== 0 || !frm.doc.employee || !frm.doc.start_date || !frm.doc.end_date) {
		return;
	}

	frm.add_custom_button(__("重新计算考勤与工资单"), () => {
		frappe.call({
			method: "fwb_utils.fwb_manufacturing.dingtalk_attendance_api.recalculate_salary_slip_attendance",
			args: {
				salary_slip: frm.doc.name,
			},
			freeze: true,
			freeze_message: __("正在重新计算考勤与工资单..."),
			callback(r) {
				const data = r.message || {};
				frm.reload_doc();
				frappe.show_alert({
					message: __("已重算：实际到岗 {0} 天，记薪 {1} 天，餐补 {2} 天，迟到扣款 {3}，早退扣款 {4}，社保个人 {5}，净工资 {6}", [
						data.actual_attendance_days || 0,
						data.payment_days || 0,
						data.meal_days || 0,
						data.late_deduction_amount || 0,
						data.early_deduction_amount || 0,
						data.social_security_personal_amount || 0,
						data.net_pay || 0,
					]),
					indicator: "green",
				});
				if (data.social_security_warning) {
					frappe.show_alert({
						message: __(data.social_security_warning),
						indicator: "orange",
					});
				}
			},
		});
	});
}

frappe.ui.form.on("Salary Slip", {
	refresh(frm) {
		inject_salary_slip_piece_wage_css();
		toggle_piece_wage_fields(frm);
		recompute_piece_totals(frm);
		setup_piece_grid_style_refresh(frm);
		schedule_piece_grid_style_refresh(frm);
		add_piece_wage_button(frm);
		add_attendance_recalculate_button(frm);
	},

	salary_structure(frm) {
		toggle_piece_wage_fields(frm);
	},
});

frappe.ui.form.on("Employee Wage Sheet Detail", {
	qty(frm, cdt, cdn) {
		if (frm.doc.doctype !== "Salary Slip") return;
		const row = locals[cdt][cdn];
		recompute_piece_row_amount(row);
		recompute_piece_totals(frm);
		frm.refresh_field(PIECE_WAGE_DETAIL_FIELD);
		schedule_piece_grid_style_refresh(frm);
	},

	rate(frm, cdt, cdn) {
		if (frm.doc.doctype !== "Salary Slip") return;
		const row = locals[cdt][cdn];
		recompute_piece_row_amount(row);
		recompute_piece_totals(frm);
		frm.refresh_field(PIECE_WAGE_DETAIL_FIELD);
		schedule_piece_grid_style_refresh(frm);
	},

	duration_seconds(frm, cdt, cdn) {
		if (frm.doc.doctype !== "Salary Slip") return;
		const row = locals[cdt][cdn];
		row.duration_display = format_piece_duration(row.duration_seconds);
		recompute_piece_row_amount(row);
		recompute_piece_totals(frm);
		frm.refresh_field(PIECE_WAGE_DETAIL_FIELD);
		schedule_piece_grid_style_refresh(frm);
	},

	amount(frm) {
		if (frm.doc.doctype !== "Salary Slip") return;
		recompute_piece_totals(frm);
		frm.refresh_field(PIECE_WAGE_DETAIL_FIELD);
		schedule_piece_grid_style_refresh(frm);
	},

	is_penalty(frm) {
		if (frm.doc.doctype !== "Salary Slip") return;
		recompute_piece_totals(frm);
		frm.refresh_field(PIECE_WAGE_DETAIL_FIELD);
		schedule_piece_grid_style_refresh(frm);
	},

	custom_piece_wage_details_add(frm) {
		if (frm.doc.doctype !== "Salary Slip") return;
		toggle_piece_wage_fields(frm);
		recompute_piece_totals(frm);
		schedule_piece_grid_style_refresh(frm);
	},

	custom_piece_wage_details_remove(frm) {
		if (frm.doc.doctype !== "Salary Slip") return;
		toggle_piece_wage_fields(frm);
		recompute_piece_totals(frm);
		schedule_piece_grid_style_refresh(frm);
	},
});
