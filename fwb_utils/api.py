import frappe

@frappe.whitelist(allow_guest=True)
def ping():
    # 简单返回，验证 app 已可被 Frappe 导入与调用
    return {"ok": True, "app": "fwb_utils"}
