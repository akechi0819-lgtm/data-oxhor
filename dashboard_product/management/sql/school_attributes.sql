-- 仅读取学校画像维度，现金按原行归类；工单学校名映射由宿主共享计算检查唯一性。
SELECT source_row_number, NULLIF(TRIM(生源校),'') AS school_name,
       NULLIF(TRIM("生源校画像属性-大类"),'') AS school_attribute
FROM landing.br_cash__sheet_39b8dee2e4b3
ORDER BY source_row_number
