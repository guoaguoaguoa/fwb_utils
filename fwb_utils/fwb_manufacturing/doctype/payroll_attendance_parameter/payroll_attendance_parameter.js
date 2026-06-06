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
			frappe.confirm(message, () => {
				apply_attendance_payroll_recalculation(dialog, values);
			});
		},
	});
}

function apply_attendance_payroll_recalculation(dialog, values) {
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
	const summary = `
		${warning}
		<div class="mb-3">
			<div>${__("月份")}：${escape_html(preview.month || "")}</div>
			<div>${__("员工数")}：${preview.employee_count || 0}</div>
			<div>${__("考勤条数")}：${preview.attendance_count || 0}</div>
			<div>${__("将变化条数")}：${preview.changed_count || 0}</div>
			<div>${__("跳过锁定")}：${preview.skipped_locked_count || 0}</div>
		</div>
	`;
	const samples = (preview.samples || []).map((row) => {
		return `<tr>
			<td>${escape_html(row.attendance_date || "")}</td>
			<td>${escape_html(row.employee_name || row.employee || "")}</td>
			<td>${format_days(row.old_overtime_days)} → ${format_days(row.new_overtime_days)}</td>
			<td>${format_days(row.old_meal_allowance_days)} → ${format_days(row.new_meal_allowance_days)}</td>
		</tr>`;
	});
	const table = samples.length
		? `<table class="table table-bordered">
			<thead>
				<tr>
					<th>${__("日期")}</th>
					<th>${__("员工")}</th>
					<th>${__("加班天")}</th>
					<th>${__("餐补天")}</th>
				</tr>
			</thead>
			<tbody>${samples.join("")}</tbody>
		</table>`
		: `<p>${__("没有需要更新的考勤。")}</p>`;
	return `${summary}${table}`;
}

function escape_html(value) {
	return frappe.utils.escape_html(String(value || ""));
}

function format_days(value) {
	const number = flt(value || 0, 4);
	return String(number).replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
}
