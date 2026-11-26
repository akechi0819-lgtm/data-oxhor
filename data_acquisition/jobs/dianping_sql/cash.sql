WITH all_orders AS (
 SELECT "ID", nullif(trim("学员号"),'') AS student_no,
 DATE '1899-12-30'+cast(cast("分配时间" AS DOUBLE) AS INTEGER) AS assigned_date,"二级渠道"
 FROM landing.br_work_orders__sheet_1f0596db9f25
), counts AS (
 SELECT student_no,count(DISTINCT "ID") AS student_order_count FROM all_orders WHERE student_no IS NOT NULL GROUP BY student_no
), target AS (
 SELECT w.*,coalesce(c.student_order_count,0) AS student_order_count FROM all_orders w LEFT JOIN counts c USING(student_no)
 WHERE trim("二级渠道")='大众点评' AND assigned_date BETWEEN ? AND ?
), candidates AS (
 SELECT w.*, c.source_row_number AS cash_row,c."业务日期" AS cash_date,c."现金收入" AS amount,c."课程产品名称" AS course,
 CASE WHEN trim(c."工单ID")=w."ID" AND coalesce(nullif(trim(c."工单ID__2"),''),w."ID")=w."ID" THEN 'order_id'
 WHEN nullif(trim(c."工单ID"),'') IS NULL AND nullif(trim(c."工单ID__2"),'') IS NULL AND w.student_no IS NOT NULL AND trim(c."学员编号")=w.student_no AND w.student_order_count=1 THEN 'unique_student_no' END AS method
 FROM target w LEFT JOIN landing.br_cash__sheet_39b8dee2e4b3 c ON trim(c."工单ID")=w."ID" OR trim(c."工单ID__2")=w."ID" OR (w.student_no IS NOT NULL AND trim(c."学员编号")=w.student_no)
)
SELECT "ID",student_no,student_order_count,count(cash_row) AS candidate_rows,
 count(cash_row) FILTER(WHERE method IS NOT NULL) AS matched_rows,
 count(cash_row) FILTER(WHERE method='order_id') AS direct_rows,
 count(cash_row) FILTER(WHERE method='unique_student_no') AS student_rows,
 round(sum(cast(amount AS DECIMAL(18,4))) FILTER(WHERE method IS NOT NULL),2) AS total_cash,
 min(DATE '1899-12-30'+cast(cast(cash_date AS DOUBLE) AS INTEGER)) FILTER(WHERE method IS NOT NULL AND cast(amount AS DECIMAL(18,4))>0) AS first_positive_date,
 string_agg(DISTINCT nullif(trim(course),''),'；' ORDER BY nullif(trim(course),'')) FILTER(WHERE method IS NOT NULL) AS courses,
 string_agg(cast(cash_row AS VARCHAR),',' ORDER BY cash_row) FILTER(WHERE method IS NOT NULL) AS matched_cash_source_rows
FROM candidates GROUP BY "ID",student_no,student_order_count ORDER BY "ID"
