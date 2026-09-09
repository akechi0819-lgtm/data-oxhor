WITH wanted AS (
  SELECT unnest(CAST(? AS VARCHAR[])) AS work_order_id
),
ranked AS (
  SELECT
    wo.*,
    ROW_NUMBER() OVER (
      PARTITION BY NULLIF(TRIM(wo.ID), '')
      ORDER BY wo.source_row_number
    ) AS rn
  FROM landing.br_work_orders__sheet_1f0596db9f25 wo
  JOIN wanted
    ON NULLIF(TRIM(wo.ID), '') = wanted.work_order_id
)
SELECT ranked.* EXCLUDE (rn)
FROM ranked
WHERE rn = 1
  AND NULLIF(TRIM(ranked.ID), '') IS NOT NULL
ORDER BY ranked.source_row_number
