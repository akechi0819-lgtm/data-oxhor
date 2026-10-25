"""P4仅创建临时阅读测试账号；不猜测真实灰度用户身份。"""
import json,secrets,os
from superset.app import create_app
from dashboard_product.shadow_bi.p3.catalog import AUDIT
app=create_app()
with app.app_context():
    from superset import db,security_manager as sm
    from superset.models.dashboard import Dashboard
    from superset.connectors.sqla.models import SqlaTable
    native=json.loads((AUDIT.parent/'shadow-bi-p35-20261023/native-bootstrap.json').read_text())
    allowed={native['datasets'][key] for key in native['visible_chart_keys']}
    allowed.update(f['targets'][0]['datasetId'] for f in native['filters'])
    role=sm.add_role('ShadowReaderData')
    role.permissions=[]
    for ds in db.session.query(SqlaTable).filter(SqlaTable.id.in_(allowed)):
        perm=sm.find_permission_view_menu('datasource_access',ds.perm)
        if not perm:perm=sm.add_permission_view_menu('datasource_access',ds.perm)
        role.permissions.append(perm)
    # 不保留被原生页面替换的P3导航页。
    for dash in db.session.query(Dashboard).filter(Dashboard.slug!='shadow-bi-native').all():db.session.delete(dash)
    c={'username':'shadow_reader_test','password':secrets.token_urlsafe(24)}
    user=sm.find_user(username=c['username'])
    if not user:
        user=sm.add_user(username=c['username'],first_name='Shadow',last_name='ReaderTest',email='shadow-reader-test@localhost',role=sm.find_role('Gamma'),password=c['password'])
        user.roles=[sm.find_role('Gamma'),role]
        f=AUDIT/'runtime/reader-test.json';f.write_text(json.dumps(c));f.chmod(0o600)
    else:user.roles=[sm.find_role('Gamma'),role]
    db.session.commit()
    print(json.dumps({'reader':'shadow_reader_test','accessible_datasets':len(allowed),'raw_fact_access':native['datasets']['facts'] in allowed}))
