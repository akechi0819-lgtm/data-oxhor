"""Local-only SQL candidate assembly. No SSH, publication or notification."""
from __future__ import annotations

from datetime import date,timedelta
import json
import hashlib
import time
from pathlib import Path

from .foundation import bind_sql,bind_text
from .relations import quote,records


def _rule_binding(root):
    from dashboard_product.shadow_bi.library import code_files
    files=set(code_files())|{p for p in (root/'dashboard_product/shadow_bi/sql_warehouse').rglob('*') if p.suffix in ('.py','.sql')}
    files.update(root/p for p in ('data_platform/sql_candidate.py',
        'dashboard_product/shadow_bi/p3/catalog.py','dashboard_product/shadow_bi/p35/native_catalog.py',
        'dashboard_product/shadow_bi/p35/bootstrap_native.py',
        'dashboard_product/shadow_bi/p35/coverage_note.py',
        'dashboard_product/shadow_bi/p35/personnel_views.py','dashboard_product/shadow_bi/p35/breakdown_views.py',
        'dashboard_product/shadow_bi/p35/platform_views.py','dashboard_product/shadow_bi/p35/dimension_views.py'))
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def _input_view(con, name, body, columns, *, extra=None):
    actual={row[0] for row in con.execute('DESCRIBE ('+body+')').fetchall()}
    selected=[]
    for key,typ in columns.items():
        expression=(extra or {}).get(key,quote(key) if key in actual else 'NULL')
        selected.append(f'CAST({expression} AS {typ}) AS {quote(key)}')
    con.execute('DROP TABLE '+name)
    con.execute(f'CREATE VIEW {name} AS SELECT row_number() OVER () AS _input_order,'+
                ','.join(selected)+' FROM ('+body+') input')


def install_source_views(con, *, config_root, as_of_date):
    """SQL views retain five base tables as the only physical customer facts."""
    from .training import install_training,_TRAINING_COLUMNS,_ORDER_COLUMNS
    root=Path(config_root)
    sql=root/'dashboard_product/management/sql'
    cfg=lambda path:json.loads((root/path).read_text())
    people=cfg('workspace_modeling/operations/people.json')
    abroad_people=cfg('dashboard_product/config/offline_market_people.json')
    mapping=cfg('dashboard_product/online_team/config/confirmed_team_mapping.json')
    adviser_mapping={r['source_adviser']:r['labeled_team'] for r in mapping['mappings']}
    study=[k for k,v in adviser_mapping.items() if v=='留学']
    prep=[k for k,v in adviser_mapping.items() if v=='留学预备']
    coverage=records(con,(sql/'coverage.sql').read_text())[0]
    from dashboard_product.management.cutoff import calculation_cutoff
    through=calculation_cutoff(coverage,as_of_date)
    if not date(2026,6,1)<=through<=date(2027,5,31):raise ValueError('此看板仅支持FY27')
    start=min(coverage['orders_start'],coverage['cash_start'])
    month_start=through.replace(day=1)
    # Existing personal performance month changes on the 26th.
    performance_start=(month_start-timedelta(days=1)).replace(day=26) if through.day<26 else through.replace(day=26)
    attachment=min(month_start,performance_start).isoformat()
    end=(through+timedelta(days=1)).isoformat()
    train_sql=bind_sql(sql/'training_details.sql',[start,end,attachment,study,prep,['主动','被动']])
    orders_sql=bind_sql(sql/'orders.sql',[start,end,attachment])
    install_training(con,[],[],people,abroad_people,adviser_mapping,
                     cfg('dashboard_product/config/confirmed_cash_team_overrides.json'),school_rows=[])
    for alias,table in (
        ('source_training_orders','br_work_orders__sheet_1f0596db9f25'),
        ('source_training_cash','br_cash__sheet_39b8dee2e4b3'),
        ('source_study_resources','study_abroad_market__resources'),
        ('source_study_contracts','study_abroad_market__contracts'),
        ('source_language_cash','study_abroad_market__languages')):
        con.execute('CREATE VIEW business.'+alias+' AS SELECT * FROM landing.'+quote(table))
    _input_view(con,'source.training_rows',train_sql,_TRAINING_COLUMNS,
                extra={'_has_work_order_campaign_name':'true'})
    _input_view(con,'source.order_rows',orders_sql,_ORDER_COLUMNS)
    con.execute('CREATE VIEW source.order_events AS '+orders_sql)
    con.execute('DROP TABLE config.school_rows')
    con.execute('CREATE VIEW config.school_rows AS SELECT CAST(source_row_number AS VARCHAR) AS source_row_number,'
                'school_name,school_attribute FROM ('+(sql/'school_attributes.sql').read_text().strip().rstrip(';')+') source_school')
    con.execute('CREATE VIEW source.market_orders AS '+bind_sql(sql/'market_orders.sql',['2025-06-01',end]))
    con.execute('CREATE VIEW source.new_student_cash AS '+bind_sql(sql/'new_student_cash.sql',['2026-06-01',end]))
    con.execute('CREATE VIEW business.abroad_source_rows AS '+bind_sql(sql/'study_abroad/facts.sql',['2026-06-01',as_of_date]))
    return {'through':through.isoformat(),'observed_dates':coverage}


def install_abroad_inputs(con, *, workspace):
    from data_acquisition.jobs.work_order_cleaning import load_work_order_reference
    from dashboard_product.management.study_abroad_channels import load_decisions
    from dashboard_product.management.study_abroad_grade import _source_table,_build_query
    from .abroad import build_abroad_config,install_abroad
    ws=Path(workspace)
    bridge=json.loads((ws/'Work/Bridge/reference.json').read_text())
    config=build_abroad_config(bridge=bridge,
        reference=load_work_order_reference(ws/'Input/Reference/留学-FY26-资源表.xlsx'),decisions=load_decisions())
    pointer=json.loads((ws/'Work/workspace.json').read_text())
    manifest=json.loads((ws/pointer['current_warehouse_path']).with_name('snapshot_manifest.json').read_text())
    table,fields=_source_table(manifest)
    ids=[r[0] for r in con.execute("SELECT DISTINCT resource_id FROM business.abroad_source_rows WHERE regexp_full_match(resource_id,'[0-9]+')").fetchall()]
    sql,parameters=_build_query(table,fields,ids)
    con.execute('CREATE VIEW business.abroad_grade_source_rows AS '+bind_text(sql,parameters))
    return install_abroad(con,None,config)


def build_local(*,workspace,output_dir,batch_id,training_snapshot,abroad_snapshot,as_of_date,config_root,source_order_receipts,expense_baseline=None,advertising_manifest=None):
    """Create a new isolated candidate. This function cannot publish or deliver."""
    import duckdb
    from data_platform.query.evidence import file_ref,resolve_file
    from data_platform.sql_release_query import SEMANTIC_RELATIONS
    from .foundation import TABLES, import_foundation
    from .scorecard import install_scorecard
    from .cache import refresh_fact_cache,reorder_fact_cache
    from .source_order import install_training_source_order
    from .metrics import install_metrics
    from .personal import install_personal
    from .contribution import install_contribution,install_marker_audit
    from .radar import install_radar
    from .platforms import install_platforms
    from .expenses import install as install_expenses,refresh_from_manifest
    from .advertising import install_advertising
    from .dimensions import install_dimensions
    from .native_channel_cache import install_native_channel_source
    from .summaries import install_summaries
    from .notifications import compile_notifications
    from .header import coverage_note,update_date_label
    from dashboard_product.management.personnel_history import load_history,HISTORY_FILENAME
    workspace,output_dir,root=Path(workspace).resolve(),Path(output_dir).resolve(),Path(config_root).resolve()
    source_order_receipts=[Path(p).resolve() for p in source_order_receipts]
    if not source_order_receipts:raise ValueError('必须显式提供同批原始来源查询回执以保留审计遍历血缘')
    if output_dir.is_relative_to(workspace):raise ValueError('候选输出必须与输入工作区隔离')
    output_dir.mkdir(parents=True,exist_ok=False)
    fee_manifest=Path(advertising_manifest).resolve() if advertising_manifest is not None else workspace/'Input/AdvertisingCosts/sources.json'
    scorecard_path=workspace/'Input/Reference/留学板块-官方记分卡.json'
    inputs=[scorecard_path,workspace/'Work/workspace.json',workspace/'Work/StudyAbroad/current.json',
        workspace/'Work/Bridge/reference.json',
        workspace/'Input/Reference/留学-FY26-资源表.xlsx']
    history_path=workspace/'Input/Reference/人员产能'/HISTORY_FILENAME
    if history_path.is_file():inputs.append(history_path)
    fingerprints={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    company=json.loads((workspace/'Work/workspace.json').read_text())['company_id']
    baseline_manifest=None;baseline_database=None
    if expense_baseline is not None:
        baseline_dir=Path(expense_baseline).resolve()
        baseline_manifest=json.loads((baseline_dir/'candidate.json').read_text())
        if (baseline_manifest['schema_version']!='sql_warehouse_candidate.v1' or baseline_manifest['company_id']!=company):
            raise ValueError('费用基线必须为同工作区显式封口候选')
        baseline_database=resolve_file(baseline_dir,baseline_manifest['database'])
    rules=_rule_binding(root)
    timings={};start=time.perf_counter()
    database=output_dir/'warehouse.duckdb'
    with duckdb.connect(str(database)) as con:
        # 全量新老生现金扩大了归属规范化的中间结果；按用户确认使用 4GB 构建配额。
        con.execute('SET threads=2');con.execute("SET memory_limit='4GB'")
        t=time.perf_counter()
        source_queries=import_foundation(con,workspace=workspace,training_snapshot=training_snapshot,
            abroad_snapshot=abroad_snapshot,run_id=batch_id,output_root=output_dir/'source-evidence')
        con.execute('CREATE SCHEMA raw')
        for table in (*TABLES['training'], *TABLES['abroad']):
            con.execute(f'CREATE VIEW raw.{quote(table)} AS SELECT * FROM landing.{quote(table)}')
        timings['base_import_seconds']=time.perf_counter()-t
        t=time.perf_counter()
        meta=install_source_views(con,config_root=root,as_of_date=as_of_date)
        install_abroad_inputs(con,workspace=workspace)
        training_pointer=json.loads((workspace/'Work/workspace.json').read_text())
        source_lineage=install_training_source_order(con,receipts=source_order_receipts,
            snapshot_id=training_snapshot,warehouse=workspace/training_pointer['current_warehouse_path'])
        fingerprints.update({str(path):hashlib.sha256(Path(path).read_bytes()).hexdigest()
            for path in source_lineage['input_paths']})
        refresh_fact_cache(con)
        reorder_fact_cache(con)
        timings['sql_normalization_seconds']=time.perf_counter()-t
        t=time.perf_counter()
        abroad_pointer=json.loads((workspace/'Work/StudyAbroad/current.json').read_text())
        abroad_through=min(abroad_pointer['through_date'],(date.fromisoformat(as_of_date)-timedelta(days=1)).isoformat())
        install_metrics(con,through=meta['through'],abroad_start='2026-06-01',abroad_through=abroad_through,config_root=root)
        scorecard=install_scorecard(con, scorecard_path, warehouse_coverage_start='2026-06-01',
                                    warehouse_coverage_end=abroad_through)
        install_personal(con,config_root=root)
        history=load_history(workspace/'Input/Reference/人员产能'/HISTORY_FILENAME)
        install_contribution(con,history=history)
        marker_source_order=install_marker_audit(con,lineage=source_lineage)
        install_radar(con,config_root=root)
        install_platforms(con)
        install_dimensions(con)
        # Preserve the demonstrated single-thread source traversal; the
        # remaining business build keeps its existing two-thread worker.
        con.execute('SET threads=1')
        install_native_channel_source(con)
        con.execute('SET threads=2')
        install_summaries(con)
        timings['sql_metrics_seconds']=time.perf_counter()-t
        t=time.perf_counter()
        install_expenses(con)
        if baseline_database is not None:
            con.execute("ATTACH '"+str(baseline_database).replace("'","''")+"' AS expense_baseline (READ_ONLY)")
            for table in ('expense_rows','expense_sources'):
                con.execute(f'INSERT INTO expenses.{table} BY NAME SELECT * FROM expense_baseline.expenses.{table}')
            con.execute('DETACH expense_baseline')
        expenses=refresh_from_manifest(con,fee_manifest,batch_id+'_fees')
        install_advertising(con,config_root=root)
        display_dates=records(con,'SELECT * FROM business.update_dates')[0]
        display_label=update_date_label(display_dates)
        dashboard_coverage_note=coverage_note(display_dates)
        timings['expense_import_seconds']=time.perf_counter()-t
        t=time.perf_counter()
        notification_preview=compile_notifications(con,through=meta['through'],study_abroad_source={
            'snapshot_id':abroad_snapshot,'source_sha256':abroad_pointer['source_sha256'],
            'start_date':'2026-06-01','through_date':abroad_through,
            'no_yoy':True,'cross_system_customers':'not_aligned'})
        (output_dir/'notification-preview.json').write_text(json.dumps(notification_preview,ensure_ascii=False,indent=2,default=str))
        timings['notification_preview_seconds']=time.perf_counter()-t
        con.execute('CREATE TABLE meta.identity (batch_id VARCHAR)');con.execute('INSERT INTO meta.identity VALUES (?)',[batch_id])
        relations=records(con,"SELECT table_schema,table_name,table_type FROM information_schema.tables WHERE table_catalog <> 'temp' AND table_schema NOT IN ('information_schema','pg_catalog') ORDER BY 1,2")
        query_relations=[r['table_name'] for r in relations if r['table_schema']=='business' and not r['table_name'].startswith('_')]
        semantic_relations=sorted({r['table_schema']+'.'+r['table_name'] for r in relations} & SEMANTIC_RELATIONS)
        if set(semantic_relations) != SEMANTIC_RELATIONS:
            raise ValueError('封存仓语义关系缺失：'+','.join(sorted(SEMANTIC_RELATIONS-set(semantic_relations))))
        counts=records(con,'SELECT business_line,is_business_fact,is_personal_fact,count(*) AS rows FROM business.fact_cache GROUP BY ALL')
        con.execute('CHECKPOINT')
    if any(hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h for p,h in fingerprints.items()):
        raise ValueError('构建期间输入身份发生变化，候选未封口')
    timings['total_build_seconds']=time.perf_counter()-start
    if _rule_binding(root)!=rules:
        raise ValueError('构建期间SQL或规则发生变化，候选未封口')
    manifest={'schema_version':'sql_warehouse_candidate.v1','status':'built_unreconciled','published':False,'company_id':company,
        'batch_id':batch_id,'as_of_date':as_of_date,'through_date':meta['through'],
        'display_dates':display_dates,'display_label':display_label,
        'dashboard_coverage_note':dashboard_coverage_note,
        'snapshots':{'training':training_snapshot,'abroad':abroad_snapshot},
        'database':file_ref(database,output_dir,'application/vnd.duckdb'),
        'input_binding':fingerprints,'source_queries':source_queries,'relations':relations,
        'source_order_receipts':marker_source_order['source_order_receipts'],'marker_source_order':marker_source_order,
        'query_relations':query_relations,'schemas':sorted({r['table_schema'] for r in relations}),
        'query_macros':['dimension_query'], 'semantic_relations':semantic_relations, 'official_scorecard':scorecard,
        'fact_counts':counts,'expenses':expenses,'timings':timings,
        'expense_baseline':{'candidate':file_ref(baseline_dir/'candidate.json',baseline_dir,'application/json'),
            'database':baseline_manifest['database']} if baseline_manifest else None,
        'rules':rules,
        'notification_preview':file_ref(output_dir/'notification-preview.json',output_dir,'application/json'),
        'server_actions':False,'notification_delivery':False}
    (output_dir/'candidate.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2,default=str))
    return manifest
