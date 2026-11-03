import hashlib
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from dashboard_product.shadow_bi.p5 import daily as daily_runner
from dashboard_product.shadow_bi.p5.full_daily import DailyBlocked
from data_acquisition.jobs.business_first_daily import run
from data_acquisition.jobs.prepare_full_daily import main


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
        'collect': Mock(),
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


def test_business_failure_never_notifies_or_collects_expenses(tmp_path):
    notify = Mock()
    expenses = Mock()
    result = run(**args(
        tmp_path,
        publish_business=Mock(side_effect=DailyBlocked('business_pair_missing')),
        publish_expenses=expenses,
        notify=notify,
    ))

    assert result['status'] == 'blocked'
    assert result['published'] is False
    notify.assert_not_called()
    expenses.assert_not_called()
    assert json.loads((tmp_path / 'batch/business-sources.json').read_text()) == {'sources': []}
    assert json.loads((tmp_path / 'batch/pipeline-result.json').read_text()) == result


def test_expense_failure_keeps_business_current_after_eight_sent(tmp_path):
    workspace = tmp_path / 'workspace'
    current = workspace / 'Output/ShadowDaily/current.json'
    current.parent.mkdir(parents=True)
    current.write_text(json.dumps({'release': 'old-release'}))
    order = []

    def publish_business(ws, day, *, advertising_manifest):
        assert json.loads(Path(advertising_manifest).read_text()) == {'sources': []}
        order.append('business')
        current.write_text(json.dumps({'release': 'business-release'}))
        return {'status': 'published', 'day': day, 'release': 'business-release',
                'sources': PAIR}

    def notify(ws, day, release, batch_dir):
        order.append('notify')
        return sent(release)

    def publish_expenses(ws, day, *, collect, prepare, business_capture):
        order.append('expenses')
        collect(ws, day, 'expense-run', tmp_path / 'capture')
        order.append('collect')
        assert business_capture(ws, day, 'expense-run') == PAIR
        raise RuntimeError('expense publication failed')

    result = run(**args(
        tmp_path,
        publish_business=publish_business,
        publish_expenses=publish_expenses,
        notify=notify,
    ))

    assert result['status'] == 'partial'
    assert result['published'] is True
    assert result['business']['status'] == 'published'
    assert result['notification']['status'] == 'sent'
    assert result['expenses']['error_type'] == 'RuntimeError'
    assert order == ['business', 'notify', 'expenses', 'collect']
    assert json.loads(current.read_text()) == {'release': 'business-release'}
    assert json.loads((tmp_path / 'batch/pipeline-result.json').read_text()) == result


def test_partial_retry_rechecks_business_skips_sent_notice_and_complete_retry_is_read_only(tmp_path):
    workspace = tmp_path / 'workspace'
    current = workspace / 'Output/ShadowDaily/current.json'
    current.parent.mkdir(parents=True)
    current.write_text(json.dumps({'release': 'old-release'}))
    business_calls = []
    notice = Mock(side_effect=lambda ws, day, release, batch: sent(release))
    expense_calls = []
    collect = Mock()

    def publish_business(ws, day, *, advertising_manifest):
        release = json.loads(current.read_text())['release']
        if release == 'old-release':
            release = 'business-release'
            current.write_text(json.dumps({'release': release}))
        business_calls.append(release)
        return {'status': 'published', 'date': day, 'release': release,
                'sources': PAIR}

    def publish_expenses(ws, day, *, collect, prepare, business_capture):
        expense_calls.append(day)
        collect(ws, day, 'expense-run', tmp_path / f'capture-{len(expense_calls)}')
        assert business_capture(ws, day, 'expense-run') == PAIR
        if len(expense_calls) == 1:
            raise RuntimeError('first expense attempt failed')
        current.write_text(json.dumps({'release': 'expense-release'}))
        return {'status': 'published', 'release': 'expense-release'}

    common = args(tmp_path, collect=collect, publish_business=publish_business,
                  publish_expenses=publish_expenses, notify=notice)
    first = run(**common)
    second = run(**common)
    saved = json.loads((tmp_path / 'batch/pipeline-result.json').read_text())
    third = run(**common)

    assert first['status'] == 'partial'
    assert second['status'] == 'complete'
    assert third == saved
    assert business_calls == ['business-release', 'business-release', 'expense-release']
    assert notice.call_count == 1
    assert expense_calls == [DAY, DAY]
    assert collect.call_count == 2


def test_expense_stage_requires_same_business_warehouse_pair(tmp_path):
    changed_pair = {
        'sources': {
            'bi': {'snapshot_id': 'snapshot-bi-new', 'run_id': 'run-bi-new'},
            'study_abroad': PAIR['sources']['study_abroad'],
        },
    }
    readiness = Mock(side_effect=[PAIR, changed_pair])
    expenses = Mock()
    result = run(**args(
        tmp_path,
        assert_ready=readiness,
        publish_business=Mock(return_value={
            'status': 'published', 'day': DAY, 'release': 'business-release',
            'sources': PAIR,
        }),
        publish_expenses=expenses,
        notify=Mock(side_effect=lambda ws, day, release, batch: sent(release)),
    ))

    assert result['status'] == 'partial'
    assert result['published'] is True
    assert result['expenses']['reason'] == 'business_sources_changed_before_expenses'
    expenses.assert_not_called()


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

    def publish_expenses(ws, day, *, collect, prepare, business_capture):
        current_release[0] = 'expense-release'
        return {'status': 'published', 'release': current_release[0]}

    common = args(
        tmp_path,
        refresh_business=True,
        publish_business=publish_business,
        publish_expenses=publish_expenses,
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
        publish_expenses=Mock(),
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

    def publish_expenses(ws, day, *, collect, prepare, business_capture):
        current_release[0] = 'expense-release'
        return {'status': 'published', 'release': current_release[0]}

    common = args(
        tmp_path,
        refresh_business=True,
        business_inputs=manifest_path,
        publish_business=publish_business,
        publish_expenses=publish_expenses,
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


def test_prepare_cli_keeps_original_full_daily_path_and_publish_uses_new_runner(tmp_path):
    common = [
        '--workspace', str(tmp_path / 'workspace'),
        '--batch-dir', str(tmp_path / 'batch'),
        '--source-contracts', str(tmp_path / 'contracts'),
        '--xhs-scope', str(tmp_path / 'scope.json'),
    ]
    preview = Mock(return_value={'status': 'prepared', 'published': False})
    assert main(common, run_fn=preview) == 0
    assert preview.call_args.kwargs['prepare'] is True
    assert 'batch_dir' not in preview.call_args.kwargs

    publishing = Mock(return_value={'status': 'complete', 'published': True})
    assert main([*common, '--publish'], run_fn=publishing) == 0
    assert publishing.call_args.kwargs['prepare'] is False
    assert publishing.call_args.kwargs['batch_dir'] == Path(tmp_path / 'batch')
    assert 'refresh_business' not in publishing.call_args.kwargs

    refreshing = Mock(return_value={'status': 'complete', 'published': True})
    assert main([*common, '--publish', '--refresh-business'], run_fn=refreshing) == 0
    assert refreshing.call_args.kwargs['refresh_business'] is True

    manifest = tmp_path / 'business-inputs.json'
    importing = Mock(return_value={'status': 'complete', 'published': True})
    assert main([
        *common, '--publish', '--refresh-business', '--business-inputs', str(manifest),
    ], run_fn=importing) == 0
    assert importing.call_args.kwargs['business_inputs'] == manifest


@pytest.mark.parametrize('mode', [[], ['--prepare']])
def test_refresh_business_cli_requires_publish(tmp_path, mode, capsys):
    common = [
        '--workspace', str(tmp_path / 'workspace'),
        '--batch-dir', str(tmp_path / 'batch'),
        '--source-contracts', str(tmp_path / 'contracts'),
        '--xhs-scope', str(tmp_path / 'scope.json'),
    ]

    with pytest.raises(SystemExit) as error:
        main([*common, *mode, '--refresh-business'], run_fn=Mock())

    assert error.value.code == 2
    assert '--refresh-business requires --publish' in capsys.readouterr().err


@pytest.mark.parametrize(('mode', 'reason'), [
    (['--business-inputs', 'inputs.json'],
     '--business-inputs requires --publish --refresh-business'),
    (['--publish', '--business-inputs', 'inputs.json'],
     '--business-inputs requires --publish --refresh-business'),
    (['--refresh-business', '--business-inputs', 'inputs.json'],
     '--refresh-business requires --publish'),
])
def test_business_inputs_cli_requires_publish_and_refresh_business(
        tmp_path, mode, reason, capsys):
    common = [
        '--workspace', str(tmp_path / 'workspace'),
        '--batch-dir', str(tmp_path / 'batch'),
        '--source-contracts', str(tmp_path / 'contracts'),
        '--xhs-scope', str(tmp_path / 'scope.json'),
    ]

    with pytest.raises(SystemExit) as error:
        main([*common, *mode], run_fn=Mock())

    assert error.value.code == 2
    assert reason in capsys.readouterr().err


def test_daily_default_reuses_same_day_success_receipt(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from data_acquisition.jobs import daily_warehouses

    day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    workspace = tmp_path / 'workspace'
    state = workspace / 'Output/ShadowDaily'
    state.mkdir(parents=True)
    receipt = {'status': 'published', 'day': day, 'release': 'daily-existing'}
    (state / f'{day}.json').write_text(json.dumps(receipt))
    commands = []
    refresh = Mock()
    monkeypatch.setattr(daily_warehouses, 'refresh_daily', refresh)
    monkeypatch.setattr(daily_runner, 'ssh_config', lambda private: (['ssh'], {}))
    monkeypatch.setattr(daily_runner, 'command',
                        lambda args, log, **kwargs: commands.append((args, kwargs)))
    monkeypatch.setattr(daily_runner.subprocess, 'run',
                        lambda *args, **kwargs: SimpleNamespace(stdout='daily-existing\n'))

    result = daily_runner.run(workspace, day)

    assert result == receipt
    refresh.assert_not_called()
    assert len(commands) == 1
    assert '--verify-only' in commands[0][1]['input']


def test_daily_force_refresh_runs_full_business_refresh_despite_same_day_receipt(
        tmp_path, monkeypatch):
    from data_acquisition.jobs import daily_warehouses
    from data_platform import business_library

    day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    workspace = tmp_path / 'workspace'
    state = workspace / 'Output/ShadowDaily'
    state.mkdir(parents=True)
    (state / f'{day}.json').write_text(json.dumps({
        'status': 'published', 'day': day, 'release': 'daily-existing',
    }))
    pair = {
        'sources': {
            'bi': {'snapshot_id': 'snapshot-bi', 'run_id': 'run-bi'},
            'study_abroad': {'snapshot_id': 'snapshot-study', 'run_id': 'run-study'},
        },
    }
    refresh = Mock(return_value={'status': 'passed'})
    commands = []
    monkeypatch.setattr(daily_warehouses, 'refresh_daily', refresh)
    monkeypatch.setattr(daily_warehouses, 'assert_daily_ready', Mock(return_value=pair))
    monkeypatch.setattr(daily_runner, 'ssh_config', lambda private: (['ssh'], {}))
    monkeypatch.setattr(daily_runner, 'command',
                        lambda args, log, **kwargs: commands.append((args, kwargs)))
    monkeypatch.setattr(business_library, 'load_library',
                        lambda path, batch: ({'batch_id': batch, 'coverage': {'rows': 1}}, None, None))

    def package_tables(source, presentation, destination):
        destination.mkdir(parents=True)
        return {}

    monkeypatch.setattr(daily_runner, 'package_tables', package_tables)

    result = daily_runner.run(workspace, day, force_refresh=True)

    assert result['status'] == 'published'
    assert result['release'] != 'daily-existing'
    refresh.assert_called_once()
    assert len(commands) == 4
    assert (state / 'current.json').exists()


def test_daily_passes_explicit_business_inputs_to_existing_refresh(tmp_path, monkeypatch):
    from data_acquisition.jobs import daily_warehouses

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

    with pytest.raises(RuntimeError, match='stop after call capture'):
        daily_runner.run(
            workspace, day, force_refresh=True, bi_start_date='2025-03-01',
            input_paths=input_paths,
        )

    assert refresh.call_args.kwargs['bi_start_date'] == '2025-03-01'
    assert refresh.call_args.kwargs['input_paths'] == input_paths


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
