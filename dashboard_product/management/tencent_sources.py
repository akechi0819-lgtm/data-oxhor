"""Explicit Tencent native CSV candidate; preserve observed scope and cost basis."""
import hashlib,json,re
from datetime import date
from pathlib import Path
from data_acquisition.connectors.advertising.tencent_native import inspect_report

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
