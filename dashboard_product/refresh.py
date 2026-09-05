#!/usr/bin/env python3
import argparse,json,subprocess
from pathlib import Path
from datetime import datetime,timezone
from uuid import uuid4
ROOT=Path(__file__).parent
TEAMS=[('offline_market','线下市场'),('online_private','线上私域（虚拟人团队）'),('online_platform','线上平台'),('暂无法匹配','暂无法匹配')]
MONTHS=[f'2026-{m:02d}' for m in range(6,13)]+[f'2027-{m:02d}' for m in range(1,6)]
PRIOR_MONTHS=[f'2025-{m:02d}' for m in range(6,13)]+[f'2026-{m:02d}' for m in range(1,6)]

def date_to_perf_month(date_str):
    """将日期转换为绩效月（YYYY-MM格式）
    绩效月定义：每月26日到次月25日算作次月的绩效月
    例如：2026-05-26 到 2026-06-25 算作 2026-06 绩效月
    """
    from datetime import datetime
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(str(date_str)[:10])
        # 如果是26日或之后，算作下个月的绩效月
        if dt.day >= 26:
            # 加一个月
            if dt.month == 12:
                perf_year = dt.year + 1
                perf_month = 1
            else:
                perf_year = dt.year
                perf_month = dt.month + 1
            return f'{perf_year:04d}-{perf_month:02d}'
        else:
            # 1-25日算作当月绩效月
            return f'{dt.year:04d}-{dt.month:02d}'
    except:
        return None

def read(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def run(ws,rid,snap,out,a,b):
 c=read(ws/'Work/workspace.json'); z=subprocess.run(['python3','-m','interfaces.data_platform','run-saved-query','--warehouse',str(ws/c['current_warehouse_path']),'--snapshot-id',snap,'--run-id',rid,'--output-root',str(out),'--registry-root',str(ws/'Work/SavedQueries'),'--query-id','dashboard_actuals','--version','v6','--params-json',json.dumps([a,b]),'--max-rows','50000','--max-result-bytes','10000000'],cwd=ROOT.parent,capture_output=True,text=True); r=json.loads(z.stdout or '{}')
 if r.get('status')!='passed': raise ValueError(f"Query failed: {r.get('errors')} | stderr: {z.stderr}")
 # 如果 result 为 None，从 artifact 文件读取
 if not r.get('result') and r.get('artifact',{}).get('path'):
  artifact_path = out / rid / r['artifact']['path']  # artifact path 是相对于 out/rid/ 的
  artifact_data = read(artifact_path)
  r['result'] = artifact_data  # artifact 文件本身就是 {columns, rows} 结构
 if not r.get('result'): raise ValueError(f"Query returned no result: {r}")
 return r
def project(q,p,tg,people):
 act={}; per={}; ch={}; prior_act={}; per_monthly={}
 # 处理当前年度数据
 # 查询列顺序: event_date, team_id, business_group, first_channel, second_channel, campaign_name, metric, actual_value
 for row in q['result']['rows']:
  if len(row)<8: continue
  dt,team,group,first_ch,second_ch,campaign,metric,val = row[0],row[1],row[2],row[3],row[4],row[5],row[6],row[7]
  if not team or not group or not metric or not val: continue
  # 业务组按自然月聚合
  natural_month = str(dt)[:7]
  k=(natural_month,team,group,metric); val=float(val); act[k]=act.get(k,0)+val
  # 渠道分组：同时保存一级渠道和二级渠道数据
  if metric=='work_orders':
   ch['|'.join((natural_month,team,group,str(first_ch or '未归类')))]=ch.get('|'.join((natural_month,team,group,str(first_ch or '未归类'))),0)+val
   # 保存二级渠道数据（用于下钻）
   if second_ch:
    ch['|'.join((natural_month,team,group,str(first_ch or '未归类'),str(second_ch)))]=ch.get('|'.join((natural_month,team,group,str(first_ch or '未归类'),str(second_ch))),0)+val
  # 人员匹配：从 campaign_name 中提取人名
  if campaign and str(campaign) not in ['是', '否', 'None', '', 'NULL']:
   campaign_str = str(campaign)
   for t in people.get('teams',[]):
    if t['team_id']==team:
     for g in t.get('groups',[]):
      for person in g.get('members',[]):
       person_name = person.get('display_name')
       if person_name and person_name in campaign_str:
        per[(team,person_name,metric)]=per.get((team,person_name,metric),0)+val
        # 个人数据按绩效月聚合
        perf_month = date_to_perf_month(dt)
        if perf_month:
         per_monthly[(team,person_name,perf_month,metric)]=per_monthly.get((team,person_name,perf_month,metric),0)+val
 # 去年同期按自然月聚合。前端按所选季度切片，必须与当前年度使用相同月段。
 for row in p['result']['rows']:
  if len(row)<8: continue
  mo,team,group,first_ch,second_ch,campaign,metric,val = row[0],row[1],row[2],row[3],row[4],row[5],row[6],row[7]
  if not team or not group or not metric or not val: continue
  natural_month = str(mo)[:7]
  key = (natural_month, team, group, metric)
  prior_act[key] = prior_act.get(key, 0) + float(val)
 teams=[]
 for tid,label in TEAMS:
  gs=[]
  for item in tg['business_groups'].values():
   n=item['display_name']; qt={q:{'cash':v.get(tid,{}).get('passive_cash_target'),'orders':v.get(tid,{}).get('work_order_target')} for q,v in item['quarters'].items()}
   monthly_cash = [act.get((m,tid,n,'passive_reported_cash'),0) for m in MONTHS]
   monthly_orders = [act.get((m,tid,n,'work_orders'),0) for m in MONTHS]
   prior_monthly_cash = [prior_act.get((m,tid,n,'passive_reported_cash'),0) for m in PRIOR_MONTHS]
   prior_monthly_orders = [prior_act.get((m,tid,n,'work_orders'),0) for m in PRIOR_MONTHS]
   gs.append({'display_name':n,'quarter_targets':qt,'annual_targets':{'cash':sum((x['cash'] or 0) for x in qt.values()) or None,'orders':sum((x['orders'] or 0) for x in qt.values()) or None},'monthly_actuals':{'cash':monthly_cash,'orders':monthly_orders},'prior_monthly_actuals':{'cash':prior_monthly_cash,'orders':prior_monthly_orders},'cash_actual':sum(monthly_cash),'orders_actual':sum(monthly_orders)})
  roster=[]
  for t in people.get('teams',[]):
   if t['team_id']==tid:
    for g in t.get('groups',[]):
     for person in g.get('members',[]):
      person_name = person.get('display_name')
      # 添加月度数据
      monthly_cash = [per_monthly.get((tid,person_name,m,'passive_reported_cash'),0) for m in MONTHS]
      monthly_orders = [per_monthly.get((tid,person_name,m,'work_orders'),0) for m in MONTHS]
      roster.append({
        'display_name':person_name,
        'group_name':g.get('display_name'),
        'status':person.get('status'),
        'cash_actual':per.get((tid,person_name,'passive_reported_cash'),0),
        'orders_actual':per.get((tid,person_name,'work_orders'),0),
        'monthly_actuals':{'cash':monthly_cash,'orders':monthly_orders}
      })
  team_cash_target=sum(g['annual_targets']['cash'] or 0 for g in gs)
  team_orders_target=sum(g['annual_targets']['orders'] or 0 for g in gs)
  teams.append({'team_id':tid,'display_name':label,'cash_target':team_cash_target or None,'orders_target':team_orders_target or None,'groups':gs,'people':roster})
 return {'months':MONTHS,'prior_months':PRIOR_MONTHS,'teams':teams,'channels':ch}
def refresh(workspace,run_id):
 from datetime import date
 ws=workspace.resolve(); c=read(ws/'Work/workspace.json'); snap=c['current_snapshot_id']; out=ws/'Output/Dashboard'/run_id; out.mkdir(parents=True,exist_ok=False)

 # 计算当前日期和去年同期日期
 today = date.today()
 fiscal_year_start = date(2026, 6, 1)
 prior_fiscal_year_start = date(2025, 6, 1)

 # 今年：从财年开始到今天
 current_start = fiscal_year_start.isoformat()
 current_end = today.isoformat()

 # 去年同期：从去年财年开始，到去年的相同天数
 days_into_fy = (today - fiscal_year_start).days
 prior_end = prior_fiscal_year_start + (today - fiscal_year_start)
 prior_start = prior_fiscal_year_start.isoformat()
 prior_end_str = prior_end.isoformat()

 q=run(ws,run_id,snap,out,current_start,current_end)
 p=run(ws,run_id+'_prior',snap,out,prior_start,prior_end_str)
 d=project(q,p,read(ROOT/'config/project_targets.json'),read(ROOT/'config/people.json'))
 a={'schema_version':'dashboard_artifact.v1','artifact_id':'dashboard_'+uuid4().hex[:12],'run_id':run_id,'snapshot_id':snap,'as_of_date':today.isoformat(),'data_through_date':(today.fromordinal(today.toordinal()-1)).isoformat(),'created_at':datetime.now(timezone.utc).isoformat(),'query_results':[q,p],'errors':[],'dashboard':d}
 path=out/'artifact.json'; path.write_text(json.dumps(a,ensure_ascii=False,indent=2),encoding='utf-8')
 return {'status':'artifact_created','artifact':str(path)}
def render(artifact):
 import sys; sys.path.insert(0,str(ROOT.parent))
 from dashboard_product.render_template import render_html
 a=read(artifact); out=Path(artifact).with_suffix('.html'); out.write_text(render_html(a),encoding='utf-8'); return {'status':'rendered','output':str(out)}
def main():
 p=argparse.ArgumentParser(); s=p.add_subparsers(dest='c',required=True); r=s.add_parser('refresh'); r.add_argument('--workspace',type=Path,required=True); r.add_argument('--run-id',required=True); r=s.add_parser('render'); r.add_argument('--artifact',type=Path,required=True); s.add_parser('push'); x=p.parse_args(); z=refresh(x.workspace,x.run_id) if x.c=='refresh' else render(x.artifact) if x.c=='render' else {'status':'not_started'}; print(json.dumps(z,ensure_ascii=False)); return 0 if z['status']!='not_started' else 2
if __name__=='__main__': raise SystemExit(main())
