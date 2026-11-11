"""服务器批次门禁：页面固定版本，跨换版请求拒绝并自动重载。"""
import json
from flask import jsonify,request
from flask_login import current_user
from flask_jwt_extended import verify_jwt_in_request,get_jwt_identity
from dashboard_product.shadow_bi.p3.extension import install as install_native
from dashboard_product.shadow_bi.p3.catalog import LIBRARY

def release():return LIBRARY.resolve().parent.name

def install_metadata_prefetch():
    """复用原生序列化/鉴权，批量装载关系，避免88数据集逐一查列/指标/所有者。"""
    from functools import wraps
    from sqlalchemy.orm import selectinload
    from superset import db
    from superset.models.dashboard import Dashboard
    from superset.connectors.sqla.models import SqlaTable
    original=Dashboard.datasets_trimmed_for_slices
    if getattr(original,'_shadow_prefetch',False):return
    @wraps(original)
    def prefetched(dashboard):
        if dashboard.slug=='shadow-bi-native':
            ids=[chart.datasource_id for chart in dashboard.slices]
            db.session.query(SqlaTable).filter(SqlaTable.id.in_(ids)).options(
                selectinload(SqlaTable.columns),selectinload(SqlaTable.metrics),
                selectinload(SqlaTable.owners),selectinload(SqlaTable.database)).all()
        return original(dashboard)
    prefetched._shadow_prefetch=True
    Dashboard.datasets_trimmed_for_slices=prefetched

def install(app):
    install_metadata_prefetch()
    install_native(app)
    # 自定义受保护资源沿用实际FAB登录端点，避免匿名跳转到不存在的login。
    app.login_manager.login_view='AuthDBView.login'
    @app.before_request
    def check_page_release():
        if request.path.rstrip('/')=='/api/v1/chart/data':
            pinned=request.headers.get('X-Shadow-BI-Release')
            if pinned and pinned!=release():return jsonify(message='数据批次已更新，正在刷新看板',release=release()),409
    @app.after_request
    def pin_page_release(response):
        if request.path.startswith('/superset/dashboard/') and response.mimetype=='text/html':
            # 页面内捕获固定版本，其他标签页刷新不会改变本页的请求版本。
            js=r'''<script>(function(){const v=__RELEASE__;const api=u=>{try{return new URL(u,location.href).pathname.replace(/\/$/,'')==='/api/v1/chart/data'}catch(e){return false}};const f=window.fetch;window.fetch=function(u,o){if(api(typeof u==='string'?u:u.url)){o=o||{};o.headers=new Headers(o.headers||(u.headers));o.headers.set('X-Shadow-BI-Release',v)}return f.call(this,u,o).then(r=>{if(r.status===409&&api(r.url)){location.reload()}return r})};const p=XMLHttpRequest.prototype,open=p.open,send=p.send;p.open=function(m,u){this._shadowApi=api(u);return open.apply(this,arguments)};p.send=function(){if(this._shadowApi){this.setRequestHeader('X-Shadow-BI-Release',v);this.addEventListener('load',()=>{if(this.status===409)location.reload()})}return send.apply(this,arguments)}})();</script>'''.replace('__RELEASE__',json.dumps(release()))
            response.set_data(response.get_data(as_text=True).replace('</head>',js+'</head>'))
            response.headers['Cache-Control']='no-store'
        return response
    @app.route('/p4/version')
    def version():
        verify_jwt_in_request(optional=True)
        if not current_user.is_authenticated and get_jwt_identity() is None:return jsonify(message="登录后查看批次"),401
        from superset import db
        from superset.models.core import Database
        database=db.session.query(Database).filter_by(database_name='市场经营 · 2026-10-22独立批次').one()
        if (LIBRARY/'candidate.json').is_file():
            from dashboard_product.shadow_bi.p4.sql_release import version as sql_version
            return jsonify(sql_version(LIBRARY,database))
        with database.get_sqla_engine() as engine:
            with engine.connect() as con:batch=con.exec_driver_sql('SELECT batch_id FROM queries.batch').scalar()
        manifest=json.loads((LIBRARY/'library_manifest.json').read_text())
        return jsonify(batch_id=batch,manifest_batch_id=manifest['batch_id'],release=release(),coverage=manifest['coverage'],matched=batch==manifest['batch_id'])
