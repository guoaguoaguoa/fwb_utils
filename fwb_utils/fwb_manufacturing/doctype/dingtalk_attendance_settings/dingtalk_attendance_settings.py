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

	def _set_defaults(self):
		pass
