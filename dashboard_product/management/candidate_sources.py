"""Candidate-only source authority checks; registered production inputs are unchanged."""
from pathlib import Path
import hashlib

from .advertising_sources import OCEAN_ACCOUNT_DAILY, XHS_ACCOUNT_DAILY
import json

class CandidateSourceError(ValueError):
    pass


TENCENT_CONFIRMED_SCOPE_PAIR = {'legacy_search', 'display_plus'}


def _tencent_scope_confirmation(manifest, account, scopes, business_scope_confirmation=None):
    """Verify the user's additive rule without claiming technical disjointness."""
    if str(account) != '74749810' or scopes != TENCENT_CONFIRMED_SCOPE_PAIR:
        return False
    confirmation = business_scope_confirmation or manifest.get('business_scope_confirmation')
    if not isinstance(confirmation, dict):
        return False
    if (confirmation.get('account_id') != '74749810'
            or confirmation.get('product_scopes') != ['display_plus', 'legacy_search']
            or confirmation.get('combine_rule') != 'sum'):
        return False
    evidence = confirmation.get('evidence')
    if not isinstance(evidence, dict) or set(evidence) != {'path', 'sha256'}:
        return False
    path = Path(evidence['path'])
    if not path.is_absolute() or not path.is_file():
        return False
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != evidence['sha256']:
        return False
    record = json.loads(raw)
    return (record.get('evidence_type') == 'user_confirmed_business_scope'
            and record.get('account_id') == '74749810'
            and record.get('combine_rule') == 'sum'
            and set(record.get('confirmed_entrances', [])) == {'竞价－搜索投放', '竞价－展示投放'}
            and record.get('exclude_costs_by_product') is False
            and record.get('technical_disjointness_proven') is False)


def platform_family(platform):
    return '腾讯' if platform in {'微信','腾讯广告','腾讯'} else platform


def validate_candidate_authorities(manifest, *, business_scope_confirmation=None):
    entries=manifest.get('sources')
    if not isinstance(entries,list):raise CandidateSourceError('candidate_sources_missing')
    if manifest.get('network_period_differences') or any(e.get('kind')=='network_weekly' for e in entries):
        raise CandidateSourceError('candidate_group_aggregate_forbidden')
    authorities={};xhs_kinds=set()
    for entry in entries:
        kind=entry.get('kind')
        if kind in {'ocean_daily', OCEAN_ACCOUNT_DAILY}: authority,platforms='native:ocean',{'抖音'}
        elif kind in {'xhs_daily','xhs_mcc_daily', XHS_ACCOUNT_DAILY}:
            authority,platforms='native:xhs',{'小红书'};xhs_kinds.add(kind)
        elif kind=='tencent_native_csv':
            authority,platforms='native:tencent',{'腾讯广告'}
        elif kind=='sem_daily':authority,platforms='designated:sem',{m['platform'] for m in entry['sheets'].values()}
        else:raise CandidateSourceError('candidate_source_kind_unverified')
        for platform in platforms:
            family=platform_family(platform)
            if family not in {'抖音','小红书','腾讯','百度','必应','闲鱼','360','B站','微博'}:
                raise CandidateSourceError('candidate_platform_unverified')
            previous=authorities.get(family)
            if previous and previous['authority']!=authority:
                raise CandidateSourceError('candidate_authority_conflict:'+family)
            if not previous:authorities[family]={'authority':authority,'source_ids':[]}
            authorities[family]['source_ids'].append(entry['source_id'])
    if len(xhs_kinds)>1:
        raise CandidateSourceError('candidate_xhs_report_overlap_unverified')
    tencent_scopes={}
    for entry in entries:
        if entry.get('kind')!='tencent_native_csv':continue
        account=entry.get('account_id');scope=entry.get('product_scope')
        scopes=tencent_scopes.setdefault(account,set());scopes.add(scope)
    for account, scopes in tencent_scopes.items():
        if len(scopes)>1 and not _tencent_scope_confirmation(manifest,account,scopes,business_scope_confirmation):
            raise CandidateSourceError('candidate_tencent_product_overlap_unverified')
    return {p:{'authority':v['authority'],'source_ids':sorted(v['source_ids'])} for p,v in sorted(authorities.items())}


def validate_candidate_account_days(parsed, manifest=None, *, business_scope_confirmation=None):
    seen=set()
    tencent_scopes={}
    if manifest:
        for entry in manifest.get('sources',[]):
            if entry.get('kind')=='tencent_native_csv':
                tencent_scopes.setdefault(entry.get('account_id'),set()).add(entry.get('product_scope'))
    confirmed_tencent={account for account,scopes in tencent_scopes.items()
                       if _tencent_scope_confirmation(manifest or {},account,scopes,business_scope_confirmation)}
    for row in parsed['rows']:
        identity=('account',row['account_id']) if row.get('account_id') else ('sem_leaf',row['source_sheet']) if row.get('source_sheet') else None
        if (identity and identity[0]=='account' and platform_family(row['platform'])=='腾讯'
                and str(row['account_id']) in confirmed_tencent):
            identity=('account',row['account_id'],row.get('product_scope'))
        if identity is None:continue
        key=(platform_family(row['platform']),identity,row['start_date'],row['end_date'])
        if key in seen:raise CandidateSourceError('candidate_account_date_overlap')
        seen.add(key)


def load_candidate_sources(path, *, business_scope_confirmation=None):
    from .advertising_sources import load_sources,_read_rows,_daily_duplicate_key
    path=Path(path);manifest=json.loads(path.read_text(encoding='utf-8-sig'))
    validate_candidate_authorities(manifest,business_scope_confirmation=business_scope_confirmation)
    parsed=load_sources(path)
    validate_candidate_account_days(parsed,manifest,business_scope_confirmation=business_scope_confirmation)
    # Project IDs are native global keys; two revisions of the same project/day
    # must replace each other, never become two cost sources.
    project_keys=set()
    for entry in manifest['sources']:
        if entry['kind']!='ocean_daily':continue
        raw=Path(entry['path']);raw=raw if raw.is_absolute() else path.parent/raw
        table,_=_read_rows(raw.read_bytes(),raw);headers={str(v).strip():i for i,v in enumerate(table[0])}
        for row in (r for r in parsed['rows'] if r['source_id']==entry['source_id']):
            cells={k:table[row['source_row']-1][i] for k,i in headers.items()}
            key=_daily_duplicate_key(cells,row['start_date'],raw,row['source_row'])
            if key in project_keys:raise CandidateSourceError('candidate_ocean_project_date_overlap')
            project_keys.add(key)
    return parsed
