#!/usr/bin/env python3
import argparse,json,re,subprocess
from pathlib import Path
from datetime import datetime,timezone
from uuid import uuid4
ROOT=Path(__file__).parent
TEAMS=[('offline_market','线下市场'),('online_private','线上私域（虚拟人团队）'),('online_platform','线上平台')]
MONTHS=[f'2026-{m:02d}' for m in range(6,13)]+[f'2027-{m:02d}' for m in range(1,6)]
PRIOR_MONTHS=[f'2025-{m:02d}' for m in range(6,13)]+[f'2026-{m:02d}' for m in range(1,6)]
BUSINESS_GROUP_BY_ROSTER_GROUP={'青少组':'留学预备','小初提能组':'留学预备','高中组':'高中','高中多途径组':'高中','国际学校择校组':'高中','大学组':'大学'}
YOY_GROUPS=('青少','初中','高中','大学')
TARGET_GROUP={'青少':'留学预备','初中':'留学预备','高中':'高中','大学':'大学'}

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

SKIP_CAMPAIGN_VALUES=frozenset({'是','否','None','','NULL'})

def campaign_allows_person_match(campaign):
    return bool(campaign) and str(campaign) not in SKIP_CAMPAIGN_VALUES

MARKET_PERSON_RE=re.compile(r'市场人员\s*[:：]\s*([^\s,，;；]+)')
MARKET_RESOURCE_RE=re.compile(r'([^\s,，;；/]+)市场资源')
EMBEDDED_CAMPAIGN_RE=re.compile(r'\d{4}\.\d{2}\.\d{2}-\S+')

def names_in_text(names, text):
    blob=str(text or '')
    if not blob: return []
    return [name for name in names if name in blob]

def match_person_names(candidates, campaign, entry_person, resource_desc=None):
    names=[name for name in candidates if name]
    if not names: return []
    if campaign_allows_person_match(campaign):
        matched=names_in_text(names, campaign)
        if matched: return matched
    desc=str(resource_desc or '')
    labeled=MARKET_PERSON_RE.search(desc)
    if labeled:
        matched=names_in_text(names, labeled.group(1))
        if matched: return matched
    resource_owner=MARKET_RESOURCE_RE.search(desc)
    if resource_owner:
        matched=names_in_text(names, resource_owner.group(1))
        if matched: return matched
    matched=names_in_text(names, entry_person)
    if matched: return matched
    return names_in_text(names, EMBEDDED_CAMPAIGN_RE.sub(' ', desc))

SCHOOL_AGENT_RESOURCE_MARK='校代系统资源'
TMK_PLATFORM_CHANNEL='TMK激活-平台'

def remap_tmk_school_agent_team(team, first_channel, campaign, entry_person, offline_names):
    """Temporary patch: TMK-activated school-agent resources owned by offline roster count as offline."""
    if team != 'online_platform':
        return team
    if str(first_channel or '') != TMK_PLATFORM_CHANNEL:
        return team
    if SCHOOL_AGENT_RESOURCE_MARK not in str(campaign or ''):
        return team
    name=str(entry_person or '').strip()
    if name and name in offline_names:
        return 'offline_market'
    return team

def read(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def run(ws,rid,snap,out,a,b):
 c=read(ws/'Work/workspace.json'); z=subprocess.run(['python3','-m','interfaces.data_platform','run-saved-query','--warehouse',str(ws/c['current_warehouse_path']),'--snapshot-id',snap,'--run-id',rid,'--output-root',str(out),'--registry-root',str(ws/'Work/SavedQueries'),'--query-id','dashboard_actuals','--version','v9','--params-json',json.dumps([a,b]),'--max-rows','50000','--max-result-bytes','10000000'],cwd=ROOT.parent,capture_output=True,text=True); r=json.loads(z.stdout or '{}')
 if r.get('status')!='passed': raise ValueError(f"Query failed: {r.get('errors')} | stderr: {z.stderr}")
 # 如果 result 为 None，从 artifact 文件读取
 if not r.get('result') and r.get('artifact',{}).get('path'):
  artifact_path = out / rid / r['artifact']['path']  # artifact path 是相对于 out/rid/ 的
  artifact_data = read(artifact_path)
  r['result'] = artifact_data  # artifact 文件本身就是 {columns, rows} 结构
 if not r.get('result'): raise ValueError(f"Query returned no result: {r}")
 return r
def project(q,p,tg,people,capacity=None):
 from dashboard_product.capacity import add_contribution, annual_cash_capacity, credit_unique, empty_contributions, person_line, unique_total
 act={}; yoy_act={}; per={}; prior_act={}; yoy_prior={}; per_monthly={}; person_drill={}; heads_credits={}
 drill={"current":{"cash":{"channel":{},"school_grade":{}},"orders":{"channel":{},"school_grade":{}}},"prior":{"cash":{"channel":{},"school_grade":{}},"orders":{"channel":{},"school_grade":{}}}}
 configured_people=[]
 for team_config in people.get('teams',[]):
  for group_config in team_config.get('groups',[]):
   group_business_group=BUSINESS_GROUP_BY_ROSTER_GROUP.get(group_config.get('display_name'))
   for person in group_config.get('members',[]):
    person_name=person.get('display_name')
    if not person_name or person.get('status') == 'vacant': continue
    configured_people.append((team_config['team_id'], person.get('business_group') or group_business_group, person_name))
 offline_names={name for configured_team,_,name in configured_people if configured_team=='offline_market'}

 def matched_people(team, business_group, campaign, entry_person):
  candidates=[name for configured_team, configured_group, name in configured_people
              if configured_team == team and configured_group == business_group]
  return match_person_names(candidates, campaign, entry_person)

 def add_row(row, period, months, actuals, yoy_actuals, is_current):
  if len(row)!=12: raise ValueError(f'Unexpected dashboard query row: expected 12 columns, got {len(row)}')
  dt,team,group,first_ch,second_ch,campaign,entry_person,school,grade,metric,val,student_id = row[:12]
  team=remap_tmk_school_agent_team(team, first_ch, campaign, entry_person, offline_names)
  if not team or group not in YOY_GROUPS or metric not in ('work_orders','passive_reported_cash') or val in (None, ''): return
  month=str(dt)[:7]; value=float(val); target=TARGET_GROUP[group]
  actuals[(month,team,target,metric)]=actuals.get((month,team,target,metric),0)+value
  yoy_actuals[(month,team,group,metric)]=yoy_actuals.get((month,team,group,metric),0)+value
  metric_key='cash' if metric=='passive_reported_cash' else 'orders'
  channel_key='|'.join((month,team,group,str(first_ch or '未归类'),str(second_ch or '未细分')))
  grade_key='|'.join((month,team,group,str(school or '暂无归属'),str(grade or '暂无归属')))
  drill[period][metric_key]['channel'][channel_key]=drill[period][metric_key]['channel'].get(channel_key,0)+value
  drill[period][metric_key]['school_grade'][grade_key]=drill[period][metric_key]['school_grade'].get(grade_key,0)+value
  people_hit=matched_people(team, target, campaign, entry_person)
  for person_name in people_hit:
   if is_current:
    per[(team,person_name,metric)]=per.get((team,person_name,metric),0)+value
    perf_month=date_to_perf_month(dt)
    if perf_month: per_monthly[(team,person_name,perf_month,metric)]=per_monthly.get((team,person_name,perf_month,metric),0)+value
    if perf_month:
     drill_key=(team,person_name,perf_month,metric,str(first_ch or '未归类'),str(second_ch or '未细分'))
     person_drill[drill_key]=person_drill.get(drill_key,0)+value
  if is_current and metric=='passive_reported_cash' and people_hit:
   sid=str(student_id).strip() if student_id not in (None,'') else ''
   if sid:
    weight=1.0/len(people_hit)
    for person_name in people_hit:
     credit_unique(heads_credits,(team,person_name),sid,weight)
 # 处理当前年度数据
 for row in q['result']['rows']:
  add_row(row,'current',MONTHS,act,yoy_act,True)
 # 去年同期按自然月聚合。前端按所选季度切片，必须与当前年度使用相同月段。
 for row in p['result']['rows']:
  add_row(row,'prior',PRIOR_MONTHS,prior_act,yoy_prior,False)
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
      if person.get('status') == 'vacant':
       continue
      # 添加月度数据
      monthly_cash = [per_monthly.get((tid,person_name,m,'passive_reported_cash'),0) for m in MONTHS]
      monthly_orders = [per_monthly.get((tid,person_name,m,'work_orders'),0) for m in MONTHS]
      monthly_targets = person.get('monthly_targets', {})
      monthly_drilldowns = {}
      for month in MONTHS:
       monthly_drilldowns[month] = {'cash': {}, 'orders': {}}
      for (drill_team, drill_person, drill_month, drill_metric, first_channel, second_channel), value in person_drill.items():
       if drill_team != tid or drill_person != person_name or drill_month not in monthly_drilldowns: continue
       monthly_drilldowns[drill_month]['cash' if drill_metric == 'passive_reported_cash' else 'orders'][f'{first_channel}||{second_channel}'] = value
      contrib=empty_contributions()
      for (drill_team, drill_person, drill_month, drill_metric, first_channel, second_channel), value in person_drill.items():
       if drill_team==tid and drill_person==person_name and drill_metric=='passive_reported_cash':
        add_contribution(contrib, first_channel, second_channel, value)
      roster.append({
        'display_name':person_name,
        'group_name':g.get('display_name'),
        'business_group':person.get('business_group') or BUSINESS_GROUP_BY_ROSTER_GROUP.get(g.get('display_name')),
        'monthly_targets':monthly_targets,
        'cash_actual':per.get((tid,person_name,'passive_reported_cash'),0),
        'orders_actual':per.get((tid,person_name,'work_orders'),0),
        'heads_actual':unique_total(heads_credits,(tid,person_name)),
        'annual_cash_capacity':annual_cash_capacity(capacity),
        'line':person_line(tid),
        'cash_contributions':contrib,
        'monthly_actuals':{'cash':monthly_cash,'orders':monthly_orders},
        'monthly_drilldowns':monthly_drilldowns
      })
  yoy_gs=[]
  for n in YOY_GROUPS:
   yoy_gs.append({'display_name':n,'monthly_actuals':{'cash':[yoy_act.get((m,tid,n,'passive_reported_cash'),0) for m in MONTHS],'orders':[yoy_act.get((m,tid,n,'work_orders'),0) for m in MONTHS]},'prior_monthly_actuals':{'cash':[yoy_prior.get((m,tid,n,'passive_reported_cash'),0) for m in PRIOR_MONTHS],'orders':[yoy_prior.get((m,tid,n,'work_orders'),0) for m in PRIOR_MONTHS]}})
  team_cash_target=sum(g['annual_targets']['cash'] or 0 for g in gs)
  team_orders_target=sum(g['annual_targets']['orders'] or 0 for g in gs)
  teams.append({'team_id':tid,'display_name':label,'cash_target':team_cash_target or None,'orders_target':team_orders_target or None,'groups':gs,'yoy_groups':yoy_gs,'people':roster})
 total_groups=[]
 for group_name in [item['display_name'] for item in tg['business_groups'].values()]:
  sources=[team['groups'] for team in teams]
  group_items=[next(group for group in source if group['display_name']==group_name) for source in sources]
  total_groups.append({'display_name':group_name,'quarter_targets':{quarter:{metric:sum((item['quarter_targets'].get(quarter,{}).get(metric) or 0) for item in group_items) or None for metric in ('cash','orders')} for quarter in ('Q1','Q2','Q3','Q4')},'annual_targets':{'cash':sum((item['annual_targets']['cash'] or 0) for item in group_items) or None,'orders':sum((item['annual_targets']['orders'] or 0) for item in group_items) or None},'monthly_actuals':{'cash':[sum(item['monthly_actuals']['cash'][i] for item in group_items) for i in range(12)],'orders':[sum(item['monthly_actuals']['orders'][i] for item in group_items) for i in range(12)]},'prior_monthly_actuals':{'cash':[sum(item['prior_monthly_actuals']['cash'][i] for item in group_items) for i in range(12)],'orders':[sum(item['prior_monthly_actuals']['orders'][i] for item in group_items) for i in range(12)]},'cash_actual':sum(item['cash_actual'] for item in group_items),'orders_actual':sum(item['orders_actual'] for item in group_items)})
 total_yoy=[]
 for n in YOY_GROUPS:
  yoy_items=[next(group for group in team['yoy_groups'] if group['display_name']==n) for team in teams]
  total_yoy.append({'display_name':n,'monthly_actuals':{'cash':[sum(item['monthly_actuals']['cash'][i] for item in yoy_items) for i in range(12)],'orders':[sum(item['monthly_actuals']['orders'][i] for item in yoy_items) for i in range(12)]},'prior_monthly_actuals':{'cash':[sum(item['prior_monthly_actuals']['cash'][i] for item in yoy_items) for i in range(12)],'orders':[sum(item['prior_monthly_actuals']['orders'][i] for item in yoy_items) for i in range(12)]}})
 teams.append({'team_id':'market_total','display_name':'市场总计','cash_target':sum((team['cash_target'] or 0) for team in teams) or None,'orders_target':sum((team['orders_target'] or 0) for team in teams) or None,'groups':total_groups,'yoy_groups':total_yoy,'people':[]})
 for period in ('current','prior'):
  for metric in ('cash','orders'):
   for kind in ('channel','school_grade'):
    total={}
    for key,value in list(drill[period][metric][kind].items()):
     parts=key.split('|'); total_key='|'.join((parts[0],'market_total',*parts[2:]))
     total[total_key]=total.get(total_key,0)+value
    drill[period][metric][kind].update(total)
 return {'months':MONTHS,'prior_months':PRIOR_MONTHS,'teams':teams,'drilldowns':drill}
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
 d=project(q,p,read(ROOT/'config/project_targets.json'),read(ROOT/'config/people.json'),read(ROOT/'config/capacity_targets.json'))
 a={'schema_version':'dashboard_artifact.v1','artifact_id':'dashboard_'+uuid4().hex[:12],'run_id':run_id,'snapshot_id':snap,'as_of_date':today.isoformat(),'data_through_date':(today.fromordinal(today.toordinal()-1)).isoformat(),'created_at':datetime.now(timezone.utc).isoformat(),'query_results':[q,p],'errors':[],'dashboard':d}
 path=out/'artifact.json'; path.write_text(json.dumps(a,ensure_ascii=False,indent=2),encoding='utf-8')
 return {'status':'artifact_created','artifact':str(path)}
def render(artifact, booklet=None, output=None):
 import sys; sys.path.insert(0,str(ROOT.parent))
 from dashboard_product.render_template import render_html
 from dashboard_product.booklets import booklet_filename, validate_booklet
 booklet=validate_booklet(booklet)
 a=read(artifact); artifact=Path(artifact)
 if output is not None: out=Path(output)
 elif booklet: out=artifact.with_name(booklet_filename(booklet))
 else: out=artifact.with_suffix('.html')
 out.write_text(render_html(a, booklet=booklet),encoding='utf-8'); return {'status':'rendered','output':str(out),'booklet':booklet or 'full'}
def render_all_booklets(artifact):
 from dashboard_product.booklets import BOOKLET_IDS
 outputs=[render(artifact, booklet=booklet) for booklet in BOOKLET_IDS]
 return {'status':'rendered','outputs':[item['output'] for item in outputs],'booklets':list(BOOKLET_IDS)}
def main():
 p=argparse.ArgumentParser(); s=p.add_subparsers(dest='c',required=True)
 r=s.add_parser('refresh'); r.add_argument('--workspace',type=Path,required=True); r.add_argument('--run-id',required=True)
 r=s.add_parser('render'); r.add_argument('--artifact',type=Path,required=True)
 from dashboard_product.booklets import BOOKLET_IDS
 r.add_argument('--booklet',choices=list(BOOKLET_IDS))
 r.add_argument('--all-booklets',action='store_true')
 r.add_argument('--output',type=Path)
 x=p.parse_args()
 if x.c=='refresh': z=refresh(x.workspace,x.run_id)
 elif x.all_booklets:
  if x.booklet or x.output: p.error('use --all-booklets without --booklet/--output')
  z=render_all_booklets(x.artifact)
 else: z=render(x.artifact, booklet=x.booklet, output=x.output)
 print(json.dumps(z,ensure_ascii=False)); return 0
if __name__=='__main__': raise SystemExit(main())
