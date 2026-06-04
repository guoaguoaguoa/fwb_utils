import frappe
from frappe.utils import cint, flt

from fwb_utils.patches.v15_0.payroll_attendance_parameter_quota_and_overtime import (
	NON_WORKER_QUOTAS_2026,
	REGULAR_QUOTAS_2026,
)


def execute():
	if not frappe.db.exists("DocType", "Payroll Holiday Quota Year"):
		return
	legacy_rows = _legacy_parameter_rows()
	if legacy_rows:
		_seed_from_rows(legacy_rows)
		_delete_legacy_parameter_rows()
	else:
		_seed_from_rows(REGULAR_QUOTAS_2026 + NON_WORKER_QUOTAS_2026)


def _legacy_parameter_rows():
	try:
		return frappe.db.sql(
			"""
			select year, holiday_month, holiday_name, is_regular, quota_days, enabled
			from `tabPayroll Holiday Quota`
			where parenttype = 'Payroll Attendance Parameter'
			  and parentfield = 'holiday_quotas'
			order by year, idx
			""",
			as_dict=True,
		)
	except Exception:
		return []


def _seed_from_rows(rows):
	for year, year_rows in _group_by_year(rows).items():
		doc = _get_or_new_year_doc(year)
		existing = {
			(cint(row.holiday_month), 1 if cint(row.is_regular) else 0, str(row.holiday_name or "").strip())
			for row in doc.get("holiday_quotas")
		}
		for row in year_rows:
			key = (
				cint(row.get("holiday_month")),
				1 if cint(row.get("is_regular")) else 0,
				str(row.get("holiday_name") or "").strip(),
			)
			if key in existing:
				continue
			doc.append(
				"holiday_quotas",
				{
					"holiday_month": cint(row.get("holiday_month")),
					"holiday_name": str(row.get("holiday_name") or "").strip(),
					"is_regular": 1 if cint(row.get("is_regular")) else 0,
					"quota_days": flt(row.get("quota_days")),
					"enabled": 1 if cint(row.get("enabled", 1)) else 0,
				},
			)
			existing.add(key)
		doc.save(ignore_permissions=True)


def _group_by_year(rows):
	grouped = {}
	for row in rows:
		year = cint(row.get("year"))
		month = cint(row.get("holiday_month"))
		name = str(row.get("holiday_name") or "").strip()
		if year <= 0 or month < 1 or month > 12 or not name:
			continue
		grouped.setdefault(year, []).append(row)
	return grouped


def _get_or_new_year_doc(year):
	name = frappe.db.get_value("Payroll Holiday Quota Year", {"year": year}, "name")
	if name:
		return frappe.get_doc("Payroll Holiday Quota Year", name)
	return frappe.get_doc({"doctype": "Payroll Holiday Quota Year", "year": year})


def _delete_legacy_parameter_rows():
	frappe.db.sql(
		"""
		delete from `tabPayroll Holiday Quota`
		where parenttype = 'Payroll Attendance Parameter'
		  and parentfield = 'holiday_quotas'
		"""
	)
