import frappe
from frappe.utils import cint, flt

from fwb_utils.fwb_manufacturing.doctype.payroll_attendance_parameter.payroll_attendance_parameter import (
	DEFAULT_OVERTIME_START_TIME,
	normalize_time_string,
)


REGULAR_QUOTAS_2026 = (
	{"year": 2026, "holiday_month": 5, "holiday_name": "劳动节", "is_regular": 1, "quota_days": 1},
	{"year": 2026, "holiday_month": 6, "holiday_name": "端午节", "is_regular": 1, "quota_days": 1},
	{"year": 2026, "holiday_month": 9, "holiday_name": "中秋节", "is_regular": 1, "quota_days": 1},
	{"year": 2026, "holiday_month": 10, "holiday_name": "国庆节", "is_regular": 1, "quota_days": 1},
)

NON_WORKER_QUOTAS_2026 = (
	{"year": 2026, "holiday_month": 1, "holiday_name": "元旦", "is_regular": 0, "quota_days": 1},
	{"year": 2026, "holiday_month": 2, "holiday_name": "春节", "is_regular": 0, "quota_days": 7},
	{"year": 2026, "holiday_month": 4, "holiday_name": "清明节", "is_regular": 0, "quota_days": 1},
	{"year": 2026, "holiday_month": 5, "holiday_name": "劳动节", "is_regular": 0, "quota_days": 2},
	{"year": 2026, "holiday_month": 6, "holiday_name": "端午节", "is_regular": 0, "quota_days": 1},
	{"year": 2026, "holiday_month": 9, "holiday_name": "中秋节", "is_regular": 0, "quota_days": 1},
	{"year": 2026, "holiday_month": 10, "holiday_name": "国庆节", "is_regular": 0, "quota_days": 2},
)


def execute():
	doc = frappe.get_single("Payroll Attendance Parameter")
	_set_defaults(doc)
	doc.save(ignore_permissions=True)
	_seed_holiday_quota_year()


def _is_blank(value):
	return value is None or str(value).strip() == ""


def _set_if_changed(doc, fieldname, value):
	if doc.get(fieldname) == value:
		return False
	if callable(getattr(doc, "set", None)):
		doc.set(fieldname, value)
	else:
		doc[fieldname] = value
	return True


def _legacy_paid_leave_names():
	rows = frappe.db.sql(
		"""select value
		from `tabSingles`
		where doctype='Dingtalk Attendance Settings'
		  and field='paid_leave_names'
		limit 1""",
		as_dict=True,
	)
	return rows[0].value if rows else ""


def _set_defaults(doc):
	normalized_time = normalize_time_string(doc.get("overtime_start_time"), DEFAULT_OVERTIME_START_TIME)
	_set_if_changed(doc, "overtime_start_time", normalized_time)
	if _is_blank(doc.get("paid_leave_names")):
		doc.paid_leave_names = _legacy_paid_leave_names() or "年假,丧假"
	if _is_blank(doc.get("overtime_min_minutes")):
		doc.overtime_min_minutes = 60
	if cint(doc.get("overtime_step_minutes")) <= 0:
		doc.overtime_step_minutes = 30
	if _is_blank(doc.get("overtime_cap_hours")):
		doc.overtime_cap_hours = 5
	if flt(doc.get("overtime_hours_per_day")) <= 0:
		doc.overtime_hours_per_day = 7
	if cint(doc.get("overtime_daily_divisor")) <= 0:
		doc.overtime_daily_divisor = 30


def _seed_holiday_quota_year():
	if not frappe.db.exists("DocType", "Payroll Holiday Quota Year"):
		return
	_upsert_quota_year(2026, REGULAR_QUOTAS_2026 + NON_WORKER_QUOTAS_2026)


def _upsert_quota_year(year, rows):
	name = frappe.db.get_value("Payroll Holiday Quota Year", {"year": year}, "name")
	if name:
		doc = frappe.get_doc("Payroll Holiday Quota Year", name)
	else:
		doc = frappe.get_doc({"doctype": "Payroll Holiday Quota Year", "year": year})
	existing = {
		(cint(row.holiday_month), 1 if cint(row.is_regular) else 0, str(row.holiday_name or "").strip())
		for row in doc.get("holiday_quotas")
	}
	for row in rows:
		key = (cint(row["holiday_month"]), 1 if cint(row["is_regular"]) else 0, row["holiday_name"])
		if key in existing:
			continue
		doc.append(
			"holiday_quotas",
			{
				"holiday_month": cint(row["holiday_month"]),
				"holiday_name": row["holiday_name"],
				"is_regular": cint(row["is_regular"]),
				"quota_days": flt(row["quota_days"]),
				"enabled": 1,
			},
		)
		existing.add(key)
	doc.save(ignore_permissions=True)
