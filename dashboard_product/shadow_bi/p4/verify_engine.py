"""检查BI实际数据库连接的只读/文件访问限制；不执行客户业务查询。"""
import json
from superset.app import create_app
from dashboard_product.shadow_bi.p3.catalog import AUDIT
app=create_app()
with app.app_context():
    from superset import db
    from superset.models.core import Database
    database=db.session.query(Database).filter_by(database_name='市场经营 · 2026-10-22独立批次').one()
    checks=[]
    for name,sql in [('external_file',"SELECT * FROM read_text('/etc/passwd')"),('readonly',"CREATE TABLE queries.p4_permission_probe(i INTEGER)")]:
        try:
            with database.get_sqla_engine() as engine:
                with engine.connect() as con:con.exec_driver_sql(sql)
        except Exception as e:
            error=str(e)
            assert ('disabled' in error.lower() or 'permission' in error.lower()) if name=='external_file' else ('read-only' in error.lower() or 'read only' in error.lower()),error
            checks.append({'key':name,'status':'denied','error':error[:500]})
        else:raise AssertionError('BI连接未阻止:'+name)
    (AUDIT/'evidence/engine-boundaries.json').write_text(json.dumps({'checks':checks},ensure_ascii=False,indent=2));print('实际BI连接两项边界均拒绝')
