app_name = "fwb_utils"
app_title = "FWB Utils"
app_publisher = "WenZhou Furui Handicraft Co.,Ltd."
app_description = "Utility functions for QR generation"
app_email = "tech@freewoodenbox.com"
app_license = "MIT"
doc_events = {
    "Work Order": {
        "on_submit": "fwb_utils.fwb_manufacturing.doctype.material_readiness_check.material_readiness_check.work_order_on_submit",
        "on_cancel": "fwb_utils.fwb_manufacturing.doctype.material_readiness_check.material_readiness_check.work_order_on_cancel",
    }
}
scheduler_events = {
    "cron": {
        "30 10 * * 1": [
            "fwb_utils.fwb_manufacturing.doctype.material_readiness_check.material_readiness_check.send_material_readiness_daily_reminder"
        ],
	# 每天 9:30 发送站内提醒（Notification Log）
        "30 9 * * *": [
            "fwb_utils.fwb_manufacturing.doctype.material_readiness_check.material_readiness_check.send_material_readiness_daily_notification"
        ],
    }
}
