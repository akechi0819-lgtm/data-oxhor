from datetime import datetime
from decimal import Decimal
import json

from ops import cli
from ops.pipeline import ingest_costs, run_business
from ops.state import OpsState
from data_acquisition.jobs import business_first_daily
from data_acquisition.jobs.daily_notification import notify_published_resumable


DAY = '2026-11-26'
NOW = datetime.fromisoformat(DAY + 'T09:30:00+08:00')


def test_incremental_notification_then_manual_rebuild_does_not_resend(tmp_path, capsys):
    workspace, runtime = tmp_path / 'workspace', tmp_path / 'runtime'
    workspace.mkdir()
    sends = []
    current = {}

    def send_under_server_lock(_workspace, date, release, log):
        deduplicated = 8 if sends else 0
        if not deduplicated:
            sends.extend(range(8))
        log.write_text(json.dumps({
            'status': 'sent', 'release_id': release, 'as_of_date': date,
            'message_count': 8, 'message_status_counts': {'sent': 8},
            'deduplicated': deduplicated, 'network_send_attempted': not deduplicated,
        }))
        return 0

    def notify(ws, day, release, batch):
        return notify_published_resumable(ws, day, release, batch,
                                         clock=lambda: NOW, execute=send_under_server_lock)

    def publish(ws, date, *, on_stage, advertising_manifest, **kwargs):
        assert ws == workspace and date == DAY
        assert json.loads(advertising_manifest.read_text()) == {'sources': []}
        assert 'input_paths' not in kwargs or set(kwargs['input_paths']) == {'orders', 'cash'}
        release = 'daily-full' if kwargs.get('input_paths') else 'daily-incremental'
        count = 720 if release == 'daily-full' else 18
        current.update({
            'run_id': release, 'sources': {
                'bi': {'snapshot_id': 'bi-' + release, 'coverage': {
                    'orders_rows': count, 'cash_rows': 90,
                    'orders_max_date': '2026-11-25', 'cash_max_date': '2026-11-25',
                }},
                'study_abroad': {'snapshot_id': 'abroad-' + release, 'through_date': '2026-11-25'},
            }, 'content_work_orders': {'status': 'passed'},
        })
        for step in ('acquire', 'validate', 'build', 'publish'):
            on_stage(step, 'running')
            on_stage(step, 'passed', {'release': release, 'data_through': '2026-11-25'})
        return {'status': 'published', 'day': DAY, 'release': release, 'sources': current.copy()}

    def pipeline(*args, **kwargs):
        def should_not_collect(*_args, **_kwargs):
            raise AssertionError('business must not acquire or publish fees')
        return business_first_daily.run(*args, **kwargs, publish_business=publish,
                                         publish_expenses=should_not_collect, assert_ready=lambda *_: current)

    automatic = run_business(workspace, runtime, day=DAY, now=NOW, pipeline=pipeline, notify=notify)
    assert automatic['release'] == 'daily-incremental'
    assert automatic['notification']['message_status_counts'] == {'sent': 8}
    inbox = runtime / 'inbox' / 'manual' / DAY
    inbox.mkdir(parents=True)
    (inbox / 'orders.xlsx').write_bytes(b'mocked orders')
    (inbox / 'cash.xlsx').write_bytes(b'mocked cash')
    corrected = run_business(workspace, runtime, day=DAY, now=NOW, from_manual=True,
                             pipeline=pipeline, notify=notify)
    assert corrected['release'] == 'daily-full'
    assert corrected['notification']['reason'] == 'already_sent_today'
    assert len(sends) == 8
    assert corrected['business']['sources']['sources']['bi']['coverage']['orders_rows'] == 720
    snapshots = OpsState(runtime).status(DAY)
    assert len(snapshots['runs']) == 2
    assert snapshots['stage_events'][-1]['stage'] == 'notify'
    assert snapshots['stage_events'][-1]['status'] == 'skipped'
    assert cli.main(['--runtime', str(runtime), 'status', '--day', DAY]) == 0
    output = capsys.readouterr().out
    assert 'daily-full' in output and 'already_sent_today' in output
    assert '投流' in output and '点评' in output and '初三' in output


def test_independent_cost_run_records_cost_coverage(tmp_path):
    runtime = tmp_path / 'runtime'
    workbook = tmp_path / 'costs.csv'
    workbook.write_text('date,business_line,business_group,amount\n'
                        '2026-11-23,training,高中,0\n'
                        '2026-11-24,training,高中,12.00\n'
                        '2026-11-25,training,高中,\n')
    def publish(workspace, run_root, *, costs, on_stage):
        assert run_root == runtime
        assert [row['amount'] for row in costs['rows']] == [Decimal('0'), Decimal('12.00'), None]
        on_stage('build', 'passed')
        on_stage('publish', 'passed')
        return {'status': 'published', 'release': 'daily-fees',
                'coverage': {'data_through': '2026-11-25'}, 'expenses': {'status': 'updated'}}
    ingest_costs(tmp_path, runtime, day=DAY, input_path=workbook, platform='xhs',
                 confirmed_zero=['高中=2026-11-23'], publish=publish)
    snapshot = OpsState(runtime).status(DAY)
    assert {row['stage'] for row in snapshot['stage_events']} == {'validate', 'build', 'publish'}
    costs = next(row for row in snapshot['live_pointers'] if row['domain'] == 'ad_costs')
    assert costs['data_through'] == '2026-11-24'
