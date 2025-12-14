app_name = "fwb_utils"
app_title = "FWB Utils"
app_publisher = "WenZhou Furui Handicraft Co.,Ltd."
app_description = "Utility functions for QR generation"
app_email = "tech@freewoodenbox.com"
app_license = "MIT"

doc_events = {
    "Work Order": {
        # 你原来这里的路径保持不动，我只保留结构，具体函数名用你自己现有的
        "on_submit": "fwb_utils.fwb_manufacturing.doctype.material_readiness_check.material_readiness_check.on_work_order_submit",
        "on_cancel": "fwb_utils.fwb_manufacturing.doctype.material_readiness_check.material_readiness_check.on_work_order_cancel",
    }
}

scheduler_events = {
    "cron": {
        # 周一 10:30
        "30 10 * * 1": [
            "fwb_utils.fwb_manufacturing.doctype.material_readiness_check.material_readiness_check.daily_notify_unready_materials"
        ],
        # 每天 9:30
        "30 9 * * *": [
            "fwb_utils.fwb_manufacturing.doctype.material_readiness_check.material_readiness_check.daily_notify_unready_materials"
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

    # 2) Fwb Manufacturing 模块下的所有报表（Report）
    {
        "doctype": "Report",
        "filters": [
            ["module", "=", "Fwb Manufacturing"],
        ],
    },

    # 3) Fwb Manufacturing 模块下的所有 Server Script
    {
        "doctype": "Server Script",
        "filters": [
            ["module", "=", "Fwb Manufacturing"],
        ],
    },

    # 4) Fwb Manufacturing 模块下的所有 Client Script
    {
        "doctype": "Client Script",
        "filters": [
            ["module", "=", "Fwb Manufacturing"],
        ],
    },

    # 5) Fwb Manufacturing 模块下的页面（Factory Control Tower 等）
    {
        "doctype": "Page",
        "filters": [
            ["name", "in", ["factory-control-towe"]],
        ],
    },

    # 6) 自定义字段：BOM / Employee / Work Order / Salary Slip / BOM Operation
    #    这里就把你盘点清单里提到的那几个都一网打尽
    {
        "doctype": "Custom Field",
        "filters": [
            ["name", "in", [
                "BOM-custom_size_l",
                "BOM-custom_size_w",
                "BOM-custom_size_h",
                "Employee-custom_section_break_5pjzz",
                "Employee-custom_多工种关联",
                "Salary Slip-custom_section_break_ap1nx",
                "Salary Slip-custom_manufacturing_wage_details",
                "Work Order-custom_section_break_jkoar",
                "Work Order-custom_qr_code",
                "BOM Operation-custom_piece_rate",
            ]],
        ],
    },

    # 7) 这些 DocType 上做的 Property Setter（属性修改）
    {
        "doctype": "Property Setter",
        "filters": [
            ["doc_type", "in", ["BOM", "Employee", "Work Order", "Salary Slip", "BOM Operation"]],
        ],
    },
]
# --------------------------- 新增部分结束
