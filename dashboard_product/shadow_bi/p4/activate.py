"""本服务器显式批次切换：预检失败不动当前，重启清连接缓存，失败回滚。"""
import argparse,json,subprocess,time,sys
from pathlib import Path
from data_platform.business_library import load_library,execute_library_query,read_library_result

def verify_target(target):
    base=Path('/var/lib/shadow-bi')
    from dashboard_product.shadow_bi.p4.verify_server import session,payload
    BASE="http://127.0.0.1:18090"
    from dashboard_product.shadow_bi.p3.catalog import AUDIT
    client=session(AUDIT/'runtime/credentials.json',base=BASE)
    v=client.get(BASE+'/p4/version',timeout=30);v.raise_for_status();identity=v.json()
    if not identity['matched'] or identity['release']!=target.name:raise RuntimeError('应用实际批次不匹配')
    wanted=json.loads((target/'library/library_manifest.json').read_text())
    fields=["json_extract_string(view,'$.lines.training."+metric+"."+field+"')" for metric in ['orders','cash','heads'] for field in ['actual','prior']]
    expected_query=execute_library_query(library=target/'library',batch_id=wanted['batch_id'],sql="SELECT "+','.join(fields)+" FROM queries.scoped_team_periods WHERE period_id='FY27' AND team_id='total' AND acquisition_scope='被动'",run_id='run_p4_expected_'+str(time.time_ns()),output_root=base/'app/preflight')
    expected=read_library_result(expected_query,output_root=base/'app/preflight')['rows'][0]
    native=json.loads((AUDIT.parent/'shadow-bi-p35-20261023/native-bootstrap.json').read_text())
    meta=client.get(BASE+'/api/v1/dashboard/'+str(native['dashboard_id']),timeout=30);meta.raise_for_status()
    from dashboard_product.shadow_bi.p35.bootstrap_native import coverage_note
    notes=[x.get('meta',{}).get('code','') for x in json.loads(meta.json()['result']['position_json']).values() if isinstance(x,dict) and x.get('type')=='MARKDOWN']
    if coverage_note(wanted['coverage']) not in notes:raise RuntimeError('页眉覆盖日期与已连接批次不同')
    from dashboard_product.shadow_bi.p35.expense_coverage import expense_coverage_note
    if expense_coverage_note(target/'library',wanted['batch_id'],AUDIT) not in notes:raise RuntimeError('平台费用提示与已连接批次不同')
    b=json.loads((AUDIT/'evidence/bootstrap.json').read_text())
    filters=[{'col':k,'op':'IN','val':[v]} for k,v in {'期间':'FY27','管理单元':'市场总计','语培统计范围':'被动'}.items()]
    client.headers['X-Shadow-BI-Release']=target.name
    r=client.post(BASE+'/api/v1/chart/data',json=payload(b['datasets']['native_overview_training'],['指标','本期完成','上年同期'],filters),timeout=120);r.raise_for_status()
    rows=r.json()['result'][0]['data']
    mapping={row['指标']:row for row in rows}
    for index,label in enumerate(['工单','现金（元）','人头']):
        for offset,column in enumerate(['本期完成','上年同期']):
            raw=expected[index*2+offset];display=mapping[label][column]
            if raw is None:
                if display!='—':raise RuntimeError('缺失值呈现不匹配')
            elif abs(float(display.replace(',',''))-float(raw))>.005:raise RuntimeError('关键查询与目标批次不符:'+label+column)
    return {'identity':identity,'query_rows':len(rows),'header_matches':True,'expense_note_matches':True,'metrics_compared':6,'key_metrics':rows,'expected_values':expected}

def activate(candidate,fail_smoke=False):
    started=time.monotonic()
    base=Path('/var/lib/shadow-bi');candidate=candidate.resolve()
    if not candidate.is_relative_to(base/'releases'):raise ValueError('不在独立发布目录')
    m=json.loads((candidate/'library/library_manifest.json').read_text())
    execute_library_query(library=candidate/'library',batch_id=m['batch_id'],sql='SELECT batch_id FROM queries.batch',run_id='run_p4_preflight_'+str(time.time_ns()),output_root=base/'app/preflight')
    current=base/'current';old=current.resolve() if current.exists() else None
    maintenance=Path('/run/shadow-bi-maintenance');maintenance.touch(mode=0o644)
    subprocess.run(['systemctl','stop','shadow-bi'],check=True)
    def point(target):
        tmp=base/'next';tmp.unlink(missing_ok=True);tmp.symlink_to(target);tmp.replace(current)
    def header():
        subprocess.run(["runuser","-u","shadowbi","--preserve-environment","--",sys.executable,"-m","dashboard_product.shadow_bi.p4.refresh_header"],check=True)
    try:
        point(candidate)
        header()
        subprocess.run(['systemctl','start','shadow-bi'],check=True)
        for _ in range(60):
            result=subprocess.run(['curl','-fsS','http://127.0.0.1:18090/health'],capture_output=True)
            if result.returncode==0:break
            time.sleep(1)
        else:raise RuntimeError('新实例未就绪')
        if fail_smoke:raise RuntimeError("P4恢复演练：模拟发布后烟测失败")
        verified=verify_target(candidate)
        if old and old!=candidate:
            previous=base/'previous';previous.unlink(missing_ok=True);previous.symlink_to(old)
        maintenance.unlink(missing_ok=True)
        print(json.dumps({'activated':str(candidate),'previous':str(old),'batch_id':m['batch_id'],'app_verification':verified,'seconds':round(time.monotonic()-started,3)}))
    except Exception:
        subprocess.run(['systemctl','stop','shadow-bi'],check=True)
        if old:
            point(old);header();subprocess.run(['systemctl','start','shadow-bi'],check=True)
            for _ in range(60):
                if subprocess.run(['curl','-fsS','http://127.0.0.1:18090/health'],capture_output=True).returncode==0:break
                time.sleep(1)
            restored=verify_target(old)
            print(json.dumps({'rollback_verified':restored,'seconds':round(time.monotonic()-started,3)}),flush=True)
            maintenance.unlink(missing_ok=True)
        raise
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('candidate',type=Path);p.add_argument('--fail-smoke',action='store_true');p.add_argument('--verify-only',action='store_true');a=p.parse_args()
    if a.verify_only:print(json.dumps(verify_target(a.candidate.resolve()),ensure_ascii=False))
    else:activate(a.candidate,a.fail_smoke)
