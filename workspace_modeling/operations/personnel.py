import re
from pathlib import Path
from decimal import Decimal

PEOPLE_CONFIG_PATH = Path(__file__).with_name("people.json")
BUSINESS_GROUP_BY_ROSTER_GROUP={'青少组':'留学预备','小初提能组':'留学预备','高中组':'高中','高中多途径组':'高中','国际学校择校组':'高中','大学组':'大学'}
HIDDEN_PERSON_STATUSES = frozenset({'vacant', 'departed', 'transferred'})
ORDER_STATUS_MODES = ('00', '01', '10', '11')
DEFAULT_ORDER_STATUS_MODE = '01'
ORDER_STATUS_VALUES = frozenset({'删除', '死单', '回收'})


def order_status_allowed(status, mode):
    """Return whether a work-order status is included by the two selector bits."""
    if mode not in ORDER_STATUS_MODES:
        raise ValueError(f'unsupported order status mode: {mode!r}')
    normalized = str(status or '').strip()
    if normalized in ('删除', '回收'):
        return mode[0] == '1'
    if normalized == '死单':
        return mode[1] == '1'
    return True

def is_displayable_person(person):
    return bool(person.get('display_name')) and person.get('status') not in HIDDEN_PERSON_STATUSES


def co_creation_weights(names, roster_by_name):
    """Return individual attribution weights for currently displayed co-creators.

    Offline-market members share one contribution equally. Online-private
    virtual members each receive a full contribution and do not dilute the
    offline denominator. Names absent from the current roster or in an
    existing hidden status do not participate.
    """
    if isinstance(names, str):
        names = (names,)

    offline = []
    virtual = []
    seen = set()
    roster_by_name = roster_by_name or {}
    for raw_name in names or ():
        name = str(raw_name or '').strip()
        if not name or name in seen:
            continue
        seen.add(name)
        person = roster_by_name.get(name)
        if not person or person.get('status') in HIDDEN_PERSON_STATUSES:
            continue
        team_ids = person.get('team_ids') or ()
        if isinstance(team_ids, str):
            team_ids = (team_ids,)
        team_ids = set(team_ids)
        if 'online_private' in team_ids:
            virtual.append(name)
        elif 'offline_market' in team_ids:
            offline.append(name)

    result = {name: Decimal(1) for name in virtual}
    if offline:
        weight = Decimal(1) / Decimal(len(offline))
        result.update({name: weight for name in offline})
    return result


ACTIVITY_BRACKETS = re.compile(r'（([^）]*)）|\(([^)]*)\)')


def activity_co_creation_weights(names, roster_by_name, business_line, campaign):
    """本业务主办者全计；明确括号跨业务接收只分实际跨业务成果。

    活动名不是业务线证据，业务线来自事实。只在已识别归属人员内区分
    括号外主办与括号内接收；没有明确双方或主办业务不唯一时沿用共创。
    虚拟人仍独立全计，不参与线下分母。
    """
    weights = co_creation_weights(names, roster_by_name)
    text = str(campaign or '')
    outside = ACTIVITY_BRACKETS.sub(' ', text)
    bracket_text = ' '.join(match.group(1) or match.group(2) or ''
                            for match in ACTIVITY_BRACKETS.finditer(text))
    offline = [name for name in weights
               if 'online_private' not in roster_by_name[name]['team_ids']]
    primary = [name for name in offline if name in outside]
    secondary = [name for name in offline if name not in primary and name in bracket_text]
    primary_lines = {roster_by_name[name].get('business_line') for name in primary}
    if (not primary or not secondary or len(primary_lines) != 1
            or not primary_lines <= {'training', 'abroad'}):
        return weights
    own_line = next(iter(primary_lines))
    creators = primary + [name for name in secondary
                          if roster_by_name[name].get('business_line') == own_line]
    receivers = [name for name in secondary
                 if roster_by_name[name].get('business_line') == business_line
                 and roster_by_name[name].get('business_line') != own_line]
    # 未能归入明确双方的已识别人名不能被活动解析静默丢弃。
    if set(creators + secondary) != set(offline):
        return weights
    virtual = {name: weight for name, weight in weights.items() if name not in offline}
    creator_weights = co_creation_weights(creators, roster_by_name)
    if business_line == own_line or not receivers:
        return {**virtual, **creator_weights}
    receiver_weights = co_creation_weights(receivers, roster_by_name)
    return {**virtual,
            **{name: weight * Decimal('0.5') for name, weight in creator_weights.items()},
            **{name: weight * Decimal('0.5') for name, weight in receiver_weights.items()}}

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
