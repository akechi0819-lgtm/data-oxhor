"""Compare sealed daily warehouse candidates on the same historical window."""
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb

from dashboard_product.shadow_bi.sql_warehouse.foundation import TABLES
from dashboard_product.shadow_bi.sql_warehouse.metrics import TRAINING_HEAD_CASH_MINIMUM
from dashboard_product.shadow_bi.sql_warehouse.relations import quote
from data_acquisition.jobs.bi_window_merge import rolling_start_date


# Same selection and qualification as business.team_values for the market total.
# Fix the period independently of either warehouse's published clock.
_METRICS = """
WITH facts AS (
    SELECT f.* FROM business.scoped_facts f CROSS JOIN config.clock c
    WHERE unit_id='total' AND acquisition_scope='全部'
      AND event_date::DATE BETWEEN (SELECT start_date FROM business.periods WHERE period_id='FY27') AND ?
      AND (business_line='training' OR event_date::DATE BETWEEN c.abroad_start AND c.abroad_through)
), totals AS (
    SELECT business_line,
           sum(value) FILTER (WHERE metric='orders') AS orders,
           round(sum(value) FILTER (WHERE metric='cash'), 2) AS cash,
           sum(value) FILTER (WHERE metric='cash' AND value<0) AS negative_cash,
           count(*) FILTER (WHERE metric='cash' AND value<0) AS negative_rows
    FROM facts GROUP BY business_line
), qualified_training AS (
    SELECT student_id FROM facts
    WHERE business_line='training' AND metric='cash' AND nullif(trim(student_id),'') IS NOT NULL
    GROUP BY student_id,class_code HAVING abs(sum(value))>=? AND bool_or(registration_count>0)
), heads AS (
    SELECT 'training' AS name, count(DISTINCT student_id) AS heads FROM qualified_training
    UNION ALL SELECT customer_domain, count(DISTINCT student_id)
    FROM facts WHERE business_line='abroad' AND metric='cash' AND value>0
      AND nullif(trim(student_id),'') IS NOT NULL AND customer_domain IN ('study_abroad','small_language')
    GROUP BY customer_domain
)
SELECT l.name, coalesce(t.orders,0), coalesce(t.cash,0), coalesce(t.negative_cash,0),
       coalesce(t.negative_rows,0), coalesce(h.heads,0)
FROM (VALUES ('training'),('abroad'),('study_abroad'),('small_language')) l(name)
LEFT JOIN totals t ON t.business_line=l.name LEFT JOIN heads h USING(name)
"""


def _warehouse_values(database: Path, start: date, through: date) -> tuple[dict, dict]:
    dates = ('分配时间', '业务日期', 'event_date', 'event_date', 'event_date')
    tables = TABLES['training'] + TABLES['abroad']
    with duckdb.connect(str(database), read_only=True, config={'threads': 2}) as connection:
        rows = {}
        for table, column in zip(tables, dates, strict=True):
            day = (f"DATE '1899-12-30' + floor(try_cast({quote(column)} AS DOUBLE))::INT"
                   if table in TABLES['training'] else f"try_cast({quote(column)} AS DATE)")
            rows[table] = connection.execute(
                f"SELECT count(*), count(*) FILTER (WHERE {day} BETWEEN ? AND ?) "
                f"FROM landing.{quote(table)}", [start, through]
            ).fetchone()
        metrics = {row[0]: row[1:] for row in connection.execute(_METRICS, [through, TRAINING_HEAD_CASH_MINIMUM]).fetchall()}
    return rows, metrics


def _change(before, after) -> dict:
    before, after = Decimal(str(before)), Decimal(str(after))
    difference = after - before
    return {'before': str(before), 'after': str(after), 'difference': str(difference),
            'ratio': float(difference / abs(before)) if before else None}


def compare_releases(*, baseline: Path, candidate: Path,
                     baseline_through: str, candidate_through: str) -> dict:
    previous_day, candidate_day = map(date.fromisoformat, (baseline_through, candidate_through))
    through = min(previous_day, candidate_day)
    start = date.fromisoformat(rolling_start_date(through))
    blocks = []
    warnings = []
    report = {'baseline_through': baseline_through, 'candidate_through': candidate_through,
              'common_through': through.isoformat(), 'row_window_start': start.isoformat(),
              'blocks': blocks, 'warnings': warnings, 'rows': {}, 'metrics': {}}
    if candidate_day < previous_day:
        blocks.append('coverage_regressed')
    old_rows, old_metrics = _warehouse_values(baseline, start, through)
    new_rows, new_metrics = _warehouse_values(candidate, start, through)
    for table, (total, window) in new_rows.items():
        before_total, before_window = old_rows[table]
        change = _change(before_window, window)
        report['rows'][table] = {**change, 'before_total': before_total, 'after_total': total}
        if not total:
            blocks.append(f'{table}:empty')
        if change['ratio'] is not None and change['ratio'] < -.30:
            blocks.append(f'{table}:row_loss')
        if change['ratio'] is None:
            warnings.append(f'{table}:zero_comparison_baseline')

    metric_indices = {'orders': 0, 'cash': 1, 'heads': 4}
    comparisons = {'training': ('orders', 'cash', 'heads'), 'abroad': ('orders', 'cash'),
                   'study_abroad': ('heads',), 'small_language': ('heads',)}
    for scope, metrics in comparisons.items():
        previous, current = old_metrics[scope], new_metrics[scope]
        for metric in metrics:
            index = metric_indices[metric]
            key = f'{scope}.{metric}'
            change = _change(previous[index], current[index])
            report['metrics'][key] = change
            drop = -Decimal(change['difference'])
            ratio = change['ratio']
            if ratio is None:
                warnings.append(f'{key}:zero_comparison_baseline')
            if metric == 'cash':
                if ratio is not None and ratio < -.15:
                    blocks.append(f'{key}:retraction')
                elif drop > 0 and Decimal(str(previous[2])) - Decimal(str(current[2])) >= drop:
                    change['negative_cash_rows'] = current[3]
                    warnings.append(f'{key}:negative_cash_retraction')
            elif drop > 50 or (drop > 10 and ratio is not None and ratio < -.02):
                blocks.append(f'{key}:retraction')
    report['status'] = 'blocked' if blocks else 'warning' if warnings else 'passed'
    return report
