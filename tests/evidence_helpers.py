import json
from pathlib import Path
from unittest.mock import patch
from data_platform.query.evidence import file_ref

def manifest(path, snapshot_id):
    (path.parent/'snapshot_manifest.json').write_text(json.dumps({'schema_version':'warehouse_snapshot.v2','snapshot_id':snapshot_id,'artifacts':[file_ref(path,path.parent,'application/octet-stream')]}))

def delivery(root, role='operator'):
    from tests.platform.test_query_service import warehouse
    from data_platform.query.service import execute_query
    from workspace_modeling.delivery import create_delivery
    config_path=root/'Work/workspace.json'
    config=json.loads(config_path.read_text())
    pointer=config.get('current_warehouse_path') or 'Work/Snapshot/warehouse.duckdb'
    config['current_warehouse_path']=pointer
    config_path.write_text(json.dumps(config))
    db=root/pointer
    if not db.exists():
        db.parent.mkdir(parents=True,exist_ok=True)
        warehouse(db,config['current_snapshot_id'])
    response=execute_query(warehouse=db,snapshot_id=config['current_snapshot_id'],sql='SELECT sum(amount) AS total FROM landing.values_table',run_id='run_delivery_test',output_root=root/'Output')
    report=root/'Output/report.html'
    report.write_text('<!doctype html><title>合成分析</title><p>合计：6</p>')
    import uuid
    with patch('workspace_modeling.casebook.router.guide', return_value={'next_step':'analyze'}):
        return create_delivery(root=root,output_dir=root/'Output'/('delivery_'+uuid.uuid4().hex),run_id='run_analysis_test',primary_role=role,query_receipts=[root/'Output'/response['run_id']/response['receipt']['path']],files=[{'path':report,'media_type':'text/html'}],producer={'name':'test_report','version':'1.0.0'})
