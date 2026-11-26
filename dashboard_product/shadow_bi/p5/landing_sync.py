"""Exchange landing row changes, schema and query receipts with the fixed cloud builder."""
import hashlib
import json
from pathlib import Path

from data_platform.query.evidence import read_query_result, resolve_file
from data_platform.query.service import describe_warehouse, execute_query
from data_platform.sql_release_query import execute_query_bundle
from dashboard_product.shadow_bi.sql_warehouse.foundation import TABLES, quote


def read_cloud_rows(release,expected_release,expected_batch,output):
    """Read the five old tables on the warehouse host through the controlled service."""
    tables = {}
    for domain, source in (('training','training'),('study','abroad')):
        for table in TABLES[source]:
            result_dir = output/table
            result = execute_query_bundle(release_root=release,expected_release=expected_release,
                expected_batch_id=expected_batch,domain=domain,allowed_relations=set(TABLES[source]),
                sql=f'SELECT * FROM landing.{quote(table)} ORDER BY source_row_number',output_dir=result_dir)
            with (result_dir/'rows.jsonl').open() as stream:
                tables[table] = {'columns':result['columns'],'rows':[json.loads(line) for line in stream]}
    return tables


def local_changes(*, workspace, snapshots, day, batch_id, output, index, old_release, old_sha):
    from business_data_mcp.build_context import build_bundle
    from data_acquisition.transfer.sql_landing_delta import make_delta_from_index
    from dashboard_product.shadow_bi.p5.sql_daily import source_order_receipts
    from dashboard_product.shadow_bi.sql_warehouse.source_order import install_training_source_order
    import duckdb

    work = workspace/'Work'
    bi = json.loads((work/'workspace.json').read_text())
    abroad = json.loads((work/'StudyAbroad/current.json').read_text())
    if {'training':bi['current_snapshot_id'],'abroad':abroad['snapshot_id']}!=snapshots:
        raise ValueError('本机基础表在同步期间发生了变化')
    tables,descriptions,provenance,queries = {},{},{},[]
    controlled = output/'landing-evidence'
    for group, domain, warehouse in (('training','training',workspace/bi['current_warehouse_path']),
                                      ('abroad','study',workspace/abroad['warehouse'])):
        snapshot = snapshots[group]
        description = describe_warehouse(warehouse=warehouse,snapshot_id=snapshot)
        description['relations'] = [r for r in description['relations'] if r['schema']=='landing' and r['name'] in TABLES[group]]
        descriptions[domain] = description
        for table in TABLES[group]:
            relation = 'landing.'+table
            rows = []
            for offset in range(0,1_000_000,5000):
                name = hashlib.sha256(f'{batch_id}:{table}:{offset}'.encode()).hexdigest()[:30]
                reply = execute_query(warehouse=warehouse,snapshot_id=snapshot,
                    run_id='run_delta_'+name,sql=f'SELECT * FROM landing.{quote(table)} ORDER BY source_row_number LIMIT 5000 OFFSET {offset}',
                    parameters=[],output_root=controlled,max_rows=5000,max_result_bytes=50_000_000)
                data = read_query_result(reply,output_root=controlled)
                receipt = json.loads(resolve_file(controlled/reply['run_id'],reply['receipt']).read_text())
                ids=receipt['referenced_source_ids']
                if receipt['referenced_relations']!=[relation] or len(ids)!=1:
                    raise ValueError('基础表增量缺少已封存的来源身份')
                source = {'source_id':ids[0],'snapshot_id':snapshot,'domain':domain}
                if relation in provenance and provenance[relation]!=source:
                    raise ValueError('基础表增量来源身份在读取中改变')
                provenance[relation]=source
                queries.append({key:reply[key] for key in ('schema_version','status','run_id','snapshot_id','receipt','errors')})
                rows.extend(data['rows'])
                if len(data['rows'])<5000:
                    break
            else:
                raise ValueError('超过基础表增量读取上限')
            tables[table]={'columns':data['columns'],'rows':rows}
    patch=make_delta_from_index(index,tables,expected_release=old_release,expected_warehouse_sha256=old_sha)
    source=source_order_receipts(workspace=workspace,training_snapshot=snapshots['training'],as_of_date=day,
                                batch_id=batch_id,output_root=output/'source-order')
    with duckdb.connect() as scratch:
        lineage=install_training_source_order(scratch,receipts=source['source_order_receipts'],
                   snapshot_id=snapshots['training'],warehouse=workspace/bi['current_warehouse_path'])
        def rows_from(table):
            cursor=scratch.execute(f'SELECT * FROM {table} ORDER BY ALL')
            return {'columns':[col[0] for col in cursor.description],'rows':cursor.fetchall()}
        metadata={'snapshots':snapshots,'source_queries':queries,
                  'source_order_rows':rows_from('source.training_source_order'),
                  'source_order_evidence':rows_from('meta.training_source_order_evidence'),
                  'source_order_receipts':lineage['source_order_receipts'],
                  'abroad_through':abroad['through_date'],'abroad_source_sha256':abroad['source_sha256']}
    context=build_bundle(workspace=workspace)
    semantics={'Work/Bridge/reference.json':context['manifest']['source_sha256']['bridge']}
    landing_contract={'descriptions':descriptions,'provenance':provenance,'semantics':semantics,'business_context':context}
    return patch,metadata,landing_contract,source['coverage']
