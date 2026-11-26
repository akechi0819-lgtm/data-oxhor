"""Explicit Tencent native CSV candidate; preserve observed scope and cost basis."""
import hashlib,json,re
from datetime import date
from decimal import Decimal
from pathlib import Path
from data_acquisition.connectors.advertising.tencent_native import inspect_report

TENCENT_MANUAL = 'tencent_manual_csv'


def validate_tencent_manual(entry):
    required = {'source_id', 'path', 'sha256', 'kind', 'business_line', 'business_group', 'platform', 'account_id', 'grain'}
    if set(entry) != required or not all(isinstance(entry[k], str) and entry[k] for k in required):
        raise ValueError('腾讯手工费用清单字段无效')
    groups = {'training': {'高中', '大学'}, 'abroad': {'留学整体'}}
    if (entry['platform'] != '腾讯广告' or entry['business_group'] not in groups.get(entry['business_line'], ())
            or entry['grain'] not in {'daily', 'period'} or not entry['account_id'].isdigit()
            or not re.fullmatch('[0-9a-f]{64}', entry['sha256'])):
        raise ValueError('腾讯手工费用归属、粒度或摘要无效')
    return dict(entry)


def parse_tencent_manual(item):
    from .advertising_sources import _read_rows, _parse_amount, _source_metadata
    path = item['resolved_path']
    table, _ = _read_rows(item['raw'], path)
    if len(table) < 2 or table[0] != ('开始日期', '结束日期', '业务组', '花费'):
        raise ValueError('腾讯手工费用明细列无效')
    rows = []
    seen = set()
    for source_row, (start, end, group, value) in enumerate(table[1:], 2):
        start, end = date.fromisoformat(start).isoformat(), date.fromisoformat(end).isoformat()
        amount = _parse_amount(value, path, source_row, '花费')
        if (group != item['business_group'] or start > end or ((start == end) != (item['grain'] == 'daily'))
                or amount is None or amount != amount.quantize(Decimal('0.01')) or (start, end) in seen):
            raise ValueError(f'腾讯手工费用日期或金额无效: {path} 第{source_row}行')
        seen.add((start, end))
        record = {name: item[name] for name in ('source_id', 'business_line', 'business_group', 'platform', 'account_id')}
        rows.append({**record, 'source_row': source_row, 'start_date': start, 'end_date': end, 'amount': float(amount)})
    source = _source_metadata(item, grain=item['grain'], platform=item['platform'],
                              start_date=min(r['start_date'] for r in rows), end_date=max(r['end_date'] for r in rows))
    return rows, [{**source, 'account_id': item['account_id'], 'source_kind': TENCENT_MANUAL}]


def validate_tencent_entry(entry):
    required={'source_id','path','sha256','kind','business_line','business_group','platform','account_id','product_scope','time_basis','start_date','end_date','capture_evidence'}
    if set(entry)!=required or entry.get('kind')!='tencent_native_csv':raise ValueError('tencent_manifest_fields_invalid')
    if not all(isinstance(entry[k],str) and entry[k] for k in required-{'capture_evidence'}):raise ValueError('tencent_manifest_text_invalid')
    if (entry['account_id'],entry['business_line'],entry['business_group'],entry['platform'])!=('74749810','abroad','留学整体','腾讯广告'):raise ValueError('tencent_business_scope_unverified')
    if entry['product_scope'] not in {'legacy_search','display_plus'} or entry['time_basis']!='播放口径':raise ValueError('tencent_product_or_time_basis_unverified')
    if date.fromisoformat(entry['start_date'])>date.fromisoformat(entry['end_date']):raise ValueError('tencent_window_invalid')
    if not re.fullmatch('[0-9a-f]{64}',entry['sha256']):raise ValueError('tencent_digest_invalid')
    proof=entry['capture_evidence']
    if not isinstance(proof,dict) or set(proof)!={'path','sha256'} or not isinstance(proof['path'],str) or not Path(proof['path']).is_absolute() or not isinstance(proof['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',proof['sha256']):raise ValueError('tencent_capture_reference_invalid')
    return dict(entry)

def parse_tencent(item):
    from .advertising_sources import _source_metadata
    proof=item['capture_evidence'];raw=Path(proof['path']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=proof['sha256']:raise ValueError('tencent_capture_digest_mismatch')
    state=json.loads(raw)
    if (state.get('phase')!='verified' or state.get('account_id')!=item['account_id'] or state.get('product_scope')!=item['product_scope'] or state.get('window')!=[item['start_date'],item['end_date']] or state.get('file_sha256')!=item['actual_sha256']):raise ValueError('tencent_capture_identity_mismatch')
    native=inspect_report(item['resolved_path'],account_id=item['account_id'],product_scope=item['product_scope'],time_basis=item['time_basis'],start_date=item['start_date'],through_date=item['end_date'])
    if state.get('native',{}).get('total')!=native['total'] or state.get('native',{}).get('rows')!=native['rows']:raise ValueError('tencent_capture_data_mismatch')
    rows=[{'source_id':item['source_id'],'source_row':r['source_row'],'business_line':item['business_line'],'business_group':item['business_group'],'platform':'腾讯广告','account_id':item['account_id'],'product_scope':item['product_scope'],'start_date':r['date'],'end_date':r['date'],'amount':float(r['spend'])} for r in native['rows_data']]
    source={**_source_metadata(item,grain='daily',platform='腾讯广告',start_date=native['actual_first_date'],end_date=native['actual_last_date']),'account_id':item['account_id'],'product_scope':item['product_scope'],'time_basis':item['time_basis'],'amount_basis':'腾讯原生花费；未换算现金、返佣或税额','selected_window':native['selected_window'],'missing_selected_dates':native['missing_selected_dates'],'whole_account_complete':False}
    return rows,[source]
