"""Real P3 Superset API exercise. Saves requests, generated SQL and actual results."""
import json,time,requests,os
from datetime import datetime,UTC
from dashboard_product.shadow_bi.p3.catalog import AUDIT,VIEWS

class Client:
 def __init__(self):
  self.evidence=AUDIT/'evidence'/('api-'+datetime.now(UTC).strftime('%Y%m%dT%H%M%S.%fZ'));self.evidence.mkdir()
  self.b=json.loads((AUDIT/'evidence/bootstrap.json').read_text());self.s=requests.Session();self.base=os.environ.get('SHADOW_BI_BASE_URL','http://127.0.0.1:18089');self.results=[]
  c=json.loads((AUDIT/'runtime/credentials.json').read_text());r=self.s.post(self.base+'/api/v1/security/login',json={'username':c['username'],'password':c['password'],'provider':'db','refresh':True});r.raise_for_status();self.s.headers['Authorization']='Bearer '+r.json()['access_token'];self.s.headers['X-CSRFToken']=self.s.get(self.base+'/api/v1/security/csrf_token/').json()['result']
 def query(self,key,columns=None,filters=None,limit=30,offset=0,metrics=None,order=None,name=None,**extra):
  spec=next(v for v in VIEWS if v.key==key)
  if columns is None:columns=spec.more.get('groupby',[]) if spec.more and spec.more.get('query_mode')=='aggregate' else spec.columns
  if metrics is None:metrics=(spec.more or {}).get('metrics',[])
  if filters is None:filters=[{'col':k,'op':'IN','val':v if isinstance(v,list) else [v]} for k,v in spec.filters.items()]
  query={'columns':columns,'metrics':metrics,'filters':filters,'orderby':order or [],'row_limit':limit,'row_offset':offset,'time_range':'No filter',**extra}
  payload={'datasource':{'id':self.b['datasets'][key],'type':'table'},'queries':[query],'force':True,'result_format':'json','result_type':'full'}
  start=time.monotonic();r=self.s.post(self.base+'/api/v1/chart/data',json=payload,timeout=120);j=r.json();filename=f'{len(self.results):03}-'+(name or key)+'.json';(self.evidence/filename).write_text(json.dumps({'status':r.status_code,'request':payload,'response':j},ensure_ascii=False,indent=2));row={'key':key,'file':filename,'seconds':round(time.monotonic()-start,3),'status':r.status_code};self.results.append(row)
  r.raise_for_status();data=j['result'][0]
  if data.get('error'):raise RuntimeError(data['error'])
  row['rows']=data['rowcount'];return data
 def save(self,checks):
  (self.evidence/'summary.json').write_text(json.dumps({'requests':self.results,'checks':checks},ensure_ascii=False,indent=2));print(self.evidence,flush=True)

def f(k,v,op='IN'):return {'col':k,'op':op,'val':v if isinstance(v,list) else [v]}
def main():
 c=Client();checks=[]
 for v in VIEWS:
  try:
   d=c.query(v.key);checks.append({'key':v.key,'status':'passed','rows':d['rowcount']});print(v.key,'passed',d['rowcount'],flush=True)
  except Exception as e:checks.append({'key':v.key,'status':'failed','error':str(e)});print(v.key,str(e),flush=True)
 c.save(checks)
 if any(x['status']=='failed' for x in checks):raise SystemExit(1)
if __name__=='__main__':main()
