"""真实HTTPS接口的批次、关键数值与阅读权限验证。"""
import json,os,time
from pathlib import Path
import requests
from dashboard_product.shadow_bi.p3.catalog import AUDIT

BASE=os.environ.get('SHADOW_BI_BASE_URL','https://dashboard.apinova.cn')

def session(credential,base=BASE):
    c=json.loads(credential.read_text());s=requests.Session();s.trust_env=False
    r=s.post(base+'/api/v1/security/login',json={'username':c['username'],'password':c['password'],'provider':'db','refresh':True},timeout=30);r.raise_for_status()
    s.headers['Authorization']='Bearer '+r.json()['access_token'];s.headers['Referer']=base+'/'
    r=s.get(base+'/api/v1/security/csrf_token/',timeout=30);r.raise_for_status();s.headers['X-CSRFToken']=r.json()['result'];return s

def payload(dataset,columns,filters=None):
    return {'datasource':{'id':dataset,'type':'table'},'queries':[{'columns':columns,'metrics':[],'filters':filters or [],'orderby':[],'row_limit':50,'time_range':'No filter'}],'force':True,'result_format':'json','result_type':'full'}

def main():
    evidence=AUDIT/'evidence/server-verification';evidence.mkdir(exist_ok=True)
    b=json.loads((AUDIT/'evidence/bootstrap.json').read_text());checks=[]
    admin=session(AUDIT/'runtime/credentials.json')
    expected={'被动':[(8639,9465),(17858997.4,20735205.1),(1236,1483)],'主动':[(3291,3349),(18972857.4,23233362),(1117,1364)],'全部':[(11930,12814),(36831854.8,43968567.1),(2351,2846)]}
    actuals={}
    for scope,values in expected.items():
        filters=[{'col':k,'op':'IN','val':[v]} for k,v in {'期间':'FY27','管理单元':'市场总计','业务线':'语培','语培统计范围':scope}.items()]
        r=admin.post(BASE+'/api/v1/chart/data',json=payload(b['datasets']['overview_lines'],['指标','当期','同期'],filters),timeout=120);r.raise_for_status();rows=r.json()['result'][0]['data'];actuals[scope]=rows
        mapping={x['指标']:x for x in rows}
        for metric,(a,p) in zip(['工单','现金（元）','人头'],values):
            assert abs(mapping[metric]['当期']-a)<.005 and abs(mapping[metric]['同期']-p)<.005,(scope,metric,mapping[metric])
        checks.append({'key':'server-baseline-'+scope,'status':'passed'})
    reader=session(AUDIT/'runtime/reader-test.json')
    for path in ['/api/v1/database/','/api/v1/security/roles/']:
        r=reader.get(BASE+path,timeout=30)
        assert r.status_code in (200,401,403),(path,r.status_code)
        if r.status_code==200:
            # 必要元数据可读并不等于可执行SQL；核查没有管理员秘密泄露。
            secrets=json.loads((AUDIT/'runtime/credentials.json').read_text())
            assert secrets['password'] not in r.text and secrets['secret_key'] not in r.text
            if path=='/api/v1/database/':
                for database in r.json().get('result',[]):
                    assert not database.get('expose_in_sqllab') and not database.get('allow_dml')
            (evidence/('reader-'+path.split('/')[-2]+'.json')).write_text(json.dumps(r.json(),ensure_ascii=False,indent=2))
        checks.append({'key':path,'status':r.status_code,'meaning':'metadata only; execution tested separately'})
    r=reader.post(BASE+'/api/v1/sqllab/execute/',json={'database_id':reader.get(BASE+'/api/v1/database/',timeout=30).json()['result'][0]['id'],'sql':'SELECT 42','runAsync':False,'schema':'queries','queryLimit':1},timeout=30);assert r.status_code in (401,403),r.status_code;checks.append({'key':'reader-no-sql-lab','status':r.status_code})
    r=reader.post(BASE+'/api/v1/chart/data',json=payload(b['datasets']['facts'],['工单']),timeout=30);assert r.status_code in (401,403),r.status_code;checks.append({'key':'reader-no-raw-facts','status':r.status_code})
    native=json.loads((AUDIT.parent/'shadow-bi-p35-20261023/native-bootstrap.json').read_text())
    r=reader.post(BASE+'/api/v1/chart/data',json=payload(b['datasets']['native_overview_training'],['指标','本期完成','上年同期','同比变化'],[{'col':'期间','op':'IN','val':['FY27']},{'col':'管理单元','op':'IN','val':['total']},{'col':'语培统计范围','op':'IN','val':['被动']}]),timeout=120);r.raise_for_status();checks.append({'key':'reader-native-chart','status':'passed'})
    for path in ['/api/v1/database/'+str(reader.get(BASE+'/api/v1/database/',timeout=30).json()['result'][0]['id']),'/api/v1/dashboard/'+str(native['dashboard_id'])]:
        r=reader.put(BASE+path,json={},timeout=30);assert r.status_code in (401,403),(path,r.status_code);checks.append({'key':'reader-no-edit-'+path,'status':r.status_code})
    anonymous=requests.Session();anonymous.trust_env=False
    r=anonymous.post(BASE+'/api/v1/chart/data',json=payload(b['datasets']['native_overview_training'],['指标']),timeout=30);assert r.status_code in (401,403),r.status_code;checks.append({'key':'anonymous-no-data','status':r.status_code})
    report={'created_at':time.time(),'base':BASE,'checks':checks,'actuals':actuals}
    (evidence/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({'checks':len(checks),'status':'passed'}))
if __name__=='__main__':main()
