# Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt


class PayrollHolidayQuotaYear(Document):
	def validate(self):
		self._validate_year()
		self._validate_quotas()

	def _validate_year(self):
		if cint(self.year) <= 0:
			frappe.throw("年份必须大于 0。")

	def _validate_quotas(self):
		seen = set()
		for row in self.get("holiday_quotas"):
			if not cint(row.enabled):
				continue
			month = cint(row.holiday_month)
			if month < 1 or month > 12:
				frappe.throw(f"法定假配额第 {row.idx} 行月份必须在 1-12 之间。")
			if not str(row.holiday_name or "").strip():
				frappe.throw(f"法定假配额第 {row.idx} 行节日不能为空。")
			if flt(row.quota_days) < 0:
				frappe.throw(f"法定假配额第 {row.idx} 行配额天数不能小于 0。")
			key = (month, 1 if cint(row.is_regular) else 0, str(row.holiday_name).strip())
			if key in seen:
				frappe.throw(f"法定假配额第 {row.idx} 行与前面行重复。")
			seen.add(key)


@frappe.whitelist()
def copy_previous_year(name):
	doc = frappe.get_doc("Payroll Holiday Quota Year", name)
	source_year = cint(doc.year) - 1
	source_name = frappe.db.get_value("Payroll Holiday Quota Year", {"year": source_year}, "name")
	if not source_name:
		frappe.throw(f"没有找到 {source_year} 年度法定假配额，无法复制。")

	source = frappe.get_doc("Payroll Holiday Quota Year", source_name)
	doc.set("holiday_quotas", [])
	for row in source.get("holiday_quotas"):
		doc.append(
			"holiday_quotas",
			{
				"holiday_month": row.holiday_month,
				"holiday_name": row.holiday_name,
				"is_regular": row.is_regular,
				"quota_days": row.quota_days,
				"enabled": row.enabled,
			},
		)
	doc.save()
	return {"source_year": source_year, "rows": len(doc.get("holiday_quotas"))}
