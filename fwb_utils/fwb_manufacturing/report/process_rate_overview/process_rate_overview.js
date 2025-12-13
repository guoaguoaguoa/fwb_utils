// Copyright (c) 2025, WenZhou Furui Handicraft Co.,Ltd. and contributors
// For license information, please see license.txt

//frappe.query_reports["Process Rate Overview"] = {
//	"filters": [
//
//	]
//};

// file: process_rate_overview.js 之类的报表 JS 文件

frappe.query_reports["Process Rate Overview"] = {
    filters: [
        {
            fieldname: "item_group",
            label: __("物料类别"),
            fieldtype: "Link",
            options: "Item Group",
            // ★ 关键代码：只显示“成品”下面的子分组
            get_query: function () {
                return {
                    filters: {
                        parent_item_group: "成品", // 父级为“成品”
                        is_group: 0                 // 只要叶子结点（可选，不要可以删掉）
                    }
                };
            }
        },
        // 你原来报表里的其它过滤器继续写在后面即可……
        // { fieldname: "workstation", ... },
        // { fieldname: "employee", ... },
    ]
};
