frappe.ui.form.on("Dingtalk Attendance Settings", {
	refresh(frm) {
		frm.add_custom_button(__("手动同步考勤"), () => {
			const dialog = new frappe.ui.Dialog({
				title: __("手动同步钉钉考勤"),
				fields: [
					{
						fieldname: "from_date",
						fieldtype: "Date",
						label: __("开始日期"),
						reqd: 1,
						default: frappe.datetime.add_days(frappe.datetime.get_today(), -1),
					},
					{
						fieldname: "to_date",
						fieldtype: "Date",
						label: __("结束日期"),
						reqd: 1,
						default: frappe.datetime.add_days(frappe.datetime.get_today(), -1),
					},
					{
						fieldname: "employees",
						fieldtype: "MultiSelectPills",
						label: __("员工（可选）"),
						description: __("不选员工 = 同步所有已填写【考勤设备ID】的在职员工；选择员工 = 只同步所选员工。"),
						get_data(txt) {
							return frappe.db.get_link_options("Employee", txt, {
								status: "Active",
							});
						},
					},
					{
						fieldname: "force_locked",
						fieldtype: "Check",
						label: __("强制修订已锁定考勤"),
						default: 0,
					},
				],
				primary_action_label: __("同步"),
				primary_action(values) {
					dialog.hide();
					frappe.call({
						method: "fwb_utils.fwb_manufacturing.dingtalk_attendance_api.sync_dingtalk_attendance",
						args: values,
						freeze: true,
						freeze_message: __("正在同步钉钉考勤..."),
						callback(r) {
							const stat = r.message || {};
							const message = [
								__("API 调用次数：{0}", [stat.api_calls || 0]),
								__("考勤组名称查询：{0}", [stat.group_name_api_calls || 0]),
								__("带薪假查询：{0}", [stat.paid_leave_api_calls || 0]),
								__("新建考勤：{0}", [stat.created_attendance || 0]),
								__("修订考勤：{0}", [stat.amended_attendance || 0]),
								__("锁定跳过：{0}", [stat.skipped_locked_attendance || 0]),
								__("新建签到流水：{0}", [stat.created_checkins || 0]),
								__("补写设备位置：{0}", [stat.updated_checkin_device_ids || 0]),
								__("重复签到跳过：{0}", [stat.skipped_duplicate_checkins || 0]),
							];
							if (stat.missing_gate_device_samples && stat.missing_gate_device_samples.length) {
								message.push(
									"<hr>",
									__("仍有未映射的原始设备字段（仅列前 5 条；若对应签到未显示 401/402/WiFi/补卡，请把 deviceId/deviceSN 加到门禁或 WiFi 映射，补卡则检查钉钉 payload 是否带审批标记）："),
									"<pre style='max-height:160px;overflow:auto'>" +
										frappe.utils.escape_html(JSON.stringify(stat.missing_gate_device_samples.slice(0, 5), null, 2)) +
									"</pre>"
								);
							}
							if (stat.group_name_lookup_errors && stat.group_name_lookup_errors.length) {
								message.push(
									"<hr>",
									__("考勤组名称查询失败，已回退显示“钉钉API”："),
									"<pre style='max-height:120px;overflow:auto'>" +
										frappe.utils.escape_html(JSON.stringify(stat.group_name_lookup_errors.slice(0, 5), null, 2)) +
									"</pre>"
								);
							}
							if (stat.paid_leave_lookup_errors && stat.paid_leave_lookup_errors.length) {
								message.push(
									"<hr>",
									__("带薪假查询失败，相关请假会按无薪兜底："),
									"<pre style='max-height:120px;overflow:auto'>" +
										frappe.utils.escape_html(JSON.stringify(stat.paid_leave_lookup_errors.slice(0, 5), null, 2)) +
									"</pre>"
								);
							}
							frappe.msgprint({
								title: __("钉钉考勤同步完成"),
								message: message.join("<br>"),
							});
						},
					});
				},
			});
			dialog.show();
		});
	},
});
