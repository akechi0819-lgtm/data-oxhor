#!/usr/bin/env python3
"""Retained V14 projection and attribution helpers used by management builds."""
from workspace_modeling.operations.personnel import BUSINESS_GROUP_BY_ROSTER_GROUP, date_to_perf_month, is_displayable_person, match_person_names
from dashboard_product.fallback_mapping import infer_team, resolve_cash_channel
DASHBOARD_QUERY_COLUMNS=(
    'event_date','team_id','business_group','first_channel','second_channel',
    'campaign_name','entry_person','school_name','grade_name','metric',
    'actual_value','student_id','cash_channel','work_order_active_type','cash_campaign_name',
)
TEAMS=[('offline_market','线下市场'),('online_private','线上私域（虚拟人团队）'),('online_platform','线上平台')]
MARKET_TOTAL_TEAMS=[('offline_market','线下市场'),('online_platform','线上市场'),('online_private','虚拟人')]
# 个人月度实际按自然月的团队（20260929 v3：虚拟人团队 online_private 改为绩效月，只剩线上平台）。
PERSON_NATURAL_MONTH_TEAMS=('online_platform',)
UNASSIGNED_TEAM='暂时无法识别团队'
MARKET_TOTAL_TEAM_IDS={team_id for team_id,_ in MARKET_TOTAL_TEAMS}
MONTHS=[f'2026-{m:02d}' for m in range(6,13)]+[f'2027-{m:02d}' for m in range(1,6)]
PRIOR_MONTHS=[f'2025-{m:02d}' for m in range(6,13)]+[f'2026-{m:02d}' for m in range(1,6)]
YOY_GROUPS=('青少','初中','高中','大学')
TARGET_GROUP={'青少':'留学预备','初中':'留学预备','高中':'高中','大学':'大学'}
UNASSIGNED_GROUP='业务组暂无法拆分'

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
    note_positions=[position for marker in ('备注:', '备注：')
                    if (position := name.find(marker)) >= 0]
    if note_positions:
        name=name[:min(note_positions)].strip()
    if name and name in offline_names:
        return 'offline_market'
    return team

def project(q,p,tg,people,capacity=None):
 from dashboard_product.capacity import add_contribution, annual_cash_capacity, credit_unique, empty_contributions, person_line, unique_total
 act={}; yoy_act={}; per={}; prior_act={}; yoy_prior={}; per_monthly={}; person_drill={}; heads_credits={}
 market_act={}; market_yoy={}; market_prior={}; market_yoy_prior={}
 market_team_act={}; market_team_prior={}
 drill={"current":{"cash":{"channel":{},"school_grade":{}},"orders":{"channel":{},"school_grade":{}}},"prior":{"cash":{"channel":{},"school_grade":{}},"orders":{"channel":{},"school_grade":{}}}}
 configured_people=[]
 for team_config in people.get('teams',[]):
  for group_config in team_config.get('groups',[]):
   group_business_group=BUSINESS_GROUP_BY_ROSTER_GROUP.get(group_config.get('display_name'))
   for person in group_config.get('members',[]):
    person_name=person.get('display_name')
    if not is_displayable_person(person): continue
    configured_people.append((team_config['team_id'], person.get('business_group') or group_business_group, person_name))
 offline_names={name for configured_team,_,name in configured_people if configured_team=='offline_market'}

 def matched_people(team, business_group, campaign, entry_person):
  candidates=[name for configured_team, configured_group, name in configured_people
              if configured_team == team and configured_group == business_group]
  return match_person_names(candidates, campaign, entry_person)

 def add_row(row, period, months, actuals, yoy_actuals, is_current):
  if len(row)!=15: raise ValueError(f'Unexpected dashboard query row: expected 15 columns, got {len(row)}')
  dt,team,group,first_ch,second_ch,campaign,entry_person,school,grade,metric,val,student_id,cash_channel,work_order_active_type,cash_campaign = row
  if group not in (*YOY_GROUPS,UNASSIGNED_GROUP) or metric not in ('work_orders','passive_reported_cash') or val in (None, ''): return
  month=str(dt)[:7]; value=float(val); target=TARGET_GROUP.get(group,UNASSIGNED_GROUP)
  fallback_team=False
  if metric=='passive_reported_cash':
   original_team=team
   channel_result=resolve_cash_channel(cash_channel, cash_campaign or campaign, first_ch, second_ch, work_order_active_type)
   first_ch=channel_result['first_channel']
   second_ch=channel_result['second_channel']
   if not original_team or 'TMK' in str(cash_channel or '').upper():
    team,_=infer_team(original_team,cash_channel,cash_campaign or campaign,first_ch,second_ch,channel_result['decision'])
   fallback_team=team!=original_team
  team=remap_tmk_school_agent_team(team, first_ch, campaign, entry_person, offline_names)
  team_bucket=team if team in MARKET_TOTAL_TEAM_IDS else None
  team_actuals=market_team_act if is_current else market_team_prior
  team_key=(month,team_bucket,metric)
  team_actuals[team_key]=team_actuals.get(team_key,0)+value
  market_actuals=market_act if is_current else market_prior
  market_yoy_actuals=market_yoy if is_current else market_yoy_prior
  market_actuals[(month,target,metric)]=market_actuals.get((month,target,metric),0)+value
  market_yoy_actuals[(month,group,metric)]=market_yoy_actuals.get((month,group,metric),0)+value
  metric_key='cash' if metric=='passive_reported_cash' else 'orders'
  market_channel_key='|'.join((month,'market_total',group,str(first_ch or '未归类'),str(second_ch or '未细分')))
  market_grade_key='|'.join((month,'market_total',group,str(school or '暂无归属'),str(grade or '暂无归属')))
  drill[period][metric_key]['channel'][market_channel_key]=drill[period][metric_key]['channel'].get(market_channel_key,0)+value
  drill[period][metric_key]['school_grade'][market_grade_key]=drill[period][metric_key]['school_grade'].get(market_grade_key,0)+value
  if not team or group not in YOY_GROUPS: return
  actuals[(month,team,target,metric)]=actuals.get((month,team,target,metric),0)+value
  yoy_actuals[(month,team,group,metric)]=yoy_actuals.get((month,team,group,metric),0)+value
  channel_key='|'.join((month,team,group,str(first_ch or '未归类'),str(second_ch or '未细分')))
  grade_key='|'.join((month,team,group,str(school or '暂无归属'),str(grade or '暂无归属')))
  drill[period][metric_key]['channel'][channel_key]=drill[period][metric_key]['channel'].get(channel_key,0)+value
  drill[period][metric_key]['school_grade'][grade_key]=drill[period][metric_key]['school_grade'].get(grade_key,0)+value
  people_hit=[] if fallback_team else matched_people(team, target, campaign, entry_person)
  for person_name in people_hit:
   if is_current:
    per[(team,person_name,metric)]=per.get((team,person_name,metric),0)+value
    # 个人维度：线下与虚拟人团队（online_private，20260929 v3）按绩效月（上月26日至本月25日）；线上平台个人目标与实际按自然月（ab53258）。
    # 团队/总体上方仍按自然月 month；查询上界已截到 data_through。
    perf_month=str(dt)[:7] if team in PERSON_NATURAL_MONTH_TEAMS else date_to_perf_month(dt)
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
   mt={month:{'cash':v.get(tid,{}).get('passive_cash_target'),'orders':v.get(tid,{}).get('work_order_target')} for month,v in (item.get('months') or {}).items()}
   monthly_cash = [act.get((m,tid,n,'passive_reported_cash'),0) for m in MONTHS]
   monthly_orders = [act.get((m,tid,n,'work_orders'),0) for m in MONTHS]
   prior_monthly_cash = [prior_act.get((m,tid,n,'passive_reported_cash'),0) for m in PRIOR_MONTHS]
   prior_monthly_orders = [prior_act.get((m,tid,n,'work_orders'),0) for m in PRIOR_MONTHS]
   gs.append({'display_name':n,'quarter_targets':qt,'annual_targets':{'cash':sum((x['cash'] or 0) for x in qt.values()) or None,'orders':sum((x['orders'] or 0) for x in qt.values()) or None},'monthly_targets':mt,'monthly_actuals':{'cash':monthly_cash,'orders':monthly_orders},'prior_monthly_actuals':{'cash':prior_monthly_cash,'orders':prior_monthly_orders},'cash_actual':sum(monthly_cash),'orders_actual':sum(monthly_orders)})
  roster=[]
  for t in people.get('teams',[]):
   if t['team_id']==tid:
    for g in t.get('groups',[]):
     for person in g.get('members',[]):
      person_name = person.get('display_name')
      if not is_displayable_person(person):
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
 team_by_id={item['team_id']:item for item in teams}
 for team_id,team_label in MARKET_TOTAL_TEAMS:
  source=team_by_id[team_id]
  quarter_targets={quarter:{metric:sum((group['quarter_targets'].get(quarter,{}).get(metric) or 0) for group in source['groups']) or None for metric in ('cash','orders')} for quarter in ('Q1','Q2','Q3','Q4')}
  monthly_targets={month:{metric:sum((group.get('monthly_targets',{}).get(month,{}).get(metric) or 0) for group in source['groups']) or None for metric in ('cash','orders')} for month in MONTHS}
  annual_targets={metric:sum((group['annual_targets'][metric] or 0) for group in source['groups']) or None for metric in ('cash','orders')}
  monthly={'cash':[market_team_act.get((m,team_id,'passive_reported_cash'),0) for m in MONTHS],'orders':[market_team_act.get((m,team_id,'work_orders'),0) for m in MONTHS]}
  prior_monthly={'cash':[market_team_prior.get((m,team_id,'passive_reported_cash'),0) for m in PRIOR_MONTHS],'orders':[market_team_prior.get((m,team_id,'work_orders'),0) for m in PRIOR_MONTHS]}
  total_groups.append({'team_id':team_id,'display_name':team_label,'quarter_targets':quarter_targets,'monthly_targets':monthly_targets,'annual_targets':annual_targets,'monthly_actuals':monthly,'prior_monthly_actuals':prior_monthly,'cash_actual':sum(monthly['cash']),'orders_actual':sum(monthly['orders'])})
 unassigned_monthly={'cash':[market_team_act.get((m,None,'passive_reported_cash'),0) for m in MONTHS],'orders':[market_team_act.get((m,None,'work_orders'),0) for m in MONTHS]}
 unassigned_prior_monthly={'cash':[market_team_prior.get((m,None,'passive_reported_cash'),0) for m in PRIOR_MONTHS],'orders':[market_team_prior.get((m,None,'work_orders'),0) for m in PRIOR_MONTHS]}
 total_groups.append({'team_id':None,'display_name':UNASSIGNED_TEAM,'quarter_targets':{quarter:{'cash':None,'orders':None} for quarter in ('Q1','Q2','Q3','Q4')},'monthly_targets':{},'annual_targets':{'cash':None,'orders':None},'monthly_actuals':unassigned_monthly,'prior_monthly_actuals':unassigned_prior_monthly,'cash_actual':sum(unassigned_monthly['cash']),'orders_actual':sum(unassigned_monthly['orders'])})
 total_yoy=[]
 for n in (*YOY_GROUPS,UNASSIGNED_GROUP):
  total_yoy.append({'display_name':n,'monthly_actuals':{'cash':[market_yoy.get((m,n,'passive_reported_cash'),0) for m in MONTHS],'orders':[market_yoy.get((m,n,'work_orders'),0) for m in MONTHS]},'prior_monthly_actuals':{'cash':[market_yoy_prior.get((m,n,'passive_reported_cash'),0) for m in PRIOR_MONTHS],'orders':[market_yoy_prior.get((m,n,'work_orders'),0) for m in PRIOR_MONTHS]}})
 business_group_groups=[]
 target_groups=list(tg['business_groups'].values())
 target_group_names=[item['display_name'] for item in target_groups]
 for group_name in (*target_group_names,UNASSIGNED_GROUP):
  target_items=[item for item in target_groups if item['display_name']==group_name]
  quarter_targets={quarter:{metric:sum((item.get('quarters',{}).get(quarter,{}).get(team_id,{}).get('passive_cash_target' if metric=='cash' else 'work_order_target') or 0) for item in target_items for team_id,_ in MARKET_TOTAL_TEAMS) or None for metric in ('cash','orders')} for quarter in ('Q1','Q2','Q3','Q4')}
  monthly_targets={month:{metric:sum((item.get('months',{}).get(month,{}).get(team_id,{}).get('passive_cash_target' if metric=='cash' else 'work_order_target') or 0) for item in target_items for team_id,_ in MARKET_TOTAL_TEAMS) or None for metric in ('cash','orders')} for month in MONTHS}
  monthly={'cash':[market_act.get((month,group_name,'passive_reported_cash'),0) for month in MONTHS],'orders':[market_act.get((month,group_name,'work_orders'),0) for month in MONTHS]}
  prior_monthly={'cash':[market_prior.get((month,group_name,'passive_reported_cash'),0) for month in PRIOR_MONTHS],'orders':[market_prior.get((month,group_name,'work_orders'),0) for month in PRIOR_MONTHS]}
  annual_targets={metric:sum((targets.get(metric) or 0) for targets in quarter_targets.values()) or None for metric in ('cash','orders')}
  business_group_groups.append({'display_name':group_name,'quarter_targets':quarter_targets,'monthly_targets':monthly_targets,'annual_targets':annual_targets,'monthly_actuals':monthly,'prior_monthly_actuals':prior_monthly,'cash_actual':sum(monthly['cash']),'orders_actual':sum(monthly['orders'])})
 teams.append({'team_id':'market_total','display_name':'市场总计','cash_target':sum((team['cash_target'] or 0) for team in teams) or None,'orders_target':sum((team['orders_target'] or 0) for team in teams) or None,'groups':total_groups,'business_group_groups':business_group_groups,'yoy_groups':total_yoy,'people':[]})
 return {'months':MONTHS,'prior_months':PRIOR_MONTHS,'teams':teams,'drilldowns':drill}
