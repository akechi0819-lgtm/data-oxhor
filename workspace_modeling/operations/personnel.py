import re
from pathlib import Path

PEOPLE_CONFIG_PATH = Path(__file__).with_name("people.json")
BUSINESS_GROUP_BY_ROSTER_GROUP={'青少组':'留学预备','小初提能组':'留学预备','高中组':'高中','高中多途径组':'高中','国际学校择校组':'高中','大学组':'大学'}

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
