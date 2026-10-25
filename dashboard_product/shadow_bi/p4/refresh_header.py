"""切换中的应用停止后，同步原生页眉覆盖日期；回滚同样调用。"""
import json
from superset.app import create_app
from dashboard_product.shadow_bi.p3.catalog import LIBRARY
from dashboard_product.shadow_bi.p35.bootstrap_native import coverage_note
app=create_app()
with app.app_context():
    from superset import db
    from superset.models.dashboard import Dashboard
    dashboard=db.session.query(Dashboard).filter_by(slug='shadow-bi-native').one()
    positions=json.loads(dashboard.position_json)
    keys=[key for key,value in positions.items() if isinstance(value,dict) and value.get('type')=='MARKDOWN' and '## 观近 · 市场经营' in value.get('meta',{}).get('code','')]
    if len(keys)!=1:raise ValueError('原生页眉身份不唯一')
    manifest=json.loads((LIBRARY/'library_manifest.json').read_text())
    positions[keys[0]]['meta']['code']=coverage_note(manifest['coverage'])
    dashboard.position_json=json.dumps(positions,ensure_ascii=False);db.session.commit()
    print(json.dumps({'batch_id':manifest['batch_id'],'data_through':manifest['coverage']['data_through'],'study_through':manifest['coverage']['study_abroad_source']['through_date']},ensure_ascii=False))
