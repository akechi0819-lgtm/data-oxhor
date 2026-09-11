"""Person capacity ranking and radar contribution buckets."""

ANNUAL_CASH_CAPACITY = 800000
PARTNER_SECOND_CHANNELS = frozenset({'异业渠道', '线下校代'})
LINE_BY_TEAM = {
    'offline_market': 'offline',
    'online_private': 'online',
    'online_platform': 'online',
}


def person_line(team_id):
    return LINE_BY_TEAM.get(team_id, 'online')


def cash_contribution_bucket(first_channel, second_channel):
    first = str(first_channel or '')
    second = str(second_channel or '')
    if 'TMK' in first:
        return 'tmk'
    if first == '市场活动' and second in PARTNER_SECOND_CHANNELS:
        return 'partner'
    if first == '市场活动':
        return 'campaign'
    return 'other'


def empty_contributions():
    return {'partner': 0.0, 'tmk': 0.0, 'campaign': 0.0, 'other': 0.0}


def add_contribution(target, first_channel, second_channel, value):
    bucket = cash_contribution_bucket(first_channel, second_channel)
    target[bucket] = target.get(bucket, 0.0) + float(value or 0)
    return target


def credit_unique(store, key, item_id, weight):
    if not item_id:
        return
    current = store.setdefault(key, {})
    current[item_id] = max(current.get(item_id, 0.0), float(weight))


def unique_total(store, key):
    return float(sum((store.get(key) or {}).values()))


def annual_cash_capacity(config=None):
    if isinstance(config, dict) and config.get('annual_cash_by_person') not in (None, ''):
        return float(config['annual_cash_by_person'])
    return float(ANNUAL_CASH_CAPACITY)
