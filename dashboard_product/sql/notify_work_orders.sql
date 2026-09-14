WITH params AS (
  SELECT
    CAST(? AS DATE) AS start_date,
    CAST(? AS DATE) AS end_date,
    CAST(? AS VARCHAR) AS team_id,
    CAST(? AS VARCHAR) AS business_group
),
classified AS (
  SELECT
    wo.*,
    DATE '1899-12-30' + CAST(TRY_CAST(分配时间 AS DOUBLE) AS INTEGER) AS _event_date,
    CASE
      WHEN yoy_group IN ('青少', '初中') THEN '留学预备'
      ELSE yoy_group
    END AS _mapped_business_group,
    CASE
      WHEN TRIM(线上线下) = '线下' THEN 'offline_market'
      WHEN TRIM(二级渠道) = '虚拟人' THEN 'online_private'
      WHEN TRIM(线上线下) = '线上'
           AND TRIM(一级渠道) = 'TMK激活-平台'
           AND COALESCE(活动名称, '') LIKE '%校代系统资源%'
           AND NULLIF(regexp_extract(COALESCE(资源描述, ''), '市场人员[[:space:]]*[:：][[:space:]]*([^[:space:],，;；]+)', 1), '')
               IN ('王昊','马澳','张钦莉','王欣庆','谷志文','于洋','杨新宇','刘彬','李进','师顺盈','石仁达','翟昕羽','曹恒玮')
           THEN 'offline_market'
      WHEN TRIM(线上线下) = '线上' THEN 'online_platform'
    END AS _mapped_team_id
  FROM (
    SELECT
      wo.*,
      CASE
        WHEN (TRIM(团队) IN ('无法判断', '校区资源无法归属', '需要判定') OR NULLIF(TRIM(团队), '') IS NULL) AND TRIM(跟进顾问) = '张艺彤' THEN
          CASE
            WHEN TRIM(年级校正) IN ('学龄前', '一年级', '二年级', '三年级', '四年级', '五年级')
              OR TRIM(年级校正) LIKE '%小班%' OR TRIM(年级校正) LIKE '%中班%' OR TRIM(年级校正) LIKE '%大班%' THEN '青少'
            ELSE '初中'
          END
        WHEN TRIM(团队) IN ('无法判断', '校区资源无法归属', '需要判定') OR NULLIF(TRIM(团队), '') IS NULL THEN NULL
        WHEN TRIM(顾问归属) IN ('武清顾问', '塘沽顾问', '塘沽学管') OR TRIM(团队) IN ('武清', '塘沽') THEN
          CASE
            WHEN NULLIF(TRIM(年级校正), '') IS NULL OR TRIM(年级校正) = '未知' THEN '大学'
            WHEN TRIM(年级校正) IN ('学龄前', '一年级', '二年级', '三年级', '四年级', '五年级', '六年级')
              OR TRIM(年级校正) LIKE '%小班%' OR TRIM(年级校正) LIKE '%中班%' OR TRIM(年级校正) LIKE '%大班%' THEN '青少'
            WHEN TRIM(年级校正) IN ('7年级（初一）', '8年级（初二）', '9年级（初三）')
              OR TRIM(年级校正) LIKE '%初一%' OR TRIM(年级校正) LIKE '%初二%' OR TRIM(年级校正) LIKE '%初三%' THEN '初中'
            WHEN TRIM(年级校正) IN ('10年级（高一）', '11年级（高二）', '12年级（高三）')
              OR TRIM(年级校正) LIKE '%高一%' OR TRIM(年级校正) LIKE '%高二%' OR TRIM(年级校正) LIKE '%高三%' THEN '高中'
            ELSE '大学'
          END
        WHEN TRIM(顾问归属) = '青少顾问' THEN '青少'
        WHEN TRIM(顾问归属) = '初中顾问' THEN '初中'
        WHEN TRIM(顾问归属) = '高中顾问' THEN '高中'
        WHEN TRIM(顾问归属) IN ('大学顾问', '大学学管') THEN '大学'
        WHEN NULLIF(TRIM(顾问归属), '') IS NULL AND TRIM(团队) = '留学预备' THEN
          CASE
            WHEN TRIM(年级校正) IN ('学龄前', '一年级', '二年级', '三年级', '四年级', '五年级')
              OR TRIM(年级校正) LIKE '%小班%' OR TRIM(年级校正) LIKE '%中班%' OR TRIM(年级校正) LIKE '%大班%' THEN '青少'
            ELSE '初中'
          END
        WHEN TRIM(团队) = '高中' THEN '高中'
        WHEN TRIM(团队) = '大学' THEN '大学'
      END AS yoy_group
    FROM landing.br_work_orders__sheet_1f0596db9f25 wo
    WHERE TRIM(主被动) = '被动'
  ) wo
)
SELECT classified.* EXCLUDE (_event_date, _mapped_business_group, _mapped_team_id, yoy_group)
FROM classified
CROSS JOIN params
WHERE classified._mapped_team_id = params.team_id
  AND (params.business_group IS NULL OR classified._mapped_business_group = params.business_group)
  AND classified._event_date >= params.start_date
  AND classified._event_date < params.end_date
ORDER BY classified.source_row_number
