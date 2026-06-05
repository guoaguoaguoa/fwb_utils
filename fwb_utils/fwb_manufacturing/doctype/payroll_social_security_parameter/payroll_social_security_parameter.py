# Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate


class PayrollSocialSecurityParameter(Document):
	def validate(self):
		self._validate_rules()

	def _validate_rules(self):
		seen = set()
		for row in self.get("rules"):
			if not row.effective_from:
				frappe.throw(f"社保缴费规则第 {row.idx} 行生效月份不能为空。")
			effective_from = getdate(row.effective_from)
			if effective_from.day != 1:
				frappe.throw(f"社保缴费规则第 {row.idx} 行生效月份必须是每月 1 日。")
			if flt(row.personal_amount) < 0:
				frappe.throw(f"社保缴费规则第 {row.idx} 行个人社保扣款不能小于 0。")
			if cint(row.enabled) and flt(row.personal_amount) <= 0:
				frappe.throw(f"社保缴费规则第 {row.idx} 行启用时个人社保扣款必须大于 0。")
			if not cint(row.enabled):
				continue
			if effective_from in seen:
				frappe.throw(f"社保缴费规则第 {row.idx} 行生效月份与前面启用行重复。")
			seen.add(effective_from)


def get_personal_amount_for_date(on_date):
	if not on_date or not frappe.db.exists("DocType", "Payroll Social Security Parameter"):
		return 0
	target_date = getdate(on_date)
	try:
		doc = frappe.get_cached_doc("Payroll Social Security Parameter")
	except Exception:
		return 0

	matching_amount = 0
	matching_date = None
	for row in doc.get("rules"):
		if not cint(row.enabled) or not row.effective_from:
			continue
		effective_from = getdate(row.effective_from)
		if effective_from <= target_date and (matching_date is None or effective_from > matching_date):
			matching_date = effective_from
			matching_amount = flt(row.personal_amount)
	return matching_amount
