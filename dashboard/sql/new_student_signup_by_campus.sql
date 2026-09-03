-- 新生报名口径（按校区归属）：
-- 1. 团队限定为 初中、初中国际学科、青少；新老生类型=新生。
-- 2. 人头按学员编号去重；仅当同一学员编号+班级编码在筛选窗口内的报入现金收入净额绝对值 >= 1500，且报名人次>0 时计入。
-- 3. 报入现金按正向报入现金收入汇总；报名单笔=正向报入现金/合格去重人头。
WITH params AS (
  SELECT CAST(? AS DATE) AS start_date, CAST(? AS DATE) AS end_date
), base AS (
  SELECT
    NULLIF(TRIM("{{学员编号}}"), '') AS student_id,
    NULLIF(TRIM("{{班级编码}}"), '') AS class_code,
    NULLIF(TRIM("{{校区归属}}"), '') AS campus,
    TRY_CAST("{{报名人次}}" AS DOUBLE) AS signup_count,
    TRY_CAST("{{报入现金收入}}" AS DOUBLE) AS reported_cash
  FROM landing.br_cash__sheet_39b8dee2e4b3, params
  WHERE source_row_number > 1
    AND DATE '1899-12-30' + CAST(TRY_CAST("{{业务日期}}" AS DOUBLE) AS INTEGER) >= start_date
    AND DATE '1899-12-30' + CAST(TRY_CAST("{{业务日期}}" AS DOUBLE) AS INTEGER) < end_date
    AND TRIM("{{新老生类型}}") = '新生'
    AND TRIM("{{团队}}") IN ('初中', '初中国际学科', '青少')
), qualified AS (
  SELECT *,
    SUM(COALESCE(reported_cash, 0)) OVER (PARTITION BY student_id, class_code) AS student_class_net_cash
  FROM base
), campus_rollup AS (
  SELECT
    campus,
    SUM(CASE WHEN reported_cash > 0 THEN reported_cash ELSE 0 END) AS positive_reported_cash,
    COUNT(DISTINCT CASE
      WHEN ABS(student_class_net_cash) >= 1500 AND COALESCE(signup_count, 0) > 0
      THEN student_id
    END) AS qualified_student_count
  FROM qualified
  GROUP BY campus
)
SELECT
  campus,
  positive_reported_cash,
  qualified_student_count,
  ROUND(positive_reported_cash / NULLIF(qualified_student_count, 0), 0) AS signup_unit_price
FROM campus_rollup
UNION ALL
SELECT
  '总计',
  SUM(CASE WHEN reported_cash > 0 THEN reported_cash ELSE 0 END),
  COUNT(DISTINCT CASE
    WHEN ABS(student_class_net_cash) >= 1500 AND COALESCE(signup_count, 0) > 0
    THEN student_id
  END),
  ROUND(
    SUM(CASE WHEN reported_cash > 0 THEN reported_cash ELSE 0 END) /
    NULLIF(COUNT(DISTINCT CASE
      WHEN ABS(student_class_net_cash) >= 1500 AND COALESCE(signup_count, 0) > 0
      THEN student_id
    END), 0),
    0
  )
FROM qualified
ORDER BY campus;
