"""Freeze official study-abroad reference values into a local SQL release."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path


def install_scorecard(con, scorecard_path, *, warehouse_coverage_start, warehouse_coverage_end,
                      comparison_contract=None):
    """Install only in the candidate DB, after business periods and values exist.

    An explicitly approved comparison contract can bind source periods and
    channels to the same version of the official scorecard.
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
                    # The official source explicitly states that the fiscal calendar dates
                    # are unspecified. Do not infer dates from the dashboard's calendar.
                    rows.append((scorecard_id, version, digest, captured_at, period, None, None,
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
    con.execute('''CREATE TABLE ref.scorecard_comparison_contract (
        period VARCHAR, scope VARCHAR, dimension VARCHAR, metric VARCHAR, period_start DATE, period_end DATE,
        segments VARCHAR[], first_channels VARCHAR[], approval_reference VARCHAR
    )''')
    if comparison_contract is not None:
        if comparison_contract.get('source_sha256') != digest:
            raise ValueError('scorecard comparison contract source hash mismatch')
        approval = comparison_contract.get('approval_reference')
        resources = comparison_contract.get('resource_comparisons', [])
        amounts = comparison_contract.get('gross_signing_comparisons', [])
        if (not isinstance(approval, str) or not approval.strip()
                or not isinstance(resources, list) or not isinstance(amounts, list)):
            raise ValueError('scorecard comparison contract requires approval and comparisons')
        entries = []
        comparisons = [(item, '资源数') for item in resources] + [(item, '毛签万元') for item in amounts]
        for item, metric in comparisons:
            period, scope, dimension = item['period'], item['scope'], item['dimension']
            period_start, period_end = date.fromisoformat(item['period_start']), date.fromisoformat(item['period_end'])
            segments, channels = item['segments'], item['first_channels']
            if (not all(isinstance(v, str) and v for v in (period, scope, dimension))
                    or scope not in ('online', 'offline') or period_start > period_end
                    or not isinstance(segments, list) or not segments
                    or not isinstance(channels, list) or not channels
                    or not all(isinstance(v, str) and v for v in segments + channels)
                    or (metric == '毛签万元' and item.get('definition') != 'positive_signature_yuan')):
                raise ValueError('invalid scorecard comparison')
            entries.append((period, scope, dimension, metric, period_start, period_end, segments, channels, approval))
        if len({entry[:4] for entry in entries}) != len(entries):
            raise ValueError('duplicate scorecard comparison')
        if entries:
            con.executemany('INSERT INTO ref.scorecard_comparison_contract VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', entries)
    # Bounds are already parsed dates, not user-provided SQL fragments.
    con.execute(f'''CREATE VIEW mart.study_abroad_summary AS
        WITH matched AS (
          SELECT o.*, c.period_start AS approved_start, c.period_end AS approved_end,
                 c.segments, c.first_channels, c.approval_reference,
                 CASE WHEN o.row_kind IN ('annual_target', 'target') THEN 'official_target'
                      WHEN o.row_kind LIKE '%completion%' THEN 'official_completion_rate'
                      WHEN c.period IS NULL THEN 'comparison_contract_missing'
                      WHEN NOT ((o.metric='资源数' AND o.unit='资源/工单数')
                             OR (o.metric='毛签万元' AND o.unit='毛签万元')) THEN 'metric_or_unit_not_approved'
                      WHEN c.period_start < DATE '{start}' OR c.period_end > DATE '{end}' THEN 'warehouse_coverage_incomplete'
                      ELSE NULL END AS reason
          FROM ref.official_scorecard o
          LEFT JOIN ref.scorecard_comparison_contract c
            ON c.period=o.period AND c.scope=o.scope AND c.dimension=o.dimension AND c.metric=o.metric
        ), compared AS (
          SELECT m.*, CASE WHEN m.reason IS NULL THEN (
            SELECT CASE WHEN m.metric='资源数'
                        THEN COUNT(DISTINCT NULLIF(TRIM(f.resource_id), ''))::DOUBLE
                        ELSE COALESCE(SUM(f.value), 0)::DOUBLE / 10000 END
            FROM business.abroad_facts f
            WHERE f.customer_domain='study_abroad'
              AND ((m.metric='资源数' AND f.metric='orders')
                   OR (m.metric='毛签万元' AND f.metric='cash' AND f.value>0))
              AND TRY_CAST(f.event_date AS DATE) BETWEEN m.approved_start AND m.approved_end
              AND list_contains(m.segments, f.segment_id)
              AND list_contains(m.first_channels, f.first_channel)
          ) END AS measured_value
          FROM matched m
        )
        SELECT scorecard_id, source_version, source_sha256, period,
               approved_start AS period_start, approved_end AS period_end,
               scope, dimension, row_kind, metric, unit, official_value,
               measured_value AS warehouse_value, measured_value - official_value AS delta,
               'official_scorecard' AS authority_source,
               reason AS comparability_reason, approval_reference AS comparison_approval
        FROM compared
        UNION ALL
        SELECT NULL, NULL, NULL, p.period_id, greatest(p.start_date, DATE '{start}'),
               least(p.through_date, DATE '{end}'),
               CASE v.unit_id WHEN 'online_scope' THEN 'online' ELSE 'offline' END,
               'warehouse_study_and_small_language', 'actual', m.metric, m.unit, NULL,
               m.value, NULL, 'warehouse', 'separate_warehouse_scope', NULL
        FROM business.team_values v JOIN business.periods p USING (period_id)
        CROSS JOIN LATERAL (VALUES ('orders', 'count', v.orders), ('cash', 'yuan', v.cash), ('heads', 'count', v.heads)) m(metric, unit, value)
        WHERE v.business_line='abroad' AND v.comparison='actual' AND v.acquisition_scope='全部'
          AND v.unit_id IN ('online_scope', 'offline_scope') AND p.through_date IS NOT NULL
          AND p.start_date <= DATE '{end}' AND p.through_date BETWEEN DATE '{start}' AND DATE '{end}'
    ''')
    return {'scorecard_id': scorecard_id, 'source_version': version, 'source_sha256': digest, 'row_count': len(rows)}
