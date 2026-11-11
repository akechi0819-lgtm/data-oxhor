"""必要的单份 SQL 事实缓存，避免每张图重复展开相同归属与姓名匹配。"""


def reorder_fact_cache(con):
    """Preserve the sealed producer traversal in the existing typed cache.

    The native school window consumes hash-group output from these facts.
    Reordering only the selected period loses the original scan blocks and
    changes equal-metric rows. Require lineage for every training fact;
    preserve the existing abroad traversal and all fact columns unchanged.
    """
    missing=con.execute('''SELECT 1 FROM business.fact_cache f
       LEFT JOIN source.training_source_order o ON o.fact_id=f.fact_id
       WHERE f.business_line='training' AND o.fact_id IS NULL LIMIT 1''').fetchone()
    if missing:
        raise ValueError('fact cache requires source-order evidence for every training fact')
    con.execute('''CREATE TEMP TABLE ordered_fact_stage AS
       SELECT f.* FROM business.fact_cache f
       LEFT JOIN source.training_source_order o ON o.fact_id=f.fact_id
       ORDER BY CASE WHEN f.business_line='training' THEN 0 ELSE 1 END,
                o.source_order,f.rowid''')
    con.execute('CREATE OR REPLACE TABLE business.fact_cache AS SELECT * FROM ordered_fact_stage')
    con.execute('DROP TABLE ordered_fact_stage')


def refresh_fact_cache(con):
    """Run after business updates only; expenses do not invoke this refresh.

    The first real all-period query exceeded the bounded 512MB worker memory
    with pure nested views. Store the shared normalization once, not 39 chart
    result tables. Each fact keeps independent business/personal eligibility.
    """
    for name in ('training_facts','training_personnel_facts','abroad_facts'):
        definition=con.execute("SELECT sql FROM duckdb_views() WHERE schema_name='business' AND view_name=?",[name]).fetchone()[0]
        if 'business.fact_cache' not in definition:
            body=definition.split(' AS ',1)[1].rstrip(';')
            con.execute('CREATE OR REPLACE VIEW business._source_'+name+' AS '+body)
    con.execute('''CREATE OR REPLACE TABLE business.fact_cache AS
       SELECT *,true AS is_business_fact,false AS is_personal_fact FROM business._source_training_facts''')
    con.execute('''CREATE TEMP TABLE personal_fact_stage AS SELECT * FROM business._source_training_personnel_facts''')
    con.execute('''UPDATE business.fact_cache c SET is_personal_fact=true
       FROM personal_fact_stage p WHERE c.fact_id=p.fact_id''')
    con.execute('''INSERT INTO business.fact_cache BY NAME
       SELECT *,false AS is_business_fact,true AS is_personal_fact FROM personal_fact_stage p
       WHERE NOT EXISTS (SELECT 1 FROM business.fact_cache c WHERE c.fact_id=p.fact_id)''')
    con.execute('DROP TABLE personal_fact_stage')
    # Abroad has additional provenance columns. Add their declared source types
    # before BY NAME insertion; this is schema union, not business-field guessing.
    present={r[0] for r in con.execute('DESCRIBE business.fact_cache').fetchall()}
    from .relations import quote
    for name,typ,*_ in con.execute('DESCRIBE business._source_abroad_facts').fetchall():
        if name not in present:
            con.execute('ALTER TABLE business.fact_cache ADD COLUMN '+quote(name)+' '+typ)
    con.execute('''INSERT INTO business.fact_cache BY NAME
       SELECT *,true AS is_business_fact,true AS is_personal_fact FROM business._source_abroad_facts''')
    con.execute('''CREATE OR REPLACE VIEW business.training_facts AS
       SELECT * EXCLUDE(is_business_fact,is_personal_fact) FROM business.fact_cache
       WHERE business_line='training' AND is_business_fact''')
    con.execute('''CREATE OR REPLACE VIEW business.training_personnel_facts AS
       SELECT * EXCLUDE(is_business_fact,is_personal_fact) FROM business.fact_cache
       WHERE business_line='training' AND is_personal_fact''')
    con.execute('''CREATE OR REPLACE VIEW business.abroad_facts AS
       SELECT * EXCLUDE(is_business_fact,is_personal_fact) FROM business.fact_cache WHERE business_line='abroad' ''')
