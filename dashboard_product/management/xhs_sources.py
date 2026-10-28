"""星火原生全账户分日表：按已对齐品牌归属接入子账户，不累加品牌主账户。"""
from datetime import date, datetime
import re


def validate_xhs_mcc_entry(entry):
    required = {'source_id', 'path', 'kind', 'start_date', 'end_date', 'brand_accounts'}
    if not required.issubset(entry) or set(entry) - required - {'sha256'}:
        raise ValueError('星火来源必须声明文件、日期和品牌业务归属')
    if any(not isinstance(entry[k], str) or not entry[k].strip() for k in ('source_id', 'path')):
        raise ValueError('星火来源ID和路径不能为空')
    start, end = (date.fromisoformat(entry[k]).isoformat() for k in ('start_date', 'end_date'))
    if start > end:
        raise ValueError('星火来源日期倒置')
    if entry.get('sha256') is not None and not re.fullmatch(r'[0-9a-fA-F]{64}', str(entry['sha256'])):
        raise ValueError('星火文件sha256无效')
    brands = entry['brand_accounts']
    if not isinstance(brands, dict) or not brands:
        raise ValueError('星火品牌业务归属不能为空')
    groups = {'training': {'留学预备', '高中', '大学'}, 'abroad': {'留学整体'}}
    for brand, mapping in brands.items():
        if not isinstance(brand, str) or not brand.strip() or not isinstance(mapping, dict) or set(mapping) != {'business_line', 'business_group'}:
            raise ValueError('星火品牌必须明确业务线与业务组')
        if mapping['business_group'] not in groups.get(mapping['business_line'], set()):
            raise ValueError('星火品牌业务归属无效')
    return {**entry, 'start_date': start, 'end_date': end, 'business_line': None, 'business_group': None}


def parse_xhs_mcc(item):
    from .advertising_sources import _read_rows, _header_map, _require_columns, _row_values, _parse_amount, _source_metadata
    path = item['resolved_path']
    table, _ = _read_rows(item['raw'], path)
    headers = _header_map(table[0] if table else (), path, 1)
    _require_columns(headers, ('周期', '投放ID', '账户类型', '广告主账户ID', '总消耗'), path)
    rows, accounts, seen = [], {}, set()
    for number, row in enumerate(table[1:], 2):
        cells = _row_values(headers, row)
        if not any(v is not None and str(v).strip() for v in row):
            continue
        day = datetime.strptime(str(cells['周期']).strip(), '%Y%m%d').date().isoformat()
        if not item['start_date'] <= day <= item['end_date']:
            continue
        value = cells['投放ID']
        account = str(int(value)) if isinstance(value, (int, float)) else str(value).strip()
        if not account.isdigit():
            raise ValueError('星火投放ID无效')
        key = (account, day)
        if key in seen:
            raise ValueError(f'星火账户日期重复: {account}/{day}')
        seen.add(key)
        amount = _parse_amount(cells['总消耗'], path, number, '总消耗')
        kind = cells['账户类型']
        if kind == '品牌主账户':
            if amount not in (None, 0):
                raise ValueError('星火品牌主账户有消费，需核对其是否为子账户汇总')
            continue
        if kind != '代理商子账户':
            raise ValueError(f'星火账户类型未对齐: {kind}')
        brand = str(cells['广告主账户ID']).strip()
        if brand not in item['brand_accounts']:
            raise ValueError(f'星火品牌业务归属未对齐: {brand}')
        mapping = item['brand_accounts'][brand]
        previous = accounts.get(account)
        if previous and previous['brand_account_id'] != brand:
            raise ValueError('星火同一投放ID关联多个品牌')
        account_info = {'account_id': account, 'brand_account_id': brand,
                        'account_name': cells.get('代理商子账户名称'), **mapping}
        accounts[account] = account_info
        rows.append({'source_id': item['source_id'] + ':' + account, 'source_row': number,
                     **account_info, 'platform': '小红书', 'start_date': day, 'end_date': day,
                     'amount': None if amount is None else float(amount)})
    sources = []
    for account, info in sorted(accounts.items()):
        days = [r['start_date'] for r in rows if r['account_id'] == account]
        leaf = {**item, **info, 'source_id': item['source_id'] + ':' + account}
        sources.append({**_source_metadata(leaf, grain='daily', platform='小红书', start_date=min(days), end_date=max(days)),
                        **{k: info[k] for k in ('account_id', 'brand_account_id', 'account_name')},
                        'amount_basis': '星火账户分日总消耗；排除品牌主账户，原生零消费日保留'})
    return rows, sources
