import hashlib
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from data_acquisition.auth.auth_sessions import AuthSessionExpiredError
from dashboard_product.shadow_bi.p5.full_daily import DailyBlocked
from data_acquisition.jobs import prepare_full_daily
from data_acquisition.jobs.business_first_daily import run as run_business_first


DAY = '2026-11-03'
NOW = datetime(2026, 11, 3, 10, 15, tzinfo=ZoneInfo('Asia/Shanghai'))
PAIR = {
    'sources': {
        'bi': {'snapshot_id': 'snapshot-bi', 'run_id': 'run-bi'},
        'study_abroad': {'snapshot_id': 'snapshot-study', 'run_id': 'run-study'},
    },
}


def _workspace(tmp_path, *, scope_review):
    workspace = tmp_path / 'workspace'
    private = workspace / '.private'
    private.mkdir(parents=True)
    tencent = {'start_date': '2026-09-01'}
    if scope_review is not None:
        tencent['scope_review'] = scope_review
    (private / 'full-daily-sources.json').write_text(json.dumps({
        'expected_sources': {
            'xhs': {'start_date': '2026-09-01'},
            'ocean': {'start_date': '2026-09-01'},
            'tencent_ads_abroad': tencent,
            'sem': {'start_date': '2026-09-01'},
        },
    }))
    return workspace


def _bundle(folder, source_id):
    folder.mkdir(parents=True, exist_ok=True)
    manifest = folder / 'candidate-sources.json'
    capture = folder / 'capture.json'
    manifest.write_text(json.dumps({'sources': [{'source_id': source_id}]}))
    capture.write_text(json.dumps({'sources': [{'source_id': source_id}]}))
    return {'manifest': manifest, 'capture': capture}


def _stub_non_tencent_sources(monkeypatch, batch):
    monkeypatch.setattr(prepare_full_daily, 'XHSExport', lambda **_kwargs: object())
    monkeypatch.setattr(prepare_full_daily, 'run_xhs_authenticated', lambda *_args, **_kwargs: {
        'started_at': f'{DAY}T09:00:00+08:00', 'expected_accounts': [],
        'native': {'excluded_account_ids': []},
    })
    monkeypatch.setattr(prepare_full_daily, 'xhs_candidate',
                        lambda folder, *_args, **_kwargs: _bundle(folder, 'xhs'))
    monkeypatch.setattr(prepare_full_daily, 'OceanExport', lambda *_args, **_kwargs: object())
    monkeypatch.setattr(prepare_full_daily, 'ACCOUNTS', [])
    monkeypatch.setattr(prepare_full_daily, 'ocean_candidate',
                        lambda folder, *_args, **_kwargs: _bundle(folder, 'ocean'))
    monkeypatch.setattr(prepare_full_daily, '_tencent_scope_confirmation',
                        lambda _path=None: {'evidence': {'path': 'unused', 'sha256': 'unused'}})
    monkeypatch.setattr(prepare_full_daily, 'validate_candidate_authorities', lambda _manifest: {})
    contracts = batch.parent / 'contracts'
    (contracts / 'xhs-network-sample').mkdir(parents=True)
    (contracts / 'xhs-network-sample/network-contract.json').write_text('{}')
    (contracts / 'tencent-network-sample').mkdir(parents=True)
    (contracts / 'tencent-network-sample/legacy-network-contract.json').write_text('{}')
    (contracts / 'tencent-network-sample/dedicated-network-contract.json').write_text('{}')
    xhs_scope = batch.parent / 'xhs-scope.json'
    xhs_scope.write_text('{}')
    return contracts, xhs_scope


def test_pending_promotion_scope_skips_old_tencent_exports_and_blocks_collection(tmp_path, monkeypatch):
    batch = tmp_path / 'batch'
    workspace = _workspace(tmp_path, scope_review={
        'required': ['一级竞价推广', '品牌推广'],
        'excluded': ['智能投放'],
        'status': 'pending',
        'evidence': '.local/audits/bi-orders-full-rebuild-20261103/tencent-manual-export-and-scope-investigation.json',
    })
    contracts, xhs_scope = _stub_non_tencent_sources(monkeypatch, batch)
    tencent_export = Mock(side_effect=AssertionError('must not instantiate Tencent exporter'))
    tencent_run = Mock(side_effect=AssertionError('must not run old Tencent export'))
    monkeypatch.setattr(prepare_full_daily, 'TencentExport', tencent_export)
    monkeypatch.setattr(prepare_full_daily, 'run_tencent_authenticated', tencent_run)

    collect = prepare_full_daily.collector(batch, contracts, xhs_scope)
    with pytest.raises(DailyBlocked, match='collection_incomplete:see_collection_report'):
        collect(workspace, DAY, 'run-test', tmp_path / 'capture')

    report = json.loads((batch / 'collection-report.json').read_text())
    assert report['sources']['tencent_ads_abroad'] == {
        'status': 'blocked', 'reason': 'promotion_scope_unverified',
    }
    assert 'tencent_ads_abroad:promotion_scope_unverified' in report['blockers']
    assert 'tencent_ads_abroad:source_scope_incomplete' not in report['blockers']
    assert report['sources']['xhs']['status'] == 'verified'
    assert report['sources']['ocean']['status'] == 'verified'
    tencent_export.assert_not_called()
    tencent_run.assert_not_called()


def test_missing_scope_review_keeps_original_tencent_collection_path(tmp_path, monkeypatch):
    batch = tmp_path / 'batch'
    workspace = _workspace(tmp_path, scope_review=None)
    contracts, xhs_scope = _stub_non_tencent_sources(monkeypatch, batch)
    tencent_export = Mock(return_value=object())
    tencent_run = Mock(side_effect=RuntimeError('offline test stub'))
    monkeypatch.setattr(prepare_full_daily, 'TencentExport', tencent_export)
    monkeypatch.setattr(prepare_full_daily, 'run_tencent_authenticated', tencent_run)

    collect = prepare_full_daily.collector(batch, contracts, xhs_scope)
    with pytest.raises(DailyBlocked, match='collection_incomplete:see_collection_report'):
        collect(workspace, DAY, 'run-test', tmp_path / 'capture')

    report = json.loads((batch / 'collection-report.json').read_text())
    assert 'tencent_ads_abroad:promotion_scope_unverified' not in report['blockers']
    assert tencent_export.call_count == 2
    assert tencent_run.call_count == 2


def test_tencent_scope_blocker_stops_expenses_without_rolling_back_base_or_notification(tmp_path):
    notify = Mock(return_value={
        'status': 'sent', 'release_id': 'business-release', 'as_of_date': DAY,
        'message_count': 8, 'message_status_counts': {'sent': 8},
    })
    business = Mock(return_value={
        'status': 'published', 'day': DAY, 'release': 'business-release', 'sources': PAIR,
    })
    expenses = Mock(side_effect=lambda _ws, _day, *, collect, **_kwargs:
                    collect(_ws, _day, 'expense-run', tmp_path / 'capture'))
    collect = Mock(side_effect=DailyBlocked('collection_incomplete:see_collection_report'))

    result = run_business_first(
        tmp_path / 'workspace', batch_dir=tmp_path / 'batch', collect=collect,
        day=DAY, now=NOW, publish_business=business, publish_expenses=expenses,
        notify=notify, assert_ready=Mock(return_value=PAIR),
    )

    assert result['status'] == 'partial'
    assert result['published'] is True
    assert result['business']['status'] == 'published'
    assert result['notification']['status'] == 'sent'
    assert result['expenses']['error_type'] == 'DailyBlocked'
    assert result['expenses']['reason'] == 'collection_incomplete:see_collection_report'
    business.assert_called_once()
    notify.assert_called_once()
    expenses.assert_called_once()


def test_promotion_scope_auth_expiry_saves_once_and_retries_same_verification(tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'
    kwargs = {
        'contract_path': tmp_path / 'contracts.json', 'contract_sha256': 'fixed-hash',
        'start': '2026-09-01', 'through': '2026-11-02',
        'native_files': {'display_plus': tmp_path / 'display.csv',
                         'legacy_search': tmp_path / 'legacy.csv'},
        'output_dir': tmp_path / 'same-output',
    }
    calls = []
    verification = {'status': 'verified'}

    def verify(ws, **actual_kwargs):
        calls.append((ws, actual_kwargs))
        if len(calls) == 1:
            raise AuthSessionExpiredError('tencent_http_401')
        return verification

    login = Mock()
    monkeypatch.setattr(prepare_full_daily, 'verify_promotion_scope', verify)
    monkeypatch.setattr(prepare_full_daily, 'save_tencent_login', login)

    assert prepare_full_daily._verify_promotion_scope_with_login(workspace, **kwargs) is verification
    assert len(calls) == 2
    assert calls[0] == calls[1] == (workspace, kwargs)
    login.assert_called_once_with(workspace)

    login.reset_mock()
    monkeypatch.setattr(
        prepare_full_daily, 'verify_promotion_scope',
        Mock(side_effect=DailyBlocked('tencent_promotion_native_export_required')),
    )
    with pytest.raises(DailyBlocked, match='tencent_promotion_native_export_required'):
        prepare_full_daily._verify_promotion_scope_with_login(workspace, **kwargs)
    login.assert_not_called()


@pytest.mark.parametrize('brand_nonempty', [False, True])
def test_observed_contract_collector_includes_promotion_receipt_and_query_hashes(
        tmp_path, monkeypatch, brand_nonempty):
    batch = tmp_path / 'batch'
    capture_dir = tmp_path / 'capture'
    contract_path = (tmp_path / 'promotion-contracts.json').resolve()
    contract_path.write_text('{}')
    contract_hash = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    workspace = _workspace(tmp_path, scope_review={
        'required': ['一级竞价推广', '品牌推广'], 'excluded': ['智能投放'],
        'status': 'observed_contract', 'contract_path': str(contract_path),
        'contract_sha256': contract_hash,
    })
    contracts, xhs_scope = _stub_non_tencent_sources(monkeypatch, batch)
    monkeypatch.setattr(
        prepare_full_daily, 'tencent_window_status',
        lambda *_args, **_kwargs: {
            'export_window_verified': True, 'native_dates_complete': True,
            'unreported_dates': [], 'sparse_display_accepted': False,
        },
    )

    def tencent_capture(_client, *, folder, contract, start, through):
        folder.mkdir(parents=True, exist_ok=True)
        scope = 'legacy_search' if folder.name == 'tencent_search' else 'display_plus'
        native = folder / 'native.csv'
        native.write_text('日期,曝光次数,点击次数,点击率,点击均价,花费\n2026-11-02,0,0,0,0,1.00\n')
        proof = folder / 'state.json'
        proof.write_text('{}')
        inventory = folder / 'raw_inventory.json'
        inventory.write_text(json.dumps({'captures': [{
            'product_scope': scope, 'selected_window': [start, through],
            'account_ids': ['74749810'],
            'sha256': hashlib.sha256(native.read_bytes()).hexdigest(),
            'captured_at': f'{DAY}T09:00:00+08:00',
        }]}))
        return {'task_id': 123, 'phase': 'verified', 'product_scope': scope,
                'window': [start, through], 'file_sha256': hashlib.sha256(native.read_bytes()).hexdigest()}

    monkeypatch.setattr(prepare_full_daily, 'run_tencent_authenticated', tencent_capture)
    output_dir = capture_dir / 'tencent-promotion-scope'
    query_file = output_dir / 'queries/bidding_display-page-001.json'
    receipt_file = output_dir / 'promotion-scope-check.json'

    def verify(_workspace, **kwargs):
        assert kwargs['contract_path'] == contract_path
        assert kwargs['contract_sha256'] == contract_hash
        assert kwargs['start'] == '2026-09-01' and kwargs['through'] == '2026-11-02'
        assert set(kwargs['native_files']) == {'display_plus', 'legacy_search'}
        assert kwargs['output_dir'] == output_dir
        query_file.parent.mkdir(parents=True, exist_ok=True)
        query_file.write_text('{}')
        receipt_file.write_text('{}')
        query_spec = {'path': str(query_file), 'sha256': hashlib.sha256(query_file.read_bytes()).hexdigest()}
        receipt_spec = {'path': str(receipt_file), 'sha256': hashlib.sha256(receipt_file.read_bytes()).hexdigest()}
        summaries = {'bidding_display': {'row_count': 1}}
        if brand_nonempty:
            summaries.update({
                'brand_touch_contract': {'row_count': 2, 'total': '0.40'},
                'brand_touch_rtb_all_states': {'row_count': 1, 'total': '0.30'},
                'brand_content_boost_all_created_dates': {'row_count': 1, 'total': '0.60'},
            })
        return {
            'status': 'verified', 'receipt': receipt_spec,
            'files': [query_spec, receipt_spec],
            'scope_summaries': summaries,
            'daily_comparison': {'v3': {'matches_exactly': True}, 'legacy': {'matches_exactly': True}},
        }

    verify_mock = Mock(side_effect=verify)
    monkeypatch.setattr(prepare_full_daily, 'verify_promotion_scope', verify_mock)
    sem_manifest = tmp_path / 'sem-manifest.json'
    sem_manifest.write_text(json.dumps({'sources': [{'source_id': 'sem'}]}))
    sem_source = {
        'source_id': 'sem', 'status': 'success', 'start_date': '2026-09-01',
        'through_date': '2026-11-02', 'account_ids': [],
        'completion': {'complete': True, 'through_date': '2026-11-02'},
    }
    sem_receipt = tmp_path / 'sem-receipt.json'
    sem_receipt.write_text(json.dumps({
        'manifest_path': str(sem_manifest), 'sources': [sem_source],
    }))
    monkeypatch.setattr(prepare_full_daily, 'resolve_sem_receipt', lambda **_kwargs: sem_receipt)
    from data_acquisition.connectors.advertising import sem_candidate
    monkeypatch.setattr(sem_candidate, 'load_sem_bundle', lambda _receipt: (
        [{'source_id': 'sem'}], [sem_source],
    ))
    staged = {}

    def receipt_collector(bundle_path):
        def stage(*_args):
            staged['bundle'] = json.loads(Path(bundle_path).read_text())
            return {'status': 'staged'}
        return stage

    monkeypatch.setattr(prepare_full_daily, 'receipt_collector', receipt_collector)
    collect = prepare_full_daily.collector(batch, contracts, xhs_scope, sem_receipt=sem_receipt)

    assert collect(workspace, DAY, 'run-test', capture_dir) == {'status': 'staged'}
    verify_mock.assert_called_once()
    tencent_source = next(s for s in staged['bundle']['sources'] if s['source_id'] == 'tencent_ads_abroad')
    staged_files = {item['path']: item['sha256'] for item in tencent_source['files']}
    assert str(query_file) in staged_files
    assert str(receipt_file) in staged_files
    evidence = json.loads((batch / 'tencent-abroad-capture-evidence.json').read_text())
    assert evidence['promotion_scope']['status'] == 'verified'
    assert evidence['promotion_scope']['receipt']['sha256'] == staged_files[str(receipt_file)]
    if brand_nonempty:
        assert evidence['promotion_scope']['scope_summaries'][
            'brand_touch_rtb_all_states']['row_count'] == 1
        assert evidence['promotion_scope']['scope_summaries'][
            'brand_content_boost_all_created_dates']['row_count'] == 1
    manifest = json.loads((batch / 'candidate-sources.json').read_text())
    native_entries = [entry for entry in manifest['sources']
                      if entry.get('kind') == 'tencent_native_csv']
    assert len(native_entries) == 2  # Brand costs stay in their native account ledger once.
    assert {entry['product_scope'] for entry in native_entries} == {'display_plus', 'legacy_search'}
    report = json.loads((batch / 'collection-report.json').read_text())
    assert report['sources']['tencent_ads_abroad']['promotion_scope_verified'] is True
