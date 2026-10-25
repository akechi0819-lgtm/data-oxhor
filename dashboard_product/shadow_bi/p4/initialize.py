"""只初始化独立P4元数据库；管理员凭据由服务器私有文件提供。"""
import json
from superset.app import create_app
from dashboard_product.shadow_bi.p3.catalog import AUDIT
app=create_app()
with app.app_context():
    from superset import security_manager
    c=json.loads((AUDIT/'runtime/credentials.json').read_text())
    if not security_manager.find_user(username=c['username']):
        security_manager.add_user(username=c['username'],first_name='Shadow',last_name='Operator',email='shadow-operator@localhost',role=security_manager.find_role('Admin'),password=c['password'])
