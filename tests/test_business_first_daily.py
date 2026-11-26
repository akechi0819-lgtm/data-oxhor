import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from dashboard_product.shadow_bi.p5 import daily as daily_runner
from data_acquisition.ops_io import DailyBlocked
from ops.business import run


DAY = '2026-10-30'
NOW = datetime(2026, 10, 30, 10, 15, tzinfo=ZoneInfo('Asia/Shanghai'))
PAIR = {
    'sources': {
        'bi': {'snapshot_id': 'snapshot-bi', 'run_id': 'run-bi'},
        'study_abroad': {'snapshot_id': 'snapshot-study', 'run_id': 'run-study'},
    },
}


def sent(release):
    return {
        'status': 'sent', 'release_id': release, 'as_of_date': DAY,
        'message_count': 8, 'message_status_counts': {'sent': 8},
    }


def args(tmp_path, **overrides):
    result = {
        'workspace': tmp_path / 'workspace',
        'batch_dir': tmp_path / 'batch',
        'day': DAY,
        'now': NOW,
        'assert_ready': Mock(return_value=PAIR),
    }
    result.update(overrides)
    return result


def business_inputs_manifest(tmp_path, *, as_of_date=DAY, bi_start_date='2025-03-01'):
    files = {}
    for name in ('orders', 'cash', 'tencent'):
        path = (tmp_path / f'{name}.xlsx').resolve()
        path.write_bytes(name.encode())
        files[name] = {
            'path': str(path),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    manifest = {'as_of_date': as_of_date, 'bi_start_date': bi_start_date, **files}
    manifest_path = tmp_path / 'inputs.json'
    manifest_path.write_text(json.dumps(manifest))
    return manifest_path, manifest


def test_business_failure_never_notifies(tmp_path):
    notify = Mock()
    result = run(**args(
        tmp_path,
        publish_business=Mock(side_effect=DailyBlocked('business_pair_missing')),
        notify=notify,
    ))

    assert result['status'] == 'blocked'
    assert result['published'] is False
    notify.assert_not_called()
    assert json.loads((tmp_path / 'batch/business-sources.json').read_text()) == {'sources': []}
    assert json.loads((tmp_path / 'batch/pipeline-result.json').read_text()) == result


def test_refresh_business_forces_only_new_pipeline_initial_publish(tmp_path):
    business_calls = []
    current_release = ['business-release']
    notices = Mock(side_effect=[
        {'status': 'unknown'},
        sent('business-release'),
    ])

    def publish_business(ws, day, **kwargs):
        business_calls.append(kwargs)
        return {'status': 'published', 'day': day, 'release': current_release[0],
                'sources': PAIR}

    common = args(
        tmp_path,
        refresh_business=True,
        publish_business=publish_business,
        notify=notices,
    )

    first = run(**common)
    second = run(**common)
    third = run(**common)

    assert first['status'] == 'partial'
    assert second['status'] == 'complete'
    assert third == second
    assert [call.get('force_refresh') for call in business_calls] == [True, None, None]
    assert all(call['advertising_manifest'].name == 'business-sources.json'
               for call in business_calls)
    assert notices.call_count == 2


@pytest.mark.parametrize(('change', 'reason'), [
    ('sha256', 'business_inputs_sha256_mismatch'),
    ('date', 'business_inputs_as_of_date_mismatch'),
    ('start_after_as_of', 'business_inputs_start_date_after_as_of'),
    ('relative', 'business_inputs_path_must_be_absolute'),
])
def test_business_inputs_reject_invalid_hash_date_and_relative_path(tmp_path, change, reason):
    manifest_path, manifest = business_inputs_manifest(tmp_path)
    if change == 'sha256':
        manifest['orders']['sha256'] = '0' * 64
    elif change == 'date':
        manifest['as_of_date'] = '2026-10-29'
    elif change == 'start_after_as_of':
        manifest['bi_start_date'] = '2026-10-31'
    else:
        manifest['orders']['path'] = 'orders.xlsx'
    manifest_path.write_text(json.dumps(manifest))
    publish_business = Mock()

    result = run(**args(
        tmp_path,
        refresh_business=True,
        business_inputs=manifest_path,
        publish_business=publish_business,
        notify=Mock(),
    ))

    assert result['status'] == 'blocked'
    assert result['business']['reason'] == reason
    publish_business.assert_not_called()
    assert not (tmp_path / 'batch/business-inputs.json').exists()


def test_business_inputs_are_copied_and_used_only_for_new_pipeline_publish(tmp_path):
    manifest_path, manifest = business_inputs_manifest(tmp_path)
    business_calls = []
    current_release = ['business-release']
    notices = Mock(side_effect=[{'status': 'unknown'}, sent('business-release')])

    def publish_business(ws, day, **kwargs):
        business_calls.append(kwargs)
        return {'status': 'published', 'day': day, 'release': current_release[0],
                'sources': PAIR}

    common = args(
        tmp_path,
        refresh_business=True,
        business_inputs=manifest_path,
        publish_business=publish_business,
        notify=notices,
    )

    first = run(**common)
    assert first['status'] == 'partial'
    assert (tmp_path / 'batch/business-inputs.json').read_bytes() == manifest_path.read_bytes()
    assert business_calls[0]['input_paths'] == {
        name: Path(spec['path']) for name, spec in manifest.items()
        if name in {'orders', 'cash', 'tencent'}
    }
    assert business_calls[0]['bi_start_date'] == '2025-03-01'
    assert business_calls[0]['force_refresh'] is True

    for name in ('orders', 'cash', 'tencent'):
        Path(manifest[name]['path']).unlink()
    second = run(**common)
    third = run(**common)

    assert second['status'] == 'complete'
    assert third == second
    assert [call.get('force_refresh') for call in business_calls] == [True, None, None]
    assert all('input_paths' not in call and 'bi_start_date' not in call
               for call in business_calls[1:])
    assert notices.call_count == 2


def test_daily_default_reuses_same_day_success_receipt(tmp_path, monkeypatch):
    from data_acquisition.jobs import daily_warehouses
    from dashboard_product.shadow_bi.p5 import sql_daily

    day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    workspace = tmp_path / 'workspace'
    state = workspace / 'Output/ShadowDaily'
    state.mkdir(parents=True)
    receipt = {'status': 'published', 'day': day, 'release': 'daily-sql-existing'}
    (state / f'{day}.json').write_text(json.dumps(receipt))
    refresh = Mock()
    monkeypatch.setattr(daily_warehouses, 'refresh_daily', refresh)
    monkeypatch.setattr(daily_runner, 'ssh_config', lambda private: (['ssh'], {}))
    monkeypatch.setattr(sql_daily, 'verify_current_pointer',
                        lambda **kwargs: ({'release': 'daily-sql-existing'}, {}, {},
                                          Path('/unused'), {}, 'a' * 64))

    result = daily_runner.run(workspace, day)

    assert result == receipt
    refresh.assert_not_called()


def test_daily_force_refresh_runs_full_business_refresh_despite_same_day_receipt(
        tmp_path, monkeypatch):
    from data_acquisition.jobs import daily_warehouses
    from dashboard_product.shadow_bi.p5 import sql_daily

    day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    workspace = tmp_path / 'workspace'
    state = workspace / 'Output/ShadowDaily'
    state.mkdir(parents=True)
    (state / f'{day}.json').write_text(json.dumps({
        'status': 'published', 'day': day, 'release': 'daily-existing',
    }))
    pair = {
        'run_id': 'run_shadow_daily_' + day.replace('-', '') + '_feesfixture',
        'sources': {
            'bi': {'snapshot_id': 'snapshot_bi_fixture', 'run_id': 'run-bi'},
            'study_abroad': {'snapshot_id': 'snapshot_study_fixture', 'run_id': 'run-study'},
        },
    }
    refresh = Mock(return_value={'status': 'passed'})
    def publish(**kwargs):
        return {'status': 'published', 'day': day, 'release': kwargs['release_id'],
                'batch_id': kwargs['run_id'], 'sources': kwargs['pair']}
    publish = Mock(side_effect=publish)
    monkeypatch.setattr(daily_warehouses, 'refresh_daily', refresh)
    monkeypatch.setattr(daily_warehouses, 'assert_daily_ready', Mock(return_value=pair))
    monkeypatch.setattr(daily_runner, 'ssh_config', lambda private: (['ssh'], {}))
    monkeypatch.setattr(sql_daily, 'verify_current_pointer',
                        lambda **kwargs: ({'release': 'daily-sql-existing'}, {}, {},
                                          Path('/unused'), {}, 'a' * 64))
    monkeypatch.setattr(sql_daily, 'publish', publish)

    result = daily_runner.run(workspace, day, force_refresh=True)

    assert result['status'] == 'published'
    assert result['release'].startswith('daily-sql-')
    refresh.assert_called_once()
    publish.assert_called_once()
    assert (state / 'current.json').exists()


def test_daily_passes_explicit_business_inputs_to_existing_refresh(tmp_path, monkeypatch):
    from data_acquisition.jobs import daily_warehouses
    from dashboard_product.shadow_bi.p5 import sql_daily

    day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    workspace = tmp_path / 'workspace'
    state = workspace / 'Output/ShadowDaily'
    state.mkdir(parents=True)
    (state / f'{day}.json').write_text(json.dumps({
        'status': 'published', 'day': day, 'release': 'daily-existing',
    }))
    input_paths = {name: tmp_path / f'{name}.xlsx' for name in ('orders', 'cash', 'tencent')}
    for path in input_paths.values():
        path.write_bytes(b'input')
    refresh = Mock(side_effect=RuntimeError('stop after call capture'))
    monkeypatch.setattr(daily_warehouses, 'refresh_daily', refresh)
    monkeypatch.setattr(daily_runner, 'ssh_config', lambda private: (['ssh'], {}))
    monkeypatch.setattr(sql_daily, 'verify_current_pointer',
                        lambda **kwargs: ({'release': 'daily-sql-existing'}, {}, {},
                                          Path('/unused'), {}, 'a' * 64))

    with pytest.raises(RuntimeError, match='stop after call capture'):
        daily_runner.run(
            workspace, day, force_refresh=True, bi_start_date='2025-03-01',
            input_paths=input_paths,
        )

    assert refresh.call_args.kwargs['bi_start_date'] == '2025-03-01'
    assert refresh.call_args.kwargs['input_paths'] == input_paths


def test_daily_requires_explicit_sql_current_before_collecting(tmp_path, monkeypatch):
    from data_acquisition.jobs import daily_warehouses

    day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    workspace = tmp_path / 'workspace'
    refresh = Mock()
    monkeypatch.setattr(daily_warehouses, 'refresh_daily', refresh)
    monkeypatch.setattr(daily_runner, 'ssh_config', lambda private: (['ssh'], {}))

    with pytest.raises(ValueError, match='SQL daily pointer is missing'):
        daily_runner.run(workspace, day)

    refresh.assert_not_called()


@pytest.mark.parametrize(('sources', 'raises'), [([], False), ([{'source_id': 'fee'}], True)])
def test_daily_fee_failure_keeps_published_business_and_reports_fee_boundary(
        tmp_path, monkeypatch, sources, raises):
    from data_acquisition.jobs import daily_warehouses
    from dashboard_product.shadow_bi.p5 import sql_daily

    day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    workspace = tmp_path / 'workspace'
    state = workspace / 'Output/ShadowDaily'
    state.mkdir(parents=True)
    fee_manifest = workspace / 'Input/AdvertisingCosts/sources.json'
    fee_manifest.parent.mkdir(parents=True)
    fee_manifest.write_text(json.dumps({'sources': sources}))
    pair = {
        'run_id': 'run_shadow_daily_' + day.replace('-', '') + '_feesfixture',
        'sources': {
            'bi': {'snapshot_id': 'snapshot_bi_fixture'},
            'study_abroad': {'snapshot_id': 'snapshot_study_fixture'},
        },
    }
    monkeypatch.setattr(daily_warehouses, 'assert_daily_ready', Mock(return_value=pair))
    monkeypatch.setattr(daily_runner, 'ssh_config', lambda private: (['ssh'], {}))
    monkeypatch.setattr(sql_daily, 'verify_current_pointer',
                        lambda **kwargs: ({'release': 'daily-sql-existing'}, {}, {},
                                          Path('/unused'), {}, 'a' * 64))

    def publish(**kwargs):
        return {'status': 'published', 'day': day, 'release': kwargs['release_id'],
                'batch_id': kwargs['run_id'], 'sources': pair,
                'expenses': {'status': 'failed', 'error_type': 'ValueError', 'retained_rows': 7}}

    monkeypatch.setattr(sql_daily, 'publish', publish)
    if raises:
        with pytest.raises(daily_runner.FeeRefreshFailed, match='prior fees were retained'):
            daily_runner.run(workspace, day, prepared_sources=pair)
    else:
        result = daily_runner.run(workspace, day, prepared_sources=pair)
        assert result['status'] == 'published'
        assert result['expenses']['status'] == 'failed'
    current = json.loads((state / 'current.json').read_text())
    assert current['status'] == 'published'
    if raises:
        assert current['fee_refresh_failure'] == {
            'status': 'failed', 'error_type': 'ValueError', 'retained_rows': 7,
        }


def test_daily_rejects_explicit_inputs_without_start_or_with_prepared_sources(tmp_path):
    day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    workspace = tmp_path / 'workspace'
    input_paths = {'orders': tmp_path / 'orders.xlsx', 'cash': tmp_path / 'cash.xlsx',
                   'tencent': tmp_path / 'tencent.xlsx'}

    with pytest.raises(ValueError, match='必须指定bi_start_date'):
        daily_runner.run(workspace, day, force_refresh=True, input_paths=input_paths)
    with pytest.raises(ValueError, match='不可与续跑或已准备来源混用'):
        daily_runner.run(
            workspace, day, force_refresh=True, bi_start_date='2025-03-01',
            input_paths=input_paths, prepared_sources=PAIR,
        )
