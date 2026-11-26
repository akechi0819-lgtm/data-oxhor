"""Personal calendar/performance views over SQL facts and static roster tables."""
import json
from pathlib import Path

from .relations import load_rows


def install_personal(con, *, config_root):
    # _roster reads only fixed configuration, never customer records.
    from dashboard_product.shadow_bi.sql_warehouse.common_rules import _roster
    root = Path(config_root)
    people = json.loads((root/'workspace_modeling/operations/people.json').read_text())
    abroad = json.loads((root/'dashboard_product/config/offline_market_people.json').read_text())
    roster = _roster(people, abroad)
    from dashboard_product.shadow_bi.sql_warehouse.common_rules import _group_members
    membership=_group_members(people)
    if any(p['business_line']=='training+abroad' for p in roster):
        raise ValueError('人员主业务配置冲突')
    load_rows(con,'config','people',[
        {**{k:v for k,v in p.items() if k not in ('targets','team_ids','lines')},
         'team_ids':sorted(p['team_ids']),
         'selection_group':membership.get(p['name'],p['home_group'] if p['business_line']=='abroad' else None)} for p in roster])
    targets=[]
    for p in roster:
        for line, months in p['targets'].items():
            for month, values in months.items():
                for metric, amount in values.items():
                    targets.append(dict(name=p['name'],business_line=line,month=month,metric=metric,target=amount))
    load_rows(con,'config','personal_targets',targets,columns={
        'name':'VARCHAR','business_line':'VARCHAR','month':'VARCHAR','metric':'VARCHAR','target':'DECIMAL(24,2)'})
    con.execute((Path(__file__).parent/'sql/personal.sql').read_text())
