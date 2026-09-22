WITH params AS (
  SELECT CAST(? AS DATE) AS start_date, CAST(? AS DATE) AS end_date
), roster AS (
  SELECT * FROM (VALUES
    ('孙伟'), ('吴子玄'), ('邓睿'), ('王洪霞'), ('王衡利'), ('杨芸聿'), ('马玥'), ('高书航')
  ) AS t(person_name)
), base AS (
  SELECT
    NULLIF(TRIM(ID), '') AS work_order_id,
    DATE '1899-12-30' + CAST(TRY_CAST(分配时间 AS DOUBLE) AS INTEGER) AS event_date,
    NULLIF(TRIM(团队), '') AS source_team,
    NULLIF(TRIM(资源主被动), '') AS resource_active_type,
    NULLIF(TRIM(咨询方式一级渠道), '') AS consult_path,
    SPLIT_PART(COALESCE(NULLIF(TRIM(咨询方式一级渠道), ''), ''), '-', 1) AS path_root,
    CASE
      WHEN INSTR(COALESCE(NULLIF(TRIM(咨询方式一级渠道), ''), ''), '-') > 0
        THEN SUBSTR(咨询方式一级渠道, INSTR(咨询方式一级渠道, '-') + 1)
      ELSE ''
    END AS path_rest,
    NULLIF(TRIM(渠道), '') AS source_channel,
    NULLIF(TRIM(一级渠道), '') AS warehouse_l1,
    NULLIF(TRIM(活动名称), '') AS campaign_name,
    NULLIF(TRIM(资源描述), '') AS resource_description,
    NULLIF(TRIM(资源录入人), '') AS resource_entry_person,
    NULLIF(TRIM(其他转介绍人), '') AS other_referrer,
    NULLIF(TRIM(转介绍人), '') AS referrer,
    NULLIF(TRIM(意向国家), '') AS intended_country,
    NULLIF(TRIM(矫正条线), '') AS corrected_line,
    NULLIF(TRIM(学生学校名称), '') AS student_school,
    NULLIF(TRIM(所在学校), '') AS current_school,
    NULLIF(TRIM(年级属性), '') AS grade_attr,
    NULLIF(TRIM(目前年级), '') AS current_grade,
    NULLIF(TRIM(年级名称), '') AS grade_name,
    source_row_number,
    ROW_NUMBER() OVER (
      PARTITION BY NULLIF(TRIM(ID), '')
      ORDER BY source_row_number
    ) AS rn
  FROM landing.br_work_orders__sheet_1f0596db9f25
), scoped AS (
  SELECT *
  FROM base, params
  WHERE rn = 1
    AND work_order_id IS NOT NULL
    AND source_team IS NULL
    AND event_date >= start_date
    AND event_date < end_date
), extracted AS (
  SELECT
    *,
    regexp_extract(
      COALESCE(campaign_name, ''),
      '(^|[-/])(孙伟|吴子玄|邓睿|王洪霞|王衡利|杨芸聿|马玥|高书航)(雅思|市场|渠道|-|（|$)',
      2
    ) AS campaign_owner,
    regexp_extract(
      COALESCE(resource_description, ''),
      '市场人员[[:space:]]*[:：][[:space:]]*(孙伟|吴子玄|邓睿|王洪霞|王衡利|杨芸聿|马玥|高书航)',
      1
    ) AS labeled_person,
    regexp_extract(
      COALESCE(resource_description, ''),
      '数据提供方[:：][^/\n]{0,120}?(孙伟|吴子玄|邓睿|王洪霞|王衡利|杨芸聿|马玥|高书航)',
      1
    ) AS provider_person,
    CASE
      WHEN COALESCE(other_referrer, '') LIKE '%不算新%'
        OR COALESCE(referrer, '') LIKE '%不算新%'
      THEN ''
      ELSE regexp_extract(
        COALESCE(other_referrer, '') || ' ' || COALESCE(referrer, ''),
        '(孙伟|吴子玄|邓睿|王洪霞|王衡利|杨芸聿|马玥|高书航)',
        1
      )
    END AS referrer_person
  FROM scoped
), attributed AS (
  SELECT
    *,
    CASE
      WHEN resource_entry_person IN (SELECT person_name FROM roster) THEN resource_entry_person
      WHEN campaign_owner <> '' THEN campaign_owner
      WHEN labeled_person <> '' THEN labeled_person
      WHEN provider_person <> '' THEN provider_person
      WHEN referrer_person <> '' THEN referrer_person
      ELSE NULL
    END AS mapped_person
  FROM extracted
), mapped AS (
  SELECT
    *,
    CASE
      WHEN path_root = '官方合作高校' THEN '官方合作高校'
      WHEN path_root = '新东方学校推荐' THEN '新东方学校推荐'
      WHEN path_root = '渠道合作' THEN '渠道合作'
      WHEN path_root = '市场活动' AND path_rest = '高校' AND source_channel = '个人代理' THEN '渠道合作'
      WHEN path_root = '市场活动' THEN '市场活动'
      ELSE '其他'
    END AS map_l1,
    CASE
      WHEN path_root = '官方合作高校' THEN '官方合作高校'
      WHEN path_root = '新东方学校推荐' AND path_rest IN ('国外考试部', '大学事业部', '大客服', '高中部', '青少部', '国游营地', '其他推荐') THEN path_rest
      WHEN path_root = '新东方学校推荐' THEN '其他推荐'
      WHEN path_root = '渠道合作' AND source_channel = '分公司个人代理' THEN '个人渠道'
      WHEN path_root = '渠道合作' AND source_channel IN ('分公司对公合作', '留学监理网') THEN '对公渠道（三方）'
      WHEN path_root = '渠道合作' THEN '其他'
      WHEN path_root = '市场活动' AND path_rest = '高校' AND source_channel = '个人代理' THEN '个人渠道'
      WHEN path_root = '市场活动' AND (
        (path_rest = '高校' AND source_channel = '高校活动')
        OR (COALESCE(path_rest, '') = '' AND source_channel = '市场活动')
      ) THEN '高校活动'
      WHEN path_root = '市场活动' AND path_rest = '中学' AND source_channel = '中学活动' THEN '中学活动'
      WHEN path_root = '市场活动' AND path_rest = '地推' AND source_channel = '地推' THEN '地推'
      WHEN path_root = '市场活动' AND (
        path_rest IN ('综合展', '现场注册', '部门展')
        OR source_channel IN ('综合展', '信息收集', '条线专展', 'F活动邀约', '其他')
      ) AND NOT (COALESCE(path_rest, '') = '' AND source_channel IN ('市场活动', '媒体/线上投放', '点对点', '小鹅通'))
        THEN '综合展'
      WHEN path_root = '市场活动' THEN '其他'
      ELSE '其他'
    END AS map_l2,
    CASE
      WHEN student_school IS NOT NULL AND student_school NOT IN ('其他', '其它', '未知', '无', '1', '0') THEN student_school
      WHEN current_school IS NOT NULL AND current_school NOT IN ('其他', '其它', '未知', '无', '1', '0') THEN current_school
      ELSE '学校待确认'
    END AS school_name,
    (
      COALESCE(student_school, '') || ' ' ||
      COALESCE(current_school, '') || ' ' ||
      COALESCE(grade_attr, '') || ' ' ||
      COALESCE(current_grade, '') || ' ' ||
      COALESCE(grade_name, '')
    ) AS school_grade_text
  FROM attributed
  WHERE mapped_person IS NOT NULL
), classified AS (
  SELECT
    *,
    CASE
      WHEN school_grade_text LIKE '%大学%'
        OR school_grade_text LIKE '%研究生%'
        OR school_grade_text LIKE '%硕士%'
        OR school_grade_text LIKE '%博士%'
        OR school_grade_text LIKE '%本科%'
        OR school_grade_text LIKE '%毕业%'
        OR school_grade_text LIKE '%在职%'
        OR school_grade_text LIKE '%研一%'
        OR school_grade_text LIKE '%研二%'
        OR school_grade_text LIKE '%研三%'
        OR grade_attr = '大学'
        OR current_grade LIKE '大%'
        OR grade_name LIKE '大%'
      THEN '大学以上'
      ELSE '大学以下'
    END AS school_band
  FROM mapped
)
SELECT
  event_date,
  map_l1 AS channel_group,
  map_l1 AS first_channel,
  map_l2 AS second_channel,
  intended_country,
  corrected_line,
  resource_active_type AS active_type,
  school_band,
  school_name,
  mapped_person,
  1.0 AS actual_value,
  'work_orders' AS metric
FROM classified
ORDER BY event_date, mapped_person, channel_group, second_channel, school_band, school_name;
