"""经营范围、期间和人头都在 SQL 中计算；没有逐事实 Python 汇总。"""
from pathlib import Path
import json

from .relations import load_rows


TRAINING_HEAD_CASH_MINIMUM = 1500


def install_head_threshold(con):
    con.execute('CREATE SCHEMA IF NOT EXISTS core')
    con.execute('CREATE OR REPLACE MACRO core.head_cash_meets_threshold(amount) AS '
                f'COALESCE(ABS(amount) >= {TRAINING_HEAD_CASH_MINIMUM}, FALSE)')


def install_metrics(con, *, through, abroad_start, abroad_through, config_root):
    con.execute('CREATE SCHEMA IF NOT EXISTS business')
    install_head_threshold(con)
    con.execute('CREATE SCHEMA IF NOT EXISTS mart')
    con.execute('CREATE SCHEMA IF NOT EXISTS config')
    con.execute('CREATE OR REPLACE TABLE config.clock (through_date DATE, abroad_start DATE, abroad_through DATE)')
    con.execute('INSERT INTO config.clock VALUES (?,?,?)', [through, abroad_start, abroad_through])
    # These are existing fixed target tables, not calculations over customer facts.
    root = Path(config_root)
    training = json.loads((root / 'dashboard_product/config/project_targets.json').read_text())
    abroad = json.loads((root / 'dashboard_product/config/offline_market_targets.json').read_text())
    online = json.loads((root / 'dashboard_product/online_team/config/study_abroad_targets.json').read_text())
    targets = []
    for g in training['business_groups'].values():
        for family in ('months', 'quarters'):
            for period, teams in g.get(family, {}).items():
                for team, values in teams.items():
                    for field, metric in [('work_order_target', 'orders'), ('passive_cash_target', 'cash')]:
                        targets.append(dict(business_line='training', business_group=g['display_name'],
                                            team_id=team, period_id=period, metric=metric, target=values.get(field)))
    for unit, cfg in [('university', abroad), ('online', online)]:
        orders = (cfg.get('study_abroad', {}).get('resource_target') or cfg.get('resource_target', {})) if unit == 'online' else cfg.get('total', {})
        if unit == 'university':
            orders = {**orders, 'annual': orders.get('work_order_target')}
        for metric, source, factor in [('orders', orders, 1), ('cash', cfg.get('cash', {}).get('total', {}), 10000)]:
            for period, amount in [('FY27', source.get('annual')), *source.get('months', {}).items(), *source.get('quarters', {}).items()]:
                targets.append(dict(business_line='abroad', business_group=None, team_id=unit,
                                    period_id=period, metric=metric, target=None if amount is None else amount * factor))
    load_rows(con, 'config', 'targets', targets, columns={
        'business_line':'VARCHAR', 'business_group':'VARCHAR', 'team_id':'VARCHAR',
        'period_id':'VARCHAR', 'metric':'VARCHAR', 'target':'DECIMAL(24,2)'})
    # Fixtures can supply pre-normalized facts directly. Production candidates
    # retain the controlled input tables and their normalization configuration.
    source_exists = con.execute("""
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema='source' AND table_name='training_rows'
    """).fetchone()[0]
    if source_exists:
        from .training import install_training_exclusions
        install_training_exclusions(con)
    else:
        con.execute("""CREATE OR REPLACE VIEW business.training_input_exclusions AS
            SELECT NULL::BIGINT AS source_input_order, NULL::VARCHAR AS fact_id,
              NULL::VARCHAR AS metric, NULL::VARCHAR AS business_line, NULL::DATE AS event_date,
              NULL::VARCHAR AS work_order_id, NULL::BIGINT AS source_row_number,
              NULL::VARCHAR AS team_id, NULL::VARCHAR AS business_group,
              NULL::VARCHAR AS acquisition_mode, NULL::VARCHAR AS exclude_reason
            WHERE FALSE""")
    # The SQL release contains the imported raw landing tables. Their input
    # query filters invalid dates, acquisition modes and duplicate order IDs.
    landing = con.execute("""
        SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='landing'
        AND table_name IN ('br_work_orders__sheet_1f0596db9f25','br_cash__sheet_39b8dee2e4b3')
    """).fetchone()[0]
    if landing == 2:
        con.execute("""CREATE OR REPLACE VIEW business.training_landing_exclusions AS
          WITH orders AS (
            SELECT source_row_number, NULLIF(TRIM(ID),'') AS work_order_id,
              TRIM(主被动) AS acquisition_mode,
              CASE WHEN TRY_CAST(分配时间 AS DOUBLE) BETWEEN 0 AND 100000
                THEN DATE '1899-12-30' + CAST(TRY_CAST(分配时间 AS DOUBLE) AS INTEGER) END AS event_date,
              row_number() OVER (PARTITION BY NULLIF(TRIM(ID),'') ORDER BY source_row_number) AS rn
            FROM landing.br_work_orders__sheet_1f0596db9f25
          ), cash AS (
            SELECT source_row_number, NULLIF(TRIM(工单ID),'') AS work_order_id,
              TRIM(渠道属性) AS acquisition_mode,
              CASE WHEN TRY_CAST(业务日期 AS DOUBLE) BETWEEN 0 AND 100000
                THEN DATE '1899-12-30' + CAST(TRY_CAST(业务日期 AS DOUBLE) AS INTEGER) END AS event_date
            FROM landing.br_cash__sheet_39b8dee2e4b3
          )
          SELECT source_row_number, 'training:order:' || work_order_id AS fact_id,
            'orders'::VARCHAR AS metric, 'training'::VARCHAR AS business_line,
            event_date, work_order_id, acquisition_mode,
            CASE WHEN work_order_id IS NULL THEN 'missing_order_id'
                 WHEN rn>1 THEN 'deduplicated_order_id'
                 WHEN acquisition_mode IS NULL OR acquisition_mode NOT IN ('主动','被动') THEN 'excluded_acquisition_mode'
                 ELSE 'missing_date' END AS exclude_reason
          FROM orders WHERE work_order_id IS NULL OR rn>1 OR event_date IS NULL
                            OR acquisition_mode IS NULL OR acquisition_mode NOT IN ('主动','被动')
          UNION ALL
          SELECT source_row_number, 'training:cash:' || source_row_number::VARCHAR,
            'cash', 'training', event_date, work_order_id, acquisition_mode,
            CASE WHEN acquisition_mode IS NULL OR acquisition_mode NOT IN ('主动','被动')
                 THEN 'excluded_acquisition_mode' ELSE 'missing_date' END
          FROM cash WHERE event_date IS NULL OR acquisition_mode IS NULL OR acquisition_mode NOT IN ('主动','被动')
        """)
    else:
        con.execute("""CREATE OR REPLACE VIEW business.training_landing_exclusions AS
          SELECT source_row_number, fact_id, metric, business_line, event_date,
            work_order_id, acquisition_mode, exclude_reason
          FROM business.training_input_exclusions WHERE FALSE""")
    con.execute((Path(__file__).parent/'sql/metrics.sql').read_text())

    # Production enrichment retains signature rows omitted from business.abroad_facts.
    # Small consumer fixtures can install metrics without the source pipeline.
    enriched = con.execute("""SELECT count(*) FROM information_schema.views
        WHERE table_schema='business' AND table_name='_abroad_enriched'""").fetchone()[0]
    if enriched:
        con.execute("""CREATE OR REPLACE VIEW core.abroad_excluded_source AS
            SELECT 'abroad-source:' || fact_id AS fact_id, event_date,
                   final_segment AS segment_id, business_line AS customer_domain,
                   gross_signing_amount AS source_amount, positive_signature,
                   origin_row_number AS source_row_number, origin_sha256 AS source_sha256,
                   origin_sheet AS source_sheet, origin_filename AS source_filename,
                   FALSE AS included,
                   CASE WHEN NOT coalesce(positive_signature, false) THEN 'signature_not_positive'
                        ELSE 'nonpositive_signing_amount' END AS exclude_reason
            FROM business._abroad_enriched WHERE NOT is_resource AND fact_value IS NULL""")
