"""Receive explicit browser download paths; never collect, register or publish."""
from __future__ import annotations
import argparse
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo
from data_acquisition.connectors.advertising.native_exports import adopt_download_path, ExportError

SHANGHAI = ZoneInfo('Asia/Shanghai')
REQUIRED = {'ocean', 'xhs', 'sem', 'tencent_ads_abroad'}


def intake(inventory_path, output_dir, *, now=None):
    inventory_path = Path(inventory_path).absolute()
    raw = inventory_path.read_bytes()
    value = json.loads(raw)
    day = date.fromisoformat(value['as_of_date'])
    today = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI).date()
    if day != today:
        raise ValueError('inventory_not_today')
    captures = value['captures']
    if not isinstance(captures, list):
        raise ValueError('captures_not_array')
    keys = set()
    for item in captures:
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,50}', item['source']):
            raise ValueError('source_id_invalid')
        if item['status'] not in {'downloaded', 'login_required', 'failed', 'uncertain'}:
            raise ValueError('capture_status_invalid')
        if item['status'] != 'downloaded':
            continue
        captured = datetime.fromisoformat(item['captured_at'])
        if captured.tzinfo is None or captured.astimezone(SHANGHAI).date() != day:
            raise ValueError('capture_not_today_or_timezone_missing')
        accounts, window = item['account_ids'], item['selected_window']
        if not accounts or len(accounts) != len(set(accounts)) or len(window) != 2:
            raise ValueError('capture_scope_invalid')
        native_format = item.get('native_format', 'xlsx')
        if native_format not in {'xlsx', 'tencent_account_csv'}:
            raise ValueError('capture_format_invalid')
        if native_format == 'tencent_account_csv':
            from data_acquisition.connectors.advertising.tencent_native import SCOPES
            if (item['source'] != 'tencent_ads_abroad' or item.get('product_scope') not in SCOPES
                    or item.get('time_basis') != '播放口径'):
                raise ValueError('tencent_product_scope_missing')
        key = (item['source'], tuple(sorted(accounts)), tuple(window),
               item.get('product_scope') if native_format == 'tencent_account_csv' else None)
        if key in keys:
            raise ValueError('duplicate_logical_capture')
        keys.add(key)
    output = Path(output_dir).absolute()
    output.mkdir(parents=True, exist_ok=False)
    (output/'inventory.json').write_bytes(raw)
    received, available, failures = [], set(), []
    for number, item in enumerate(captures, 1):
        row = {k: item.get(k) for k in ('source','status','captured_at','account_ids','selected_window','completion','export_task_id','evidence_files','native_format','product_scope','time_basis')}
        if item['status'] == 'downloaded':
            try:
                source = Path(item['native_file'])
                if not source.is_absolute():
                    source = inventory_path.parent/source
                native_format = item.get('native_format', 'xlsx')
                extension = '.csv' if native_format == 'tencent_account_csv' else '.xlsx'
                saved = adopt_download_path(source, output/'native'/f'capture_{number:04d}{extension}',
                                            file_format=native_format)
                if item.get('sha256') and item['sha256'] != saved['sha256']:
                    raise ExportError('declared_digest_mismatch')
                row.update(status='received', file={**saved,'bytes':Path(saved['path']).stat().st_size})
                available.add(item['source'])
            except Exception as error:
                # Dependency messages can contain private paths/URLs. Fixed codes only.
                reason = str(error) if isinstance(error, ExportError) else type(error).__name__
                row.update(status='rejected', reason=reason)
                failures.append(item['source'])
        else:
            failures.append(item['source'])
        received.append(row)
    missing = sorted(REQUIRED-available)
    result = {'schema_version':'advertising_native_intake.v1','as_of_date':day.isoformat(),
        'status':'received' if not missing and not failures else 'received_with_gaps',
        'inventory_sha256':hashlib.sha256(raw).hexdigest(),'captures':received,
        'missing_required_sources':missing,'failed_sources':sorted(set(failures)),
        'source_completeness_checked':False,'registration_performed':False,'aggregation_performed':False,
        'candidate_built':False,'production_ready':False,'published':False,
        'next_step':'Validate native account/date/amount/completion and assemble final capture receipt before full_daily --prepare'}
    (output/'intake-receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args = parser.parse_args()
    try:
        result = intake(args.inventory,args.output_dir)
        print(json.dumps({'status':result['status'],'receipt':str(args.output_dir/'intake-receipt.json'),
            'missing_required_sources':result['missing_required_sources'],'production_ready':False},ensure_ascii=False))
        return 0 if result['status']=='received' else 2
    except Exception as error:
        print(json.dumps({'status':'rejected','reason':type(error).__name__},ensure_ascii=False))
        return 2


if __name__=='__main__':
    raise SystemExit(main())
