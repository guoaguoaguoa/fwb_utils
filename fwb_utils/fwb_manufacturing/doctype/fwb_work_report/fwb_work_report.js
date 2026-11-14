// Copyright (c) 2025, WenZhou Furui Handicraft Co.,Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("FWB Work Report", {
	refresh(frm) {
		fwb_update_paid_rework_remark_requirement(frm);
	},
	rework_type(frm) {
		fwb_update_paid_rework_remark_requirement(frm);
		fwb_prompt_paid_rework_remark(frm);
	},
	validate(frm) {
		if (fwb_requires_paid_rework_remark(frm) && !(frm.doc.remark || "").trim()) {
			frappe.validated = false;
			fwb_prompt_paid_rework_remark(frm);
		}
	},
});

function fwb_requires_paid_rework_remark(frm) {
	return frm.doc.docstatus === 0 && frm.doc.rework_type === "有偿返工";
}

function fwb_update_paid_rework_remark_requirement(frm) {
	const required = fwb_requires_paid_rework_remark(frm);
	frm.toggle_reqd("remark", required);
	if (!required && frm.__fwb_paid_rework_dialog) {
		frm.__fwb_paid_rework_dialog.hide();
	}
}

function fwb_prompt_paid_rework_remark(frm) {
	if (!fwb_requires_paid_rework_remark(frm) || (frm.doc.remark || "").trim()) return;
	if (frm.__fwb_paid_rework_dialog) {
		frm.__fwb_paid_rework_dialog.show();
		return;
	}

	const docname = frm.doc.name;
	const dialog = new frappe.ui.Dialog({
		title: "请填写有偿返工备注",
		fields: [{
			fieldname: "remark",
			fieldtype: "Small Text",
			label: "备注说明（返工原因）",
			description: "请说明为什么需要有偿返工，便于管理者核算工资。",
			reqd: 1,
		}],
		primary_action_label: "填写备注",
		async primary_action(values) {
			if (frm.doc.name !== docname || !fwb_requires_paid_rework_remark(frm)) {
				dialog.hide();
				return;
			}
			const remark = (values.remark || "").trim();
			if (!remark) {
				frappe.msgprint("有偿返工必须填写备注说明，不能只填空格。");
				return;
			}
			await frm.set_value("remark", remark);
			dialog.hide();
		},
		onhide() {
			if (frm.__fwb_paid_rework_dialog === dialog) {
				delete frm.__fwb_paid_rework_dialog;
			}
		},
	});
	frm.__fwb_paid_rework_dialog = dialog;
	dialog.show();
}
