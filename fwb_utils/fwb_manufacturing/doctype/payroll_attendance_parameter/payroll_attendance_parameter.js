// Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Payroll Attendance Parameter", {
	refresh(frm) {
		frm.add_custom_button(__("重算考勤结算字段"), () => {
			show_attendance_payroll_recalculation_dialog();
		});
	},
});

var attendance_recalc_method =
	"fwb_utils.fwb_manufacturing.dingtalk_attendance_api.recalculate_attendance_payroll_fields";

function show_attendance_payroll_recalculation_dialog() {
	const dialog = new frappe.ui.Dialog({
		title: __("重算考勤结算字段"),
		fields: [
			{
				fieldname: "month",
				label: __("月份"),
				fieldtype: "Data",
				default: frappe.datetime.get_today().slice(0, 7),
				reqd: 1,
			},
			{
				fieldname: "scope",
				label: __("重算范围"),
				fieldtype: "Select",
				options: ["指定员工", "指定部门", "全员"].join("\n"),
				default: "指定员工",
				reqd: 1,
				onchange: () => update_recalculation_scope_fields(dialog),
			},
			{
				fieldname: "employees",
				label: __("员工"),
				fieldtype: "MultiSelectPills",
				reqd: 1,
				get_data(txt) {
					return frappe.db.get_link_options("Employee", txt, { status: "Active" });
				},
			},
			{
				fieldname: "department",
				label: __("部门"),
				fieldtype: "Link",
				options: "Department",
			},
			{
				fieldname: "include_locked",
				label: __("包含已锁定考勤"),
				fieldtype: "Check",
				default: 0,
			},
		],
		primary_action_label: __("预览"),
		primary_action(values) {
			preview_attendance_payroll_recalculation(dialog, values);
		},
	});

	dialog.show();
	update_recalculation_scope_fields(dialog);
}

function update_recalculation_scope_fields(dialog) {
	const scope = dialog.get_value("scope");
	dialog.set_df_property("employees", "hidden", scope !== "指定员工");
	dialog.set_df_property("employees", "reqd", scope === "指定员工");
	dialog.set_df_property("department", "hidden", scope !== "指定部门");
	dialog.set_df_property("department", "reqd", scope === "指定部门");
}

function preview_attendance_payroll_recalculation(dialog, values) {
	if (!values) {
		return;
	}
	if (!/^\d{4}-\d{2}$/.test(values.month || "")) {
		frappe.msgprint(__("月份必须使用 YYYY-MM 格式。"));
		return;
	}
	if (values.scope === "指定员工" && !(values.employees || []).length) {
		frappe.msgprint(__("请选择需要重算的员工。"));
		return;
	}
	if (values.scope === "指定部门" && !values.department) {
		frappe.msgprint(__("请选择需要重算的部门。"));
		return;
	}

	frappe.call({
		method: attendance_recalc_method,
		args: {
			month: values.month,
			scope: values.scope,
			employees: values.employees || [],
			department: values.department,
			include_locked: values.include_locked ? 1 : 0,
			dry_run: 1,
		},
		freeze: true,
		freeze_message: __("正在预览"),
		callback(response) {
			const preview = response.message || {};
			const message = build_recalculation_preview_html(preview);
			if (!preview.changed_count) {
				frappe.msgprint({
					title: __("预览结果"),
					indicator: "blue",
					message,
				});
				return;
			}
			show_recalculation_preview_dialog(dialog, values, preview, message);
		},
	});
}

function show_recalculation_preview_dialog(source_dialog, values, preview, message) {
	const preview_dialog = new frappe.ui.Dialog({
		title: __("重算预览"),
		size: "extra-large",
		fields: [
			{
				fieldname: "preview_html",
				fieldtype: "HTML",
				options: message,
			},
		],
		primary_action_label: __("确认重算"),
		primary_action() {
			apply_attendance_payroll_recalculation(source_dialog, values, preview_dialog);
		},
		secondary_action_label: __("返回修改"),
		secondary_action() {
			preview_dialog.hide();
		},
	});
	preview_dialog.show();
	if (preview.samples_truncated) {
		preview_dialog.$wrapper.find(".modal-title").attr("title", __("明细仅展示前 50 条，汇总数据包含全部变化。"));
	}
}

function apply_attendance_payroll_recalculation(dialog, values, preview_dialog) {
	frappe.call({
		method: attendance_recalc_method,
		args: {
			month: values.month,
			scope: values.scope,
			employees: values.employees || [],
			department: values.department,
			include_locked: values.include_locked ? 1 : 0,
			dry_run: 0,
		},
		freeze: true,
		freeze_message: __("正在重算"),
		callback(response) {
			const result = response.message || {};
			if (preview_dialog) {
				preview_dialog.hide();
			}
			dialog.hide();
			frappe.msgprint({
				title: __("重算完成"),
				indicator: "green",
				message: __(
					"已更新 {0} 条；变化 {1} 条；跳过锁定 {2} 条。",
					[result.updated_count || 0, result.changed_count || 0, result.skipped_locked_count || 0]
				),
			});
		},
	});
}

function build_recalculation_preview_html(preview) {
	const warning =
		preview.scope === "全员"
			? `<p class="text-warning">${__("将按全员范围重算，请确认月份和预计影响数量。")}</p>`
			: "";
	const change_summary = preview.change_summary || {};
	const change_rows = [
		["late_minutes", __("迟到分钟"), format_number],
		["early_minutes", __("早退分钟"), format_number],
		["overtime_days", __("加班天"), format_days],
		["meal_allowance_days", __("餐补天"), format_days],
	].map(([fieldname, label, formatter]) => {
		const item = change_summary[fieldname] || {};
		return `<tr>
			<td>${label}</td>
			<td class="text-right">${item.changed_count || 0}</td>
			<td class="text-right">${formatter(item.old_total)}</td>
			<td class="text-right">${formatter(item.new_total)}</td>
			<td class="text-right ${flt(item.delta || 0) ? "font-weight-bold" : "text-muted"}">${format_signed(item.delta, formatter)}</td>
		</tr>`;
	});
	const summary = `
		${warning}
		<div class="attendance-recalc-preview">
			<div class="recalc-meta mb-3">
				<span><b>${escape_html(preview.month || "")}</b></span>
				<span>${__("员工")} <b>${preview.employee_count || 0}</b></span>
				<span>${__("考勤")} <b>${preview.attendance_count || 0}</b></span>
				<span>${__("变化")} <b>${preview.changed_count || 0}</b></span>
				<span>${__("跳过锁定")} <b>${preview.skipped_locked_count || 0}</b></span>
			</div>
			<table class="table table-bordered table-sm recalc-summary-table mb-3">
				<thead><tr><th>${__("结算字段")}</th><th class="text-right">${__("影响行")}</th><th class="text-right">${__("旧合计")}</th><th class="text-right">${__("新合计")}</th><th class="text-right">${__("差额")}</th></tr></thead>
				<tbody>${change_rows.join("")}</tbody>
			</table>
		</div>
	`;
	const samples = (preview.samples || []).map((row) => {
		const attendance_url = `/app/attendance/${encodeURIComponent(row.attendance || "")}`;
		return `<tr>
			<td><a href="${attendance_url}">${escape_html(row.attendance_date || "")}</a></td>
			<td><div>${escape_html(row.employee_name || "")}</div><small class="text-muted">${escape_html(row.employee || "")}</small></td>
			<td>${escape_html(row.department || "")}</td>
			<td>${escape_html(row.salary_structure || "")}</td>
			<td>${format_change(row.old_late_minutes, row.new_late_minutes, format_number)}</td>
			<td>${format_change(row.old_early_minutes, row.new_early_minutes, format_number)}</td>
			<td>${format_change(row.old_overtime_days, row.new_overtime_days, format_days)}</td>
			<td>${format_change(row.old_meal_allowance_days, row.new_meal_allowance_days, format_days)}</td>
		</tr>`;
	});
	const truncated = preview.samples_truncated
		? `<div class="text-muted mb-2">${__("显示前 {0} 条，共 {1} 条变化；上方汇总包含全部记录。", [preview.sample_limit || 50, preview.changed_count || 0])}</div>`
		: "";
	const table = samples.length
		? `${truncated}<div class="recalc-detail-scroll"><table class="table table-bordered table-sm recalc-detail-table">
			<thead>
				<tr>
					<th>${__("日期")}</th>
					<th>${__("员工")}</th>
					<th>${__("部门")}</th>
					<th>${__("薪资结构")}</th>
					<th>${__("迟到分钟")}</th>
					<th>${__("早退分钟")}</th>
					<th>${__("加班天")}</th>
					<th>${__("餐补天")}</th>
				</tr>
			</thead>
			<tbody>${samples.join("")}</tbody>
		</table></div>`
		: `<p>${__("没有需要更新的考勤。")}</p>`;
	return `${summary}${table}<style>
		.attendance-recalc-preview .recalc-meta { display:flex; flex-wrap:wrap; gap:8px 22px; align-items:center; }
		.attendance-recalc-preview .table { margin-bottom:0; }
		.recalc-detail-scroll { max-height:440px; overflow:auto; border:1px solid var(--border-color); }
		.recalc-detail-table { min-width:1080px; }
		.recalc-detail-table thead th { position:sticky; top:0; z-index:1; background:var(--subtle-fg); white-space:nowrap; }
		.recalc-detail-table td { vertical-align:middle; }
		.recalc-change { display:inline-flex; align-items:center; gap:5px; white-space:nowrap; color:var(--text-color); }
		.recalc-change strong { color:var(--orange-600, #9a6700); }
	</style>`;
}

function escape_html(value) {
	return frappe.utils.escape_html(String(value || ""));
}

function format_days(value) {
	const number = flt(value || 0, 4);
	return String(number).replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
}

function format_number(value) {
	return format_days(flt(value || 0, 4));
}

function format_signed(value, formatter) {
	const number = flt(value || 0, 4);
	if (!number) {
		return "—";
	}
	return `${number > 0 ? "+" : ""}${formatter(number)}`;
}

function format_change(old_value, new_value, formatter) {
	if (Math.abs(flt(old_value || 0) - flt(new_value || 0)) <= 0.0001) {
		return '<span class="text-muted">—</span>';
	}
	return `<span class="recalc-change"><span>${formatter(old_value)}</span><span aria-hidden="true">→</span><strong>${formatter(new_value)}</strong></span>`;
}
