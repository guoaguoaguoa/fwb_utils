app_name = "fwb_utils"
app_title = "FWB Utils"
app_publisher = "WenZhou Furui Handicraft Co.,Ltd."
app_description = "ERPNext manufacturing reporting, QC, and wage settlement extensions"
app_email = "tech@freewoodenbox.com"
app_license = "MIT"

doctype_js = {
    "Salary Slip": "public/js/salary_slip.js",
}

doc_events = {
    "Work Order": {
        "on_submit": "fwb_utils.fwb_manufacturing.doctype.material_readiness_check.material_readiness_check.work_order_on_submit",
        "on_cancel": "fwb_utils.fwb_manufacturing.doctype.material_readiness_check.material_readiness_check.work_order_on_cancel",
    },
}

scheduler_events = {
    "cron": {
        # 每天 9:00 触发一次，下面的字符前到后的顺序分别代表：分钟、小时、每月的第几天、月份、星期几
        "30 10 * * 1": [
            "fwb_utils.fwb_manufacturing.doctype.material_readiness_check.material_readiness_check.send_material_readiness_daily_reminder"
        ],
        # 每天 9:30 发送站内提醒（Notification Log）
        "30 9 * * *": [
            "fwb_utils.fwb_manufacturing.doctype.material_readiness_check.material_readiness_check.send_material_readiness_daily_notification"
        ],
        # 钉钉考勤 API：默认由 Dingtalk Attendance Settings.enable_auto_sync 控制，未启用时 no-op
        "10 5 * * *": [
            "fwb_utils.fwb_manufacturing.dingtalk_attendance_api.sync_rolling_dingtalk_attendance"
        ],
        # 月度核对：每小时触发，由 enable_monthly_sync + 触发日(1-28)/时(0-23) 控制；未到点立即 no-op，不调 API
        "0 * * * *": [
            "fwb_utils.fwb_manufacturing.dingtalk_attendance_api.sync_monthly_dingtalk_attendance"
        ],
    }
}

# 这里开始是本次新增的部分 ---------------------------
# 告诉 Frappe：我要把哪些“配置类的东西”导出成 fixtures
fixtures = [
    # 1) 如果以后有真正的 Custom Doctype（界面上“自定义？”打勾），并且模块是 Fwb Manufacturing，就一起导出
  #  {
  #      "doctype": "DocType",
  #      "filters": [
  #         ["module", "=", "Fwb Manufacturing"],
  #          ["custom", "=", 0],
  #      ],
  #  },

  #  # 2) Fwb Manufacturing 模块下的所有报表（Report）
  #  {
  #      "doctype": "Report",
  #      "filters": [
  #          ["module", "=", "Fwb Manufacturing"],
  #      ],
  #  },

    # 3) Fwb Manufacturing 模块下的所有 Server Script
    {
        "doctype": "Server Script",
        "filters": [
            ["module", "=", "Fwb Manufacturing"],
        ],
    },
    

    {
        "doctype": "Stock Settings",
        "filters": [
            ["name", "=", "Stock Settings"],
        ],
    },




    # 4) Fwb Manufacturing 模块下的所有 Client Script
    {
        "doctype": "Client Script",
        "filters": [
            ["module", "=", "Fwb Manufacturing"],
        ],
    },

  #  # 5) Fwb Manufacturing 模块下的页面（Factory Control Tower 等）
  #  {
  #      "doctype": "Page",
  #      "filters": [
  #          ["name", "in", ["factory-control-towe"]],
  #      ],
  #  },

    # 6) 自定义字段：BOM / Employee / Work Order / Salary Slip / BOM Operation
    #    + Salary Structure Assignment（工龄/等级/证书/宿舍租金 基数，喂底薪同款考勤公式，分行随考勤）
    #    这里就把你盘点清单里提到的那几个都一网打尽
    {
        "doctype": "Custom Field",
        "filters": [
            ["dt", "in", ["BOM", "Employee", "Work Order", "Salary Slip", "BOM Operation", "Salary Structure Assignment", "Attendance"]],
        ],
    },

    # 7) 这些 DocType 上做的 Property Setter（属性修改）,针对原生表单的配置和修改，把表单名字放到下面，就会自动被识别出被改动的地方
    {
        "doctype": "Property Setter",
        "filters": [
            ["doc_type", "in", ["BOM", "Employee", "Work Order", "Salary Slip", "BOM Operation", "Item", "Attendance"]],
        ],
    },
]
# --------------------------- 新增部分结束
