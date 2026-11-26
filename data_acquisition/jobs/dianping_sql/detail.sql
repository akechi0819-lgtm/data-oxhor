SELECT "ID", "资源id", "姓名", "资源描述", "年级名称", "团队", "学生学校名称", "咨询课程名称", "跟进顾问", "工单状态", "工单等级", "财季", "学员号",
 DATE '1899-12-30'+cast(cast("分配时间" AS DOUBLE) AS INTEGER) AS assigned_date
FROM landing.br_work_orders__sheet_1f0596db9f25
WHERE trim("二级渠道")='大众点评' AND DATE '1899-12-30'+cast(cast("分配时间" AS DOUBLE) AS INTEGER)BETWEEN ? AND ?
ORDER BY assigned_date,"ID"
