# Copyright (c) 2026, WenZhou Furui Handicraft Co.,Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import cint


class DingtalkAttendanceSettings(Document):
	def onload(self):
		self._set_defaults()

	def validate(self):
		self._set_defaults()
		self.rolling_days = min(max(cint(self.rolling_days) or 7, 1), 31)
		self.result_page_limit = min(max(cint(self.result_page_limit) or 50, 1), 50)
		self.timeout_seconds = min(max(cint(self.timeout_seconds) or 20, 5), 120)
		if not self.enable_result_sync and not self.enable_detail_sync:
			frappe.throw("至少启用一个同步接口：获取打卡结果 或 获取打卡详情。")
		self._validate_monthly_sync()

	def _validate_monthly_sync(self):
		# 不预制 day/hour：仅当启用月度核对时才强制其在合法范围（未启用可留空）。
		if not cint(self.enable_monthly_sync):
			return
		day = cint(self.monthly_sync_day)
		hour = cint(self.monthly_sync_hour)
		if not (1 <= day <= 28):
			frappe.throw("启用月度核对同步后，月度触发日必须在 1–28。")
		if not (0 <= hour <= 23):
			frappe.throw("启用月度核对同步后，月度触发时必须在 0–23。")

	def _set_defaults(self):
		pass
