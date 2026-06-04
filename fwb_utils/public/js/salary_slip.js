frappe.ui.form.on("Salary Slip", {
	refresh(frm) {
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
						message: __("已重算：实际到岗 {0} 天，记薪 {1} 天，餐补 {2} 天，迟到扣款 {3}，早退扣款 {4}，净工资 {5}", [
							data.actual_attendance_days || 0,
							data.payment_days || 0,
							data.meal_days || 0,
							data.late_deduction_amount || 0,
							data.early_deduction_amount || 0,
							data.net_pay || 0,
						]),
						indicator: "green",
					});
				},
			});
		});
	},
});
