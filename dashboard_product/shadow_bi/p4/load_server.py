"""三位阅读测试客户端持续15分钟；不创建真实灰度用户或日更任务。"""
import concurrent.futures,json,os,statistics,time,subprocess
from pathlib import Path
from dashboard_product.shadow_bi.p4.verify_server import session,BASE,payload
from dashboard_product.shadow_bi.p3.catalog import AUDIT
from dashboard_product.shadow_bi.p35.native_catalog import native_views,numeric_sort_bindings

def main():
    before={n:(Path('/sys/fs/cgroup/system.slice/shadow-bi.service')/n).read_text().strip() for n in ['memory.events','memory.current']}
    restart_before=subprocess.check_output(['systemctl','show','shadow-bi','-p','NRestarts','--value'],text=True).strip()
    duration=int(os.environ.get('P4_LOAD_SECONDS','900'));start=time.monotonic()
    progress=AUDIT/'evidence/load-progress.jsonl';progress.write_text('')
    b=json.loads((AUDIT/'evidence/bootstrap.json').read_text());specs={v.key:v for v in native_views()}
    keys=['native_overview_training','native_online_platform_training','native_overview_schools_training','native_capacity_month']
    def chart_request(key):
        v=specs[key];cols=v.columns
        filters=[{'col':k,'op':'IN','val':val if isinstance(val,list) else [val]} for k,val in v.filters.items()]
        order=[json.loads(x) for x in (v.more or {}).get('order_by_cols',[])]
        bindings=numeric_sort_bindings(v)
        selected=list(dict.fromkeys(cols+[bindings.get(x[0],x[0]) for x in order]))
        p=payload(b['datasets'][key],selected,filters)
        p['queries'][0]['orderby']=order
        return p,cols
    # 用真实图表配置校验请求形状；错误请求不进入容量计时。
    probe=session(AUDIT/'runtime/reader-test.json')
    for key in keys:
        p,cols=chart_request(key);r=probe.post(BASE+'/api/v1/chart/data',json=p,timeout=120)
        if r.status_code!=200:raise AssertionError((key,r.status_code,r.text[:1000]))
        d=r.json()['result'][0];assert not d.get('error') and d.get('data') and all(c in d['data'][0] for c in cols),(key,d)
    start=time.monotonic()
    def actor(index):
        s=session(AUDIT/'runtime/reader-test.json');records=[];auth_time=time.monotonic();renewals=0
        while time.monotonic()-start<duration:
            if time.monotonic()-auth_time>=600:
                s=session(AUDIT/'runtime/reader-test.json');auth_time=time.monotonic();renewals+=1
            key=keys[(len(records)+index)%len(keys)];p,cols=chart_request(key)
            p['force']=len(records)<4 or len(records)%4==0
            t=time.monotonic()
            try:
                r=s.post(BASE+'/api/v1/chart/data',json=p,timeout=120);result={'actor':index,'key':key,'seconds':time.monotonic()-t,'status':r.status_code,'force':p['force'],'phase':'initial' if len(records)<4 else 'steady'}
                if r.status_code!=200:result['error']=r.text[:300]
                else:
                    data=r.json().get('result',[])
                    valid=bool(data) and all(not x.get('error') and x.get('status') not in ('failed','error') and x.get('data') for x in data)
                    if valid:
                        valid=all(all(col in row for col in cols) for row in data[0]['data'])
                    if not valid:result['status']=0;result['error']='HTTP200但业务结果失败、为空或缺字段'
            except Exception as e:result={'actor':index,'key':key,'seconds':time.monotonic()-t,'status':0,'error':str(e)}
            with progress.open('a') as f:f.write(json.dumps(result,ensure_ascii=False)+'\n')
            records.append(result);time.sleep(3)
        return {'records':records,'authentication_renewals':renewals}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        actors=list(pool.map(actor,range(3)));records=sum([a['records'] for a in actors],[])
    timings=sorted(r['seconds'] for r in records);p95=timings[int(.95*(len(timings)-1))]
    by_view={}
    for key in keys:
        rows=[r for r in records if r['key']==key];values=sorted(r['seconds'] for r in rows)
        by_view[key]={'requests':len(rows),'forced_requests':sum(r.get('force',False) for r in rows),'failures':sum(r['status']!=200 for r in rows),'p95_seconds':values[int(.95*(len(values)-1))],'max_seconds':max(values)}
    memory={}
    for name in ['memory.peak','memory.current','memory.events']:
        f=Path('/sys/fs/cgroup/system.slice/shadow-bi.service')/name
        if f.exists():memory[name]=f.read_text().strip()
    events=lambda text:{k:int(v) for k,v in (line.split() for line in text.splitlines())}
    oom_delta=events(memory['memory.events']).get('oom_kill',0)-events(before['memory.events']).get('oom_kill',0)
    restart_after=subprocess.check_output(['systemctl','show','shadow-bi','-p','NRestarts','--value'],text=True).strip()
    report={'by_view':by_view,'request_shapes':{k:chart_request(k)[0] for k in keys},'authentication_renewals':sum(a['authentication_renewals'] for a in actors),'authentication_policy':'same reader login at start and every 600 seconds; server token lifetime unchanged','workloads':keys,'force_policy':'first four per actor forced; then every fourth request forced; 3-second think time','oom_kill_delta':oom_delta,'service_restart_delta':int(restart_after)-int(restart_before),'clients':3,'duration_seconds':time.monotonic()-start,'requests':len(records),'failures':sum(r['status']!=200 for r in records),'p95_seconds':p95,'max_seconds':max(timings),'restart_before':restart_before,'restart_after':subprocess.check_output(['systemctl','show','shadow-bi','-p','NRestarts','--value'],text=True).strip(),'memory_before':before,'memory':memory,'records':records}
    (AUDIT/'evidence/load-3-clients.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='records'},ensure_ascii=False))
    if report['failures'] or p95>3 or any(v['p95_seconds']>3 for v in by_view.values()) or report['oom_kill_delta']!=0 or report['service_restart_delta']!=0:raise SystemExit(1)
if __name__=='__main__':main()
