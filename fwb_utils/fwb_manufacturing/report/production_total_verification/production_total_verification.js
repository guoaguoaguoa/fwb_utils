// v2026.01.10.01 - 生产总数核对报告前端配置

frappe.query_reports["Production Total Verification"] = {
    "filters": [
        {
            "fieldname": "from_date",
            "label": __("开始于"),
            "fieldtype": "Date",
            "default": frappe.datetime.add_months(frappe.datetime.get_today(), -1),
            "reqd": 0
        },
        {
            "fieldname": "to_date",
            "label": __("结束于"),
            "fieldtype": "Date",
            "default": frappe.datetime.get_today(),
            "reqd": 0
        },
        {
            "fieldname": "work_order",
            "label": __("工单号"),
            "fieldtype": "Link",
            "options": "Work Order",
            "get_query": () => {
                // 仅允许选择未取消的工单
                return {
                    filters: { "docstatus": ["<", 2] }
                };
            }
        },
        {
            "fieldname": "product_name",
            "label": __("产品名 (支持模糊)"),
            "fieldtype": "Data" 
            // 使用 Data 类型，配合 Python 里的 LIKE 语句实现模糊搜索
        }
    ],
    
    // 格式化器：可以在这里给特定的单元格加颜色
    "formatter": function(value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);
        
        // 如果想高亮某些列，例如只要有数就变粗体
        if (["woodworking_qty", "primer_qty", "top_coat_qty", "assembly_qty", "polishing_qty", "lining_qty"].includes(column.fieldname)) {
            if (data[column.fieldname] > 0) {
                value = `<span style="font-weight:bold; color:#2c3e50;">${value}</span>`;
            } else {
                value = `<span style="color:#bdc3c7;">0</span>`;
            }
        }
        
        return value;
    }
};
