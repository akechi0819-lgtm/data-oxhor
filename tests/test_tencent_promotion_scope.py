import hashlib
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest

from data_acquisition.connectors.advertising import tencent_requests as tencent


WINDOW = ['2026-09-01', '2026-11-02']
SCOPES = [
    'bidding_display', 'bidding_search', 'bidding_search_upgrade',
    'brand_touch_contract', 'brand_search_contract', 'brand_content_contract',
    'brand_touch_rtb_all_states', 'brand_content_boost_all_created_dates',
]
FILTERS = {
    'bidding_display': [
        ('adgroup.brand_ad_type', 'EQUALS', 'BRAND_AD_TYPE_NONE'),
        ('adgroup.smart_delivery_platform', 'LESS', 'SMART_DELIVERY_PLATFORM_EDITION_SCENE'),
        ('adgroup.campaign_type', 'EQUALS', 'CAMPAIGN_TYPE_NORMAL'),
    ],
    'bidding_search': [
        ('campaign.campaign_type', 'EQUALS', 'CAMPAIGN_TYPE_SEARCH'),
        ('campaign.buying_type', 'EQUALS', 'BUYINGTYPE_AUCTION'),
    ],
    'bidding_search_upgrade': [
        ('adgroup.brand_ad_type', 'EQUALS', 'BRAND_AD_TYPE_NONE'),
        ('adgroup.campaign_type', 'EQUALS', 'CAMPAIGN_TYPE_SEARCH'),
        ('adgroup.smart_delivery_platform', 'LESS', 'SMART_DELIVERY_PLATFORM_EDITION_SCENE'),
    ],
    'brand_touch_contract': [
        ('campaign.campaign_type', 'EQUALS', 'CAMPAIGN_TYPE_NORMAL'),
        ('campaign.buying_type', 'EQUALS', 'BUYINGTYPE_CONTRACT'),
    ],
    'brand_search_contract': [
        ('campaign.campaign_type', 'EQUALS', 'CAMPAIGN_TYPE_SEARCH'),
        ('campaign.buying_type', 'EQUALS', 'BUYINGTYPE_CONTRACT'),
    ],
    'brand_content_contract': [
        ('campaign.campaign_type', 'EQUALS', 'CAMPAIGN_TYPE_NORMAL'),
        ('campaign.buying_type', 'EQUALS', 'BUYINGTYPE_CONTRACT'),
        ('campaign.brand_ad_category', 'EQUALS', 'BRAND_AD_CATEGORY_CHANNELS_NATIVE_FEED'),
    ],
    'brand_touch_rtb_all_states': [
        ('adgroup.brand_ad_type', 'EQUALS', 'BRAND_AD_TYPE_RTB'),
    ],
    'brand_content_boost_all_created_dates': [
        ('campaign.campaign_type', 'EQUALS', 'CAMPAIGN_TYPE_CONTENT_PROMOTION'),
        ('adgroup.buying_type', 'EQUALS', 'BUYINGTYPE_CONTRACT'),
    ],
}


def _filters(scope):
    return [
        {'field': field, 'operator': operator, 'values': [value]}
        for field, operator, value in FILTERS[scope]
    ]


def _contract(tmp_path, *, smart_exclusion=True):
    tmp_path.mkdir(parents=True, exist_ok=True)
    groups = {
        'bidding_queries': SCOPES[:3],
        'brand_queries': SCOPES[3:6],
        'additional_brand_queries': SCOPES[6:],
    }
    value = {
        'schema': 'tencent_promotion_scope_observed.v2',
        'account_id': '74749810',
        'confirmed_required': ['竞价推广', '品牌推广'],
        'confirmed_excluded': ['智能投放'],
        'window_observed': WINDOW,
        'new_scope_complete': False,
        'ordinary_browser_auth_copied': False,
        **{key: [] for key in groups},
    }
    for group, scopes in groups.items():
        for scope in scopes:
            path = (tencent.QUERY if scope in ('bidding_display', 'bidding_search_upgrade',
                                               'brand_touch_rtb_all_states')
                    else tencent.LEGACY_QUERY if scope == 'brand_content_boost_all_created_dates'
                    else '/bff/proxy/gdt-api/ad_manage/v1/dpmanage/get_integrated_list_upgrade')
            filtering = _filters(scope)
            if not smart_exclusion and scope == 'bidding_display':
                filtering = [item for item in filtering
                             if item['field'] != 'adgroup.smart_delivery_platform']
            fields = ['report.date', 'report.cost']
            if scope.startswith('bidding_') or scope in (
                    'brand_touch_rtb_all_states', 'brand_content_boost_all_created_dates'):
                fields.append('report.adgroup_id')
            elif scope in ('brand_touch_contract', 'brand_search_contract',
                           'brand_content_contract'):
                fields.append('campaign.campaign_id')
            body = {
                'account_id_list': [74749810], 'is_total': False,
                'page': 1, 'page_size': 20, 'time_line': 'REQUEST_TIME',
                'date_range': {'start_date': WINDOW[0], 'end_date': WINDOW[1]},
                'fields': fields, 'filtering': filtering,
            }
            if path == tencent.QUERY:
                body.update(level='ADGROUP', group_by=['date', 'adgroup_id'])
            else:
                body.update(order_by=[{'sort_field': 'report.default_order_by',
                                       'sort_type': 'ASCENDING'}],
                            breakdown=['ADGROUP_REPORT_BY_DATE_AND_ADGROUP'],
                            params=[{'field': 'report.adq_report', 'values': ['true']},
                                    {'field': 'report.use_unified_report', 'values': ['true']}])
            value[group].append({
                'scope': scope, 'path': path,
                'body': body,
            })
    path = tmp_path / 'contracts.json'
    path.write_text(json.dumps(value, ensure_ascii=False))
    return path, hashlib.sha256(path.read_bytes()).hexdigest(), value


def _row(day, cost, *, entity, group='adgroup', account=74749810):
    return {
        'report': {'date': day, 'cost': cost, 'account_id': account},
        group: {group + '_id': entity},
    }


def _native_files(tmp_path, display_daily, legacy_daily):
    paths = {}
    for scope, daily in (('display_plus', display_daily), ('legacy_search', legacy_daily)):
        path = tmp_path / f'{scope}.csv'
        rows = ['日期,曝光次数,点击次数,点击率,点击均价,花费']
        rows.extend(f'{day},0,0,0,0,{amount}' for day, amount in sorted(daily.items()))
        path.write_text('\n'.join(rows) + '\n')
        paths[scope] = path
    return paths


def _native_candidate_manifest(tmp_path, native_files):
    entries = []
    for scope, path in native_files.items():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        native = tencent.inspect_report(
            path, account_id='74749810', product_scope=scope,
            time_basis='播放口径', start_date=WINDOW[0], through_date=WINDOW[1],
        )
        proof = tmp_path / f'{scope}-state.json'
        proof.write_text(json.dumps({
            'phase': 'verified', 'account_id': '74749810',
            'product_scope': scope, 'window': WINDOW, 'file_sha256': digest,
            'native': {'rows': native['rows'], 'total': native['total']},
        }, ensure_ascii=False))
        entries.append({
            'source_id': f'tencent_{scope}', 'path': str(path.resolve()),
            'sha256': digest, 'kind': 'tencent_native_csv',
            'business_line': 'abroad', 'business_group': '留学整体',
            'platform': '腾讯广告', 'account_id': '74749810',
            'product_scope': scope, 'time_basis': '播放口径',
            'start_date': WINDOW[0], 'end_date': WINDOW[1],
            'capture_evidence': {
                'path': str(proof.resolve()),
                'sha256': hashlib.sha256(proof.read_bytes()).hexdigest(),
            },
        })
    scope_record = tmp_path / 'scope-confirmation.json'
    scope_record.write_text(json.dumps({
        'evidence_type': 'user_confirmed_business_scope',
        'account_id': '74749810',
        'confirmed_entrances': ['竞价－搜索投放', '竞价－展示投放'],
        'combine_rule': 'sum', 'exclude_costs_by_product': False,
        'technical_disjointness_proven': False,
    }, ensure_ascii=False))
    manifest = tmp_path / 'candidate-sources.json'
    manifest.write_text(json.dumps({
        'sources': entries,
        'business_scope_confirmation': {
            'account_id': '74749810',
            'product_scopes': ['display_plus', 'legacy_search'],
            'combine_rule': 'sum',
            'evidence': {
                'path': str(scope_record.resolve()),
                'sha256': hashlib.sha256(scope_record.read_bytes()).hexdigest(),
            },
        },
    }, ensure_ascii=False))
    return manifest


def _empty_response(body):
    return {
        'code': 0,
        'data': {'page_info': {
            'page': body['page'], 'page_size': body['page_size'],
            'total_number': 0, 'total_page': 0,
        }, 'list': []},
    }


def _fake_post(contract, rows_by_scope, calls):
    by_filter = {
        json.dumps(spec['body']['filtering'], sort_keys=True): spec['scope']
        for group in ('bidding_queries', 'brand_queries', 'additional_brand_queries')
        for spec in contract[group]
    }

    def post(path, body):
        scope = by_filter[json.dumps(body['filtering'], sort_keys=True)]
        calls.append((scope, path, body))
        values = rows_by_scope.get(scope, [])
        page_size = body['page_size']
        pages = (len(values) + page_size - 1) // page_size
        page_rows = values[(body['page'] - 1) * page_size:body['page'] * page_size]
        return {
            'code': 0,
            'data': {'page_info': {
                'page': body['page'], 'page_size': page_size,
                'total_number': len(values), 'total_page': pages,
            }, 'list': page_rows},
        }
    return post


def _run(tmp_path, contract_path, contract_hash, native_files, post):
    return tencent.verify_promotion_scope(
        tmp_path, contract_path=contract_path, contract_sha256=contract_hash,
        start=WINDOW[0], through=WINDOW[1], native_files=native_files,
        output_dir=tmp_path / 'capture', post=post,
    )


def test_promotion_scope_empty_brand_and_extra_branches_match_native_ledgers(tmp_path):
    contract_path, contract_hash, contract = _contract(tmp_path)
    rows = {
        'bidding_display': [_row(WINDOW[0], '10', entity='d1')],
        'bidding_search': [_row(WINDOW[0], '20', entity='s1')],
        'bidding_search_upgrade': [_row(WINDOW[0], '5', entity='u1')],
    }
    native = _native_files(tmp_path, {WINDOW[0]: '15'}, {WINDOW[0]: '20'})
    calls = []

    result = _run(tmp_path, contract_path, contract_hash, native,
                  _fake_post(contract, rows, calls))

    assert result['status'] == 'verified'
    assert len(calls) == len(SCOPES)
    assert result['daily_comparison']['v3']['query_total'] == '15'
    assert result['daily_comparison']['legacy']['query_total'] == '20'
    receipt = json.loads(Path(result['receipt']['path']).read_text())
    assert receipt['known_empty_scopes'] == SCOPES[3:]
    assert receipt['scope_summaries']['brand_touch_contract']['included_in_ledger'] is True
    assert receipt['scope_summaries']['brand_touch_contract']['native_product_scope'] == 'legacy_search'
    assert receipt['scope_summaries']['brand_touch_rtb_all_states']['native_product_scope'] == 'display_plus'
    assert receipt['scope_summaries']['brand_content_boost_all_created_dates']['native_product_scope'] == 'legacy_search'
    assert receipt['scope_summaries']['brand_content_contract']['included_in_ledger'] is False
    assert receipt['scope_summaries']['brand_content_contract']['nonempty_action'] == 'verified_subset_not_added'
    assert len(result['files']) == 9
    assert all(Path(item['path']).is_file() for item in result['files'])


def test_brand_content_is_verified_as_touch_subset_without_double_adding(tmp_path):
    contract_path, contract_hash, contract = _contract(tmp_path)
    rows = {
        'bidding_display': [_row(WINDOW[0], '10', entity='d1')],
        'bidding_search': [_row(WINDOW[0], '20', entity='s1')],
        'bidding_search_upgrade': [_row(WINDOW[0], '5', entity='u1')],
        'brand_touch_contract': [_row(WINDOW[0], '3', entity='b1', group='campaign')],
        'brand_search_contract': [_row(WINDOW[1], '7', entity='b2', group='campaign')],
        'brand_content_contract': [_row(WINDOW[0], '3', entity='b1', group='campaign')],
    }
    native = _native_files(
        tmp_path, {WINDOW[0]: '15'}, {WINDOW[0]: '23', WINDOW[1]: '7'},
    )
    result = _run(tmp_path, contract_path, contract_hash, native,
                  _fake_post(contract, rows, []))

    assert result['status'] == 'verified'
    assert result['daily_comparison']['legacy']['query_total'] == '30'
    assert result['daily_comparison']['legacy']['native_total'] == '30'
    receipt = json.loads(Path(result['receipt']['path']).read_text())
    assert receipt['scope_summaries']['brand_content_contract']['total'] == '3'
    assert receipt['scope_summaries']['brand_content_contract']['included_in_ledger'] is False
    assert receipt['scope_summaries']['brand_content_contract']['subset_of'] == 'brand_touch_contract'


def test_promotion_scope_native_daily_mismatch_blocks_with_export_required(tmp_path):
    contract_path, contract_hash, contract = _contract(tmp_path)
    rows = {
        'bidding_display': [_row(WINDOW[0], '10', entity='d1')],
        'bidding_search': [_row(WINDOW[0], '20', entity='s1')],
        'bidding_search_upgrade': [_row(WINDOW[0], '5', entity='u1')],
    }
    native = _native_files(tmp_path, {WINDOW[0]: '16'}, {WINDOW[0]: '20'})

    with pytest.raises(tencent.ExportBlocked, match='tencent_promotion_native_export_required'):
        _run(tmp_path, contract_path, contract_hash, native,
             _fake_post(contract, rows, []))

    receipt = json.loads((tmp_path / 'capture/promotion-scope-check.json').read_text())
    assert receipt['status'] == 'blocked'
    assert receipt['failure']['code'] == 'tencent_promotion_native_export_required'
    assert receipt['daily_comparison']['v3']['matches_exactly'] is False


def test_brand_subset_mismatch_blocks(tmp_path):
    contract_path, contract_hash, contract = _contract(tmp_path)
    rows = {
        'bidding_display': [_row(WINDOW[0], '10', entity='d1')],
        'bidding_search': [_row(WINDOW[0], '20', entity='s1')],
        'bidding_search_upgrade': [_row(WINDOW[0], '5', entity='u1')],
        'brand_touch_contract': [_row(WINDOW[0], '3', entity='b1', group='campaign')],
        'brand_content_contract': [_row(WINDOW[0], '4', entity='b1', group='campaign')],
    }
    native = _native_files(tmp_path, {WINDOW[0]: '15'}, {WINDOW[0]: '23'})
    with pytest.raises(tencent.ExportBlocked, match='tencent_promotion_brand_subset_mismatch'):
        _run(tmp_path, contract_path, contract_hash, native,
             _fake_post(contract, rows, []))


def test_nonempty_brand_branches_match_native_ledgers_and_parse_as_expense_rows(tmp_path):
    contract_path, contract_hash, contract = _contract(tmp_path)
    rows = {
        'bidding_display': [_row(WINDOW[0], '10', entity='display')],
        'bidding_search': [_row(WINDOW[0], '20', entity='search')],
        'bidding_search_upgrade': [_row(WINDOW[0], '5', entity='upgrade')],
        'brand_touch_contract': [_row(WINDOW[0], '3', entity='touch', group='campaign')],
        'brand_search_contract': [_row(WINDOW[1], '7', entity='brand-search', group='campaign')],
        'brand_content_contract': [_row(WINDOW[0], '3', entity='touch', group='campaign')],
        'brand_touch_rtb_all_states': [_row(WINDOW[0], '2', entity='rtb')],
        'brand_content_boost_all_created_dates': [_row(WINDOW[1], '4', entity='boost')],
    }
    native = _native_files(
        tmp_path, {WINDOW[0]: '17'},
        {WINDOW[0]: '23', WINDOW[1]: '11'},
    )

    result = _run(tmp_path, contract_path, contract_hash, native,
                  _fake_post(contract, rows, []))

    assert result['daily_comparison']['v3']['query_total'] == '17'
    assert result['daily_comparison']['legacy']['query_total'] == '34'
    receipt = json.loads(Path(result['receipt']['path']).read_text())
    summaries = receipt['scope_summaries']
    for scope, product_scope in (
            ('brand_touch_contract', 'legacy_search'),
            ('brand_search_contract', 'legacy_search'),
            ('brand_touch_rtb_all_states', 'display_plus'),
            ('brand_content_boost_all_created_dates', 'legacy_search')):
        assert summaries[scope]['row_count'] == 1
        assert summaries[scope]['native_product_scope'] == product_scope
        assert summaries[scope]['included_in_ledger'] is True
        assert summaries[scope]['nonempty_action'] == 'included_in_native_ledger'
    assert summaries['brand_content_contract']['row_count'] == 1
    assert summaries['brand_content_contract']['included_in_ledger'] is False
    assert summaries['brand_content_contract']['subset_of'] == 'brand_touch_contract'

    from dashboard_product.management.candidate_sources import load_candidate_sources
    parsed = load_candidate_sources(_native_candidate_manifest(tmp_path, native))
    amounts = {
        scope: sum(row['amount'] for row in parsed['rows']
                   if row['product_scope'] == scope)
        for scope in ('display_plus', 'legacy_search')
    }
    assert amounts == {'display_plus': 17.0, 'legacy_search': 34.0}
    assert len(parsed['rows']) == 3
    assert sum(amounts.values()) == 51.0


def test_additional_brand_branches_paginate_and_map_to_native_ledgers(tmp_path):
    contract_path, contract_hash, contract = _contract(tmp_path)
    rtb_rows = [_row(WINDOW[0], '1', entity=f'rtb-{index}') for index in range(21)]
    boost_rows = [_row(WINDOW[0], '1', entity=f'boost-{index}') for index in range(21)]
    rows = {
        'bidding_display': [_row(WINDOW[0], '10', entity='display')],
        'bidding_search': [_row(WINDOW[0], '20', entity='search')],
        'bidding_search_upgrade': [_row(WINDOW[0], '5', entity='upgrade')],
        'brand_touch_rtb_all_states': rtb_rows,
        'brand_content_boost_all_created_dates': boost_rows,
    }
    native = _native_files(tmp_path, {WINDOW[0]: '36'}, {WINDOW[0]: '41'})
    calls = []

    result = _run(tmp_path, contract_path, contract_hash, native,
                  _fake_post(contract, rows, calls))

    assert result['daily_comparison']['v3']['query_total'] == '36'
    assert result['daily_comparison']['legacy']['query_total'] == '41'
    for scope in ('brand_touch_rtb_all_states', 'brand_content_boost_all_created_dates'):
        assert [call[2]['page'] for call in calls if call[0] == scope] == [1, 2]
        assert result['scope_summaries'][scope]['included_in_ledger'] is True
    receipt = json.loads(Path(result['receipt']['path']).read_text())
    for scope in ('brand_touch_rtb_all_states', 'brand_content_boost_all_created_dates'):
        query = next(item for item in receipt['queries'] if item['scope'] == scope)
        assert [page['page_info']['total_number'] for page in query['pages']] == [21, 21]


def test_additional_brand_overlap_with_existing_adgroup_blocks(tmp_path):
    contract_path, contract_hash, contract = _contract(tmp_path)
    rows = {
        'bidding_display': [_row(WINDOW[0], '10', entity='shared-adgroup')],
        'bidding_search': [_row(WINDOW[0], '20', entity='search')],
        'bidding_search_upgrade': [_row(WINDOW[0], '5', entity='upgrade')],
        'brand_touch_rtb_all_states': [_row(WINDOW[0], '2', entity='shared-adgroup')],
    }
    native = _native_files(tmp_path, {WINDOW[0]: '17'}, {WINDOW[0]: '20'})

    with pytest.raises(tencent.ExportBlocked, match='tencent_promotion_duplicate_date_entity'):
        _run(tmp_path, contract_path, contract_hash, native,
             _fake_post(contract, rows, []))


def test_same_adgroup_date_across_native_ledgers_blocks(tmp_path):
    contract_path, contract_hash, contract = _contract(tmp_path)
    rows = {
        'bidding_display': [_row(WINDOW[0], '10', entity='shared-adgroup')],
        'bidding_search': [_row(WINDOW[0], '20', entity='shared-adgroup')],
        'bidding_search_upgrade': [_row(WINDOW[0], '5', entity='upgrade')],
    }
    native = _native_files(tmp_path, {WINDOW[0]: '15'}, {WINDOW[0]: '20'})

    with pytest.raises(tencent.ExportBlocked,
                       match='tencent_promotion_duplicate_date_entity'):
        _run(tmp_path, contract_path, contract_hash, native,
             _fake_post(contract, rows, []))


def test_same_id_on_different_dates_and_campaign_adgroup_namespaces_is_allowed(tmp_path):
    contract_path, contract_hash, contract = _contract(tmp_path)
    rows = {
        'bidding_display': [_row(WINDOW[0], '10', entity='shared')],
        'bidding_search': [_row(WINDOW[1], '20', entity='shared')],
        'bidding_search_upgrade': [_row(WINDOW[0], '5', entity='upgrade')],
        'brand_touch_contract': [_row(WINDOW[0], '3', entity='shared', group='campaign')],
    }
    native = _native_files(
        tmp_path, {WINDOW[0]: '15'}, {WINDOW[0]: '3', WINDOW[1]: '20'},
    )

    result = _run(tmp_path, contract_path, contract_hash, native,
                  _fake_post(contract, rows, []))

    assert result['daily_comparison']['v3']['matches_exactly'] is True
    assert result['daily_comparison']['legacy']['matches_exactly'] is True


def test_additional_brand_cost_mismatch_requires_native_reconciliation(tmp_path):
    contract_path, contract_hash, contract = _contract(tmp_path)
    rows = {
        'bidding_display': [_row(WINDOW[0], '10', entity='display')],
        'bidding_search': [_row(WINDOW[0], '20', entity='search')],
        'bidding_search_upgrade': [_row(WINDOW[0], '5', entity='upgrade')],
        'brand_touch_rtb_all_states': [_row(WINDOW[0], '2', entity='rtb')],
    }
    native = _native_files(tmp_path, {WINDOW[0]: '15'}, {WINDOW[0]: '20'})

    with pytest.raises(tencent.ExportBlocked, match='tencent_promotion_native_export_required'):
        _run(tmp_path, contract_path, contract_hash, native,
             _fake_post(contract, rows, []))

    receipt = json.loads((tmp_path / 'capture/promotion-scope-check.json').read_text())
    assert receipt['daily_comparison']['v3']['matches_exactly'] is False


@pytest.mark.parametrize('scope', [
    'brand_touch_rtb_all_states', 'brand_content_boost_all_created_dates',
])
def test_management_level_contract_cannot_be_used_as_daily_brand_cost(scope, tmp_path):
    contract_path, contract_hash, contract = _contract(tmp_path)
    group = 'additional_brand_queries'
    spec = next(item for item in contract[group] if item['scope'] == scope)
    spec['body']['fields'] = [field for field in spec['body']['fields']
                              if field not in {'report.date', 'report.adgroup_id'}]
    if scope == 'brand_touch_rtb_all_states':
        spec['body']['group_by'] = ['adgroup_id']
        spec['body']['filtering'].append({
            'field': 'adgroup.operation_status', 'operator': 'IN',
            'values': ['CALCULATE_STATUS_DELETED'],
        })
    else:
        spec['path'] = tencent.LEGACY_QUERY
        spec['body']['breakdown'] = ['ADGROUP']
    contract_path.write_text(json.dumps(contract, ensure_ascii=False))
    contract_hash = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    native = _native_files(tmp_path, {WINDOW[0]: '1'}, {WINDOW[0]: '1'})
    calls = []
    post = _fake_post(contract, {}, calls)

    with pytest.raises(tencent.ExportBlocked,
                       match='tencent_promotion_contract_report_grain_mismatch'):
        _run(tmp_path, contract_path, contract_hash, native, post)
    assert all(call[0] != scope for call in calls)


def test_promotion_scope_paginates_stably_and_keeps_smart_exclusion_contract(tmp_path):
    contract_path, contract_hash, contract = _contract(tmp_path)
    display_rows = [_row(WINDOW[0], '1', entity=f'd{i}') for i in range(21)]
    rows = {
        'bidding_display': display_rows,
        'bidding_search': [_row(WINDOW[0], '20', entity='s1')],
        'bidding_search_upgrade': [_row(WINDOW[0], '5', entity='u1')],
    }
    native = _native_files(tmp_path, {WINDOW[0]: '26'}, {WINDOW[0]: '20'})
    calls = []
    result = _run(tmp_path, contract_path, contract_hash, native,
                  _fake_post(contract, rows, calls))

    assert result['status'] == 'verified'
    assert [call[2]['page'] for call in calls[:2]] == [1, 2]
    receipt = json.loads(Path(result['receipt']['path']).read_text())
    display = next(item for item in receipt['queries'] if item['scope'] == 'bidding_display')
    assert [page['page_info']['total_number'] for page in display['pages']] == [21, 21]
    assert any(item['field'] == 'adgroup.smart_delivery_platform'
               and item['operator'] == 'LESS'
               for item in contract['bidding_queries'][0]['body']['filtering'])

    bad_path, bad_hash, _ = _contract(tmp_path / 'without-smart-exclusion', smart_exclusion=False)
    post = lambda *_args: pytest.fail('query must not run without smart exclusion')
    with pytest.raises(tencent.ExportBlocked, match='tencent_promotion_smart_exclusion_missing'):
        tencent.verify_promotion_scope(
            tmp_path, contract_path=bad_path, contract_sha256=bad_hash,
            start=WINDOW[0], through=WINDOW[1], native_files=native,
            output_dir=tmp_path / 'bad-contract', post=post,
        )


@pytest.mark.parametrize(
    'bad_row, reason', [
        (_row(WINDOW[0], '4', entity='a1', account=42), 'tencent_promotion_query_account_mismatch'),
        (_row('2026-11-03', '4', entity='a1'), 'tencent_promotion_query_date_or_cost_invalid'),
        (_row(WINDOW[0], '', entity='a1'), 'tencent_promotion_query_date_or_cost_invalid'),
    ],
)
def test_promotion_scope_rejects_bad_rows_before_native_comparison(tmp_path, bad_row, reason):
    contract_path, contract_hash, contract = _contract(tmp_path)
    rows = {
        'bidding_display': [bad_row],
        'bidding_search': [_row(WINDOW[0], '20', entity='s1')],
        'bidding_search_upgrade': [_row(WINDOW[0], '5', entity='u1')],
    }
    native = _native_files(tmp_path, {WINDOW[0]: '5'}, {WINDOW[0]: '20'})
    with pytest.raises(tencent.ExportBlocked, match=reason):
        _run(tmp_path, contract_path, contract_hash, native,
             _fake_post(contract, rows, []))


def test_promotion_scope_404_is_not_treated_as_empty(tmp_path):
    contract_path, contract_hash, _ = _contract(tmp_path)
    native = _native_files(tmp_path, {WINDOW[0]: '1'}, {WINDOW[0]: '1'})
    post = lambda *_args: (_ for _ in ()).throw(tencent.ExportBlocked('tencent_http_404'))
    with pytest.raises(tencent.ExportBlocked, match='tencent_http_404'):
        _run(tmp_path, contract_path, contract_hash, native, post)
    receipt = json.loads((tmp_path / 'capture/promotion-scope-check.json').read_text())
    assert receipt['status'] == 'blocked'
    assert receipt['failure']['error_type'] == 'ExportBlocked'


def test_exact_4501_response_requests_one_login_recovery(tmp_path):
    contract_path, contract_hash, _ = _contract(tmp_path)
    native = _native_files(tmp_path, {WINDOW[0]: '1'}, {WINDOW[0]: '1'})
    post = lambda *_args: {'code': 4501, 'ret': 4501, 'data': {'page_info': {}, 'list': []}}
    with pytest.raises(tencent.TencentLoginRequired):
        _run(tmp_path, contract_path, contract_hash, native, post)
    receipt = json.loads((tmp_path / 'capture/promotion-scope-check.json').read_text())
    assert receipt['status'] == 'blocked'
    assert receipt['failure']['error_type'] == 'TencentLoginRequired'


def test_promotion_contract_hash_and_window_are_explicit(tmp_path):
    contract_path, contract_hash, _ = _contract(tmp_path)
    native = _native_files(tmp_path, {WINDOW[0]: '1'}, {WINDOW[0]: '1'})
    post = lambda *_args: pytest.fail('query must not run for invalid contract/window')
    with pytest.raises(tencent.ExportBlocked, match='tencent_promotion_contract_sha256_mismatch'):
        tencent.verify_promotion_scope(
            tmp_path, contract_path=contract_path, contract_sha256='0' * 64,
            start=WINDOW[0], through=WINDOW[1], native_files=native,
            output_dir=tmp_path / 'bad-hash', post=post,
        )
    with pytest.raises(tencent.ExportBlocked, match='tencent_promotion_window_invalid'):
        tencent.verify_promotion_scope(
            tmp_path, contract_path=contract_path, contract_sha256=contract_hash,
            start='2026-11-03', through='2026-09-01', native_files=native,
            output_dir=tmp_path / 'bad-window', post=post,
        )


def test_v1_promotion_contract_is_not_accepted(tmp_path):
    contract_path, contract_hash, contract = _contract(tmp_path)
    contract['schema'] = 'tencent_promotion_scope_observed.v1'
    contract_path.write_text(json.dumps(contract, ensure_ascii=False))
    contract_hash = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    native = _native_files(tmp_path, {WINDOW[0]: '1'}, {WINDOW[0]: '1'})
    post = lambda *_args: pytest.fail('v1 contract must fail before query')

    with pytest.raises(tencent.ExportBlocked,
                       match='tencent_promotion_contract_scope_mismatch'):
        _run(tmp_path, contract_path, contract_hash, native, post)


def test_brand_proxy_uses_private_legacy_auth_without_mp_token_and_no_redirect_tls(tmp_path, monkeypatch):
    auth = {
        'account_id': '74749810',
        'queries': {'legacy_search': {
            'path': tencent.LEGACY_QUERY,
            'headers': {
                'mp-tk': 'remove-header', 'Cookie': 'remove-cookie',
                'x-tsa-client-authentication': 'keep-dedicated-header',
            },
            'query': {'mp_tk': 'not-sent', 'g_tk': 'not-sent'},
        }},
    }
    monkeypatch.setattr(tencent, 'private_json', lambda _path: auth)
    client = tencent.TencentExport(tmp_path)
    client._cookie = lambda _path: 'sid=dedicated-session'
    handlers_seen, request_seen = [], []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def read(self, _limit): return b'{"code":0}'

    class Opener:
        def open(self, request, timeout):
            request_seen.append((request, timeout))
            return Response()

    monkeypatch.setattr(tencent.ssl, 'create_default_context', lambda **kwargs: 'tls-context')
    monkeypatch.setattr(tencent.certifi, 'where', lambda: 'verified-ca.pem')
    monkeypatch.setattr(tencent, 'build_opener', lambda *handlers: (handlers_seen.extend(handlers) or Opener()))

    assert tencent._brand_proxy_post(client,
        '/bff/proxy/gdt-api/ad_manage/v1/dpmanage/get_integrated_list_upgrade',
        {'account_id_list': [74749810]}) == {'code': 0}
    request, timeout = request_seen[0]
    assert timeout == client.request_timeout
    assert request.get_method() == 'POST'
    assert parse_qs(urlsplit(request.full_url).query) == {}
    assert 'mp-tk' not in {name.lower() for name, _value in request.header_items()}
    assert request.get_header('Cookie') == 'sid=dedicated-session'
    assert isinstance(handlers_seen[0], tencent.NoRedirect)
    assert isinstance(handlers_seen[1], tencent.HTTPSHandler)
    assert handlers_seen[1]._context == 'tls-context'


def test_brand_proxy_404_is_a_fixed_blocker(tmp_path, monkeypatch):
    auth = {
        'account_id': '74749810',
        'queries': {'legacy_search': {'path': tencent.LEGACY_QUERY, 'headers': {}, 'query': {}}},
    }
    monkeypatch.setattr(tencent, 'private_json', lambda _path: auth)
    client = tencent.TencentExport(tmp_path)
    client._cookie = lambda _path: 'sid=dedicated-session'

    class Opener:
        def open(self, request, timeout):
            raise HTTPError(request.full_url, 404, 'Not Found', None, None)

    monkeypatch.setattr(tencent.ssl, 'create_default_context', lambda **kwargs: object())
    monkeypatch.setattr(tencent.certifi, 'where', lambda: 'verified-ca.pem')
    monkeypatch.setattr(tencent, 'build_opener', lambda *_handlers: Opener())
    with pytest.raises(tencent.ExportBlocked, match='tencent_http_404'):
        tencent._brand_proxy_post(client,
            '/bff/proxy/gdt-api/ad_manage/v1/dpmanage/get_integrated_list_upgrade',
            {'account_id_list': [74749810]})
