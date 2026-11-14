// Copyright (c) 2025, WenZhou Furui Handicraft Co.,Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Rework Record", {
	refresh: update_recovery_input,
	rework_action: update_recovery_input,
	from_work_report: update_recovery_input,
});

function update_recovery_input(frm) {
	if (frm.doc.docstatus !== 0) return;
	const recovery = frm.doc.rework_action === "良品回补";
	frm.toggle_display("quality_inspected", !recovery);
	if (!recovery) return;
	// 复检同一批产品不再计入首次质检基数。
	if (frm.doc.quality_inspected) frm.set_value("quality_inspected", 0);
	const source = frm.doc.from_work_report;
	if (!source) return;
	frappe.call({
		method: "fwb_utils.fwb_manufacturing.doctype.rework_record.rework_record.get_rework_history_summary",
		args: { from_work_report: source },
		callback(r) {
			if (frm.doc.from_work_report !== source || frm.doc.rework_action !== "良品回补") return;
			const data = r.message || {};
			const deducted = Number(data.total_defective_qty || 0);
			const recovered = Number(data.total_reworked_qty || 0);
			frm.set_df_property("reworked_qty", "description",
				`累计扣除 ${deducted}，已回补 ${recovered}，本次最多可回补 ${Math.max(0, deducted - recovered)}。提交时系统再次校验。`);
		},
	});
}
