"""P1 only: turn sealed JSON outputs into a disposable BI projection.
Never opens a customer Snapshot, never changes business definitions.
"""
from pathlib import Path
import json,hashlib
import duckdb
ROOT=Path(__file__).resolve().parents[2]
A=ROOT/'.local/audits/shadow-bi-p1-20261022'
P0=ROOT/'.local/audits/shadow-bi-p0-20261022/workspace/Output/DashboardManagement/run_shadow_p0_20261022'

def build():
    s=json.loads((P0/'shared_result.json').read_text()); d=json.loads((P0/'details.json').read_text())
    tables={}
    tables['p1_facts']=[{'事实ID':x['fact_id'],'指标':x['metric'],'业务线':x['business_line'],'日期':x['event_date'],'金额或数量':x['value'],'学员ID':x['student_id'],'学校':x['school_name'] or None,'年级':x['grade_name'] or None,'团队':x['team_id'],'业务组':x['business_group'],'状态':x['order_status'],'计入':x['counts_toward_completion']} for x in d['records']]
    tables['p1_activities']=[{'活动':x['name'],'工单':x['orders'],'语培工单':x['training_orders'],'留学工单':x['abroad_orders'],'现金':x['cash'],'人数':x['heads'],'状态':x['cash_status']} for x in s['activities']]
    targets=[]; top=[]; personal=[]
    for p in s['periods']:
        t=next(t for t in p['teams'] if t['id']=='total')
        top.append({'期间':p['id'],'日期':p['through_date'],'语培工单':t['lines']['training']['orders']['actual'],'语培现金':t['lines']['training']['cash']['actual']})
        for team,v in t['team_scope_views'].items():
            for g in v['business_groups']:
                share=g.get('passive_cash_share',{})
                targets.append({'期间':p['id'],'团队':team,'业务组':g['name'],'工单':g['orders']['actual'],'现金':g['cash']['actual'],'目标':g['cash'].get('target'),'分子':share.get('numerator'),'固定分母':share.get('denominator'),'占比':share.get('ratio')})
        if p['kind']=='month':
            for mode,v in [('performance',t),('calendar',t['person_calendar'])]:
                for person in v['people']:
                    for status,values in person['order_status_views'].items():
                        personal.append({'个人月份':p['id'],'月模式':mode,'状态组合':status,'人员':person['name'],'工单':values.get('training_actual'),'现金':person['cash_actual']['actual'],'人数':person['heads_actual']['actual'],'目标':values.get('training_target'),'窗口开始':v['person_start'],'窗口结束':v['person_through']})
    tables['p1_top']=top;tables['p1_targets']=targets;tables['p1_personal']=personal
    radar=[]
    for person in s['capacity']['radar']['people']:
        if person['name']!='刘彬':continue
        for axis in person['radar']['axes']:
            for series,field in [('本人','value'),('同组均值','mean')]:
                v=axis[field]; scale=axis['scale']
                radar.append({'人员':person['name'],'维度':axis['label'],'系列':series,'原值':v,'比例':v/scale if v is not None and scale else None,'上限':scale,'年度':'FY27','截止日期':s['capacity']['radar']['through_date']})
    tables['p1_radar']=radar
    dbfile=A/'runtime/projection.duckdb'
    if dbfile.exists():raise RuntimeError('Refusing to overwrite existing P1 projection')
    con=duckdb.connect(str(dbfile));receipt={}
    for name,rows in tables.items():
        fp=A/f'{name}.json';fp.write_text(json.dumps(rows,ensure_ascii=False))
        con.execute(f'CREATE TABLE {name} AS SELECT * FROM read_json_auto(?)',[str(fp)])
        receipt[name]={'rows':con.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0],'projection_sha256':hashlib.sha256(fp.read_bytes()).hexdigest()}
    con.execute('ALTER TABLE p1_facts ALTER COLUMN "日期" TYPE DATE')
    con.execute('ALTER TABLE p1_facts ALTER COLUMN "金额或数量" TYPE DECIMAL(20,6)')
    con.execute('ALTER TABLE p1_activities ALTER COLUMN "现金" TYPE DECIMAL(20,2)')
    con.close()
    receipt['sources']={n:hashlib.sha256((P0/n).read_bytes()).hexdigest() for n in ['shared_result.json','details.json']}
    (A/'evidence/projection.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
    print(json.dumps(receipt,ensure_ascii=False))
if __name__=='__main__':build()
