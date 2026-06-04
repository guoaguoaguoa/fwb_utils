frappe.ui.form.on("Payroll Holiday Quota Year", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}
		frm.add_custom_button(__("复制上一年"), () => {
			frappe.confirm(__("复制上一年会覆盖当前表格里的法定假配额，继续吗？"), () => {
				frappe.call({
					method:
						"fwb_utils.fwb_manufacturing.doctype.payroll_holiday_quota_year.payroll_holiday_quota_year.copy_previous_year",
					args: {
						name: frm.doc.name,
					},
					freeze: true,
					callback(r) {
						if (!r.message) {
							return;
						}
						frm.reload_doc();
						frappe.show_alert({
							message: __("已从 {0} 年复制 {1} 行法定假配额", [
								r.message.source_year,
								r.message.rows,
							]),
							indicator: "green",
						});
					},
				});
			});
		});
	},
});
