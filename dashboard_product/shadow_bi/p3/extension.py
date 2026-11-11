"""P3 navigation plus the single proven non-native activity input component."""
import json,time
from pathlib import Path
from flask import Response,request,redirect,send_from_directory,g
from flask_login import login_required
from dashboard_product.shadow_bi.p3.catalog import AUDIT,PAGES

def install(app):
 from dashboard_product.shadow_bi.p35.readable_exports import install_readable_exports
 install_readable_exports()
 @app.route('/p3/')
 def home():
  # 入口仅跳转；身份校验由目标Superset看板路由处理。
  return redirect('/superset/dashboard/shadow-bi-native/?standalone=1')
 @app.route('/p3/assets/<path:filename>')
 @login_required
 def theme_asset(filename):
  return send_from_directory(Path(__file__).resolve().parents[1]/'p35/assets',filename)
 @app.route('/p3/activity/')
 @login_required
 def activity():
  dataset=json.loads((AUDIT/'evidence/bootstrap.json').read_text())['datasets']['activities']
  html=Path(__file__).with_name('activity.html').read_text().replace('__ACTIVITY_DATASET_ID__',str(dataset))
  return Response(html,mimetype='text/html')
 @app.before_request
 def native_table_query():
  # Superset Table无每列自定义比较器；手工排序交还服务端，仅转换预注册展示字段。
  if request.path.rstrip('/')!='/api/v1/chart/data' or request.method!='POST':return
  payload=request.get_json(silent=True)
  if not isinstance(payload,dict):return
  manifest=AUDIT.parent/'shadow-bi-p35-20261023/native-bootstrap.json'
  if not manifest.exists():return
  datasource=payload.get('datasource')
  if not isinstance(datasource,dict):return
  config=json.loads(manifest.read_text())
  bindings=config.get('numeric_sort_bindings',{}).get(str(datasource.get('id')), {})
  school_paging=datasource.get('id') in config.get('school_tree_datasets',[])
  if not bindings and not school_paging:return
  rewrites=[]
  for query in payload.get('queries') or []:
   if not isinstance(query,dict):continue
   # 计数没有顺序；原生Table将隐藏排序列带入count会触发DuckDB聚合校验。
   if query.get('is_rowcount'):
    query['orderby']=[]
    continue
   for order in query.get('orderby') or []:
    if isinstance(order,list) and len(order)>1 and isinstance(order[0],str) and order[0] in bindings:
     original=order[0];order[0]=bindings[original];rewrites.append({'display':original,'numeric':order[0],'ascending':order[1]})
  g.numeric_sort_rewrites=rewrites
 @app.after_request
 def audit(response):
  if app.config.get('SHADOW_QUERY_AUDIT',True) and request.path.rstrip('/') in {'/api/v1/chart/data','/datasource/samples'} and request.method=='POST':
   record={'time_ns':time.time_ns(),'path':request.path,'status':response.status_code,'request':request.get_json(silent=True),'numeric_sort_rewrites':getattr(g,'numeric_sort_rewrites',[]),'response':response.get_json(silent=True)}
   with (AUDIT/'evidence/chart-requests.jsonl').open('a') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
  return response
