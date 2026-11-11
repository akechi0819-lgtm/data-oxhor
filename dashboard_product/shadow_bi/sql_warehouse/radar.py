"""SQL FY27 six-axis comparisons; configuration parsing has no fact dependency."""
import json
from pathlib import Path

from .relations import load_rows


def install_radar(con,*,config_root):
    from dashboard_product.management.capacity_radar import _training_roster,_abroad_roster
    root=Path(config_root)
    people=json.loads((root/'workspace_modeling/operations/people.json').read_text())
    abroad=json.loads((root/'dashboard_product/config/offline_market_people.json').read_text())
    training_roster=_training_roster(people);abroad_roster=_abroad_roster(abroad)
    if set(training_roster)&set(abroad_roster):raise ValueError('人员主业务冲突')
    roster={**training_roster,**abroad_roster}
    load_rows(con,'config','radar_people',[{'name':p['name'],'business_line':p['business_line'],
        'home_team':sorted(p['team_ids'])[0],'home_group':p['home_group'],'team_ids':sorted(p['team_ids'])}
        for p in roster.values()])
    targets=[{'name':p['name'],'month':m,'amount':p.get('monthly_targets',{}).get(m,{}).get('cash')}
        for p in abroad_roster.values() for m in
        [f'2026-{m:02d}' for m in range(6,13)]+[f'2027-{m:02d}' for m in range(1,6)]]
    load_rows(con,'config','radar_month_targets',targets,columns={'name':'VARCHAR','month':'VARCHAR','amount':'DECIMAL(24,2)'})
    cfg=json.loads((root/'dashboard_product/config/capacity_targets.json').read_text())
    load_rows(con,'config','radar_training_target',[{'amount':cfg['annual_cash_by_person']}],columns={'amount':'DECIMAL(24,2)'})
    con.execute((Path(__file__).parent/'sql/radar.sql').read_text())
