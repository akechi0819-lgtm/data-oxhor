"""人员贡献 SQL 安装器；Python 仅装入已确认历史原值。"""
from pathlib import Path
from .relations import load_rows, quote


def install_contribution(con, history=None):
    rows = []
    for item in (history or {}).get('rows', []):
        for scope, values in item['components'].items():
            for metric in ('orders', 'cash'):
                rows.append(dict(month=item['month'], name=item['name'], product_scope=scope,
                                 metric=metric, value=values.get(metric)))
    load_rows(con, 'config', 'contribution_history', rows, columns={
        'month':'VARCHAR', 'name':'VARCHAR', 'product_scope':'VARCHAR',
        'metric':'VARCHAR', 'value':'DECIMAL(38,6)'})
    con.execute((Path(__file__).parent/'sql/contribution.sql').read_text())
    for relation, message in (
        ('contribution_marker_conflicts', '同一留学资源的国际市场标记冲突'),
        ('contribution_identity_conflicts', '同一留学记录存在冲突'),
        ('contribution_invalid_events', '人员贡献日期、咨询类型或金额无效'),
    ):
        row = con.execute('SELECT * FROM business.'+relation+' LIMIT 1').fetchone()
        if row:
            raise ValueError(message + '：' + str(row[0]))
    # DuckDB repeatedly expands the name-matching macro across dependent views.
    # Materialize this explicit batch, then remove intermediate SQL relations.
    # The installer is the refresh entry point and is rerun for every batch.
    output_names = ['contribution_capacity', 'contribution_pending',
                    'contribution_marker_diagnostics', 'contribution_diagnostics',
                    'contribution_coverage', 'contribution_totals']
    columns = {name: [r[0] for r in con.execute('DESCRIBE business.'+name).fetchall()]
               for name in output_names}
    con.execute('CREATE OR REPLACE TABLE business.contribution_ledger_cache AS SELECT * FROM business.contributions')
    selects = ["SELECT '"+name+"' AS result_kind,* FROM business."+name for name in output_names]
    selects += ["SELECT 'contribution_diagnostics' AS result_kind,* FROM business."+name+" WHERE value>0"
                for name in ('contribution_owner_diagnostics','contribution_remaining_diagnostics')]
    con.execute('CREATE OR REPLACE TABLE business.contribution_result_cache AS SELECT * FROM ('+
                ' UNION ALL BY NAME '.join(selects)+') LIMIT 0')
    # Separate inserts bound the peak working set; a single UNION expands every
    # result query concurrently and exceeded the 512 MB local build limit.
    for select in selects:
        con.execute('INSERT INTO business.contribution_result_cache BY NAME '+select)
    con.execute('CREATE OR REPLACE VIEW business.contributions AS SELECT * FROM business.contribution_ledger_cache')
    for name in output_names:
        con.execute('CREATE OR REPLACE VIEW business.'+name+' AS SELECT '+
                    ','.join(quote(column) for column in columns[name])+
                    " FROM business.contribution_result_cache WHERE result_kind='"+name+"'")
    keep = set(output_names + ['contributions','contribution_ledger_cache','contribution_result_cache'])
    relations = con.execute("SELECT table_name,table_type FROM information_schema.tables WHERE table_schema='business' AND starts_with(table_name,'contribution_')").fetchall()
    for name, kind in relations:
        if name not in keep:
            con.execute(('DROP VIEW ' if kind=='VIEW' else 'DROP TABLE ')+'business.'+quote(name))
    return {'ledger' :'business.contributions', 'pending':'business.contribution_pending',
            'totals':'business.contribution_capacity', 'diagnostics':'business.contribution_diagnostics'}


def install_marker_audit(con, *, lineage):
    """Seal the shared SQL audit ledger in its recorded source traversal.

    The native table relies on DuckDB's physical-table late materialization
    (TOP_N, rowid semi-join, final sort). A logical union view changes equal-key
    pagination. Keep the array contract for pending consumers; materialize the
    two existing text fields without rebuilding any Python business output.
    """
    missing = con.execute("""SELECT m.key FROM business.contribution_marker_diagnostics m
        LEFT JOIN source.training_source_order o ON o.fact_id=m.key
        WHERE m.source='bi' AND o.fact_id IS NULL LIMIT 1""").fetchone()
    if missing:
        raise ValueError('source-order evidence does not cover marker identity: ' + missing[0])
    con.execute("""CREATE OR REPLACE TABLE business.contribution_marker_audit_cache AS
        SELECT m.*,CAST(to_json(m.affected_people) AS VARCHAR) AS affected_people_text,
            CASE WHEN metric='orders' THEN format('{:.0f}',value)
                 ELSE CAST(CAST(value AS DOUBLE) AS VARCHAR) END AS source_value
        FROM business.contribution_marker_diagnostics m
        LEFT JOIN source.training_source_order o ON o.fact_id=m.key
        ORDER BY CASE m.source WHEN 'bi' THEN 0 WHEN 'resources' THEN 1
                              WHEN 'contracts' THEN 2 WHEN 'languages' THEN 3 END,
                 CASE WHEN m.source='bi' THEN o.source_order
                      ELSE CAST(m.source_row_number AS BIGINT) END""")
    con.execute('CREATE OR REPLACE VIEW business.contribution_marker_diagnostics AS '
                'SELECT * FROM business.contribution_marker_audit_cache')
    con.execute("DELETE FROM business.contribution_result_cache WHERE result_kind='contribution_marker_diagnostics'")
    return {**lineage, 'relation': 'business.contribution_marker_audit_cache',
            'rows': con.execute('SELECT COUNT(*) FROM business.contribution_marker_audit_cache').fetchone()[0]}
