"""Freeze official study-abroad reference values into a local SQL release."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, timedelta
from pathlib import Path


def _period_dates(period):
    match = re.fullmatch(r'FY(\d{2})(?:-Q([1-4]))?', period)
    if not match:
        return None, None
    year = 2000 + int(match.group(1)) - 1
    quarter = match.group(2)
    if quarter is None:
        return date(year, 6, 1), date(year + 1, 5, 31)
    month_index = 5 + (int(quarter) - 1) * 3
    start = date(year + month_index // 12, month_index % 12 + 1, 1)
    next_index = month_index + 3
    next_start = date(year + next_index // 12, next_index % 12 + 1, 1)
    return start, next_start - timedelta(days=1)


def install_scorecard(con, scorecard_path, *, warehouse_coverage_start, warehouse_coverage_end):
    """Install only in the candidate DB, after business periods and values exist.

    Warehouse rows remain separate: their combined study/small-language scope has
    not been established as comparable to any official scorecard dimension.
    """
    start = date.fromisoformat(str(warehouse_coverage_start))
    end = date.fromisoformat(str(warehouse_coverage_end))
    if end < start:
        raise ValueError('invalid study-abroad warehouse coverage')
    content = Path(scorecard_path).read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    document = json.loads(content)
    version = document['schema_version']
    scorecard_id = document['scorecard_id']
    captured_at = document['captured_at']
    units = document['units']
    metric_units = {'资源数': 'resource_count', '总资源': 'resource_count',
                    '签约数': 'signed_count', '总签约数': 'signed_count',
                    '签约率': 'sign_rate', '毛签万元': 'gross_signed_amount'}
    if not all(isinstance(x, str) and x for x in (version, scorecard_id, captured_at)):
        raise ValueError('invalid scorecard identity')
    rows = []
    for scope in ('online', 'offline'):
        for record in document[scope]['rows']:
            period, row_kind = record['period'], record['row_kind']
            if not isinstance(period, str) or not isinstance(row_kind, str) or not period or not row_kind:
                raise ValueError('invalid scorecard period or row kind')
            period_start, period_end = _period_dates(period)
            for dimension, values in record.items():
                if dimension in ('period', 'row_kind'):
                    continue
                measures = values.items() if isinstance(values, dict) else [(dimension, values)]
                for metric, value in measures:
                    if value is None:
                        continue
                    if isinstance(value, bool) or not isinstance(value, (int, float)):
                        raise ValueError('invalid scorecard measure')
                    unit = units.get(metric_units.get(metric, '')) if isinstance(values, dict) else None
                    rows.append((scorecard_id, version, digest, captured_at, period, period_start, period_end,
                                 scope, dimension if isinstance(values, dict) else 'scope_share', row_kind, metric, unit, value))
    if not rows:
        raise ValueError('scorecard has no measures')
    con.execute('CREATE SCHEMA IF NOT EXISTS ref')
    con.execute('CREATE SCHEMA IF NOT EXISTS mart')
    con.execute('''CREATE TABLE ref.official_scorecard (
        scorecard_id VARCHAR, source_version VARCHAR, source_sha256 VARCHAR, captured_at VARCHAR,
        period VARCHAR, period_start DATE, period_end DATE, scope VARCHAR, dimension VARCHAR,
        row_kind VARCHAR, metric VARCHAR, unit VARCHAR, official_value DOUBLE
    )''')
    con.executemany('INSERT INTO ref.official_scorecard VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', rows)
    # Bounds are already parsed dates, not user-provided SQL fragments.
    con.execute(f'''CREATE VIEW mart.study_abroad_summary AS
        SELECT scorecard_id, source_version, source_sha256, period, period_start, period_end,
               scope, dimension, row_kind, metric, unit, official_value,
               NULL::DOUBLE AS warehouse_value, NULL::DOUBLE AS delta,
               'official_scorecard' AS authority_source,
               'scope_or_metric_not_verified_comparable' AS comparability_reason
        FROM ref.official_scorecard
        UNION ALL
        SELECT NULL, NULL, NULL, p.period_id, greatest(p.start_date, DATE '{start}'),
               least(p.through_date, DATE '{end}'),
               CASE v.unit_id WHEN 'online_scope' THEN 'online' ELSE 'offline' END,
               'warehouse_study_and_small_language', 'actual', m.metric, m.unit, NULL,
               m.value, NULL, 'warehouse', 'separate_warehouse_scope'
        FROM business.team_values v JOIN business.periods p USING (period_id)
        CROSS JOIN LATERAL (VALUES ('orders', 'count', v.orders), ('cash', 'yuan', v.cash), ('heads', 'count', v.heads)) m(metric, unit, value)
        WHERE v.business_line='abroad' AND v.comparison='actual' AND v.acquisition_scope='全部'
          AND v.unit_id IN ('online_scope', 'offline_scope') AND p.through_date IS NOT NULL
          AND p.start_date <= DATE '{end}' AND p.through_date BETWEEN DATE '{start}' AND DATE '{end}'
    ''')
    return {'scorecard_id': scorecard_id, 'source_version': version, 'source_sha256': digest, 'row_count': len(rows)}
