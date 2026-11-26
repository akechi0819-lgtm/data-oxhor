"""供正式发布读回使用的 Superset 会话与图表查询请求。"""
import json
import os

import requests

BASE=os.environ.get('SHADOW_BI_BASE_URL','https://dashboard.apinova.cn')

def session(credential,base=BASE):
    c=json.loads(credential.read_text());s=requests.Session();s.trust_env=False
    r=s.post(base+'/api/v1/security/login',json={'username':c['username'],'password':c['password'],'provider':'db','refresh':True},timeout=30);r.raise_for_status()
    s.headers['Authorization']='Bearer '+r.json()['access_token'];s.headers['Referer']=base+'/'
    r=s.get(base+'/api/v1/security/csrf_token/',timeout=30);r.raise_for_status();s.headers['X-CSRFToken']=r.json()['result'];return s

def payload(dataset,columns,filters=None):
    return {'datasource':{'id':dataset,'type':'table'},'queries':[{'columns':columns,'metrics':[],'filters':filters or [],'orderby':[],'row_limit':50,'time_range':'No filter'}],'force':True,'result_format':'json','result_type':'full'}
