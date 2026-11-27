"""Entry points for the independent business and advertising expense runs."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4

from data_acquisition.ops_io import DailyBlocked, atomic_json
from . import business
from data_acquisition.jobs.bi_window_merge import rolling_start_date
from data_acquisition.jobs.daily_notification import notify_published_resumable
from .state import OpsState

_STAGES = ('acquire', 'validate', 'build', 'publish', 'notify')


@contextmanager
def _tracked_run(state, run_id, pipeline, day):
    state.acquire(run_id, pipeline, day)
    stopped = Event()

    def heartbeat():
        while not stopped.wait(30):
            state.heartbeat(run_id)

    ticker = Thread(target=heartbeat, daemon=True)
    ticker.start()
    try:
        yield
    except Exception as error:
        state.end(run_id, 'failed', error_code=type(error).__name__)
        raise
    finally:
        stopped.set()
        ticker.join()


def _manual_manifest(runtime: Path, day: str, batch: Path) -> Path:
    inbox = runtime / 'inbox' / 'manual' / day
    document = {'as_of_date': day, 'bi_start_date': rolling_start_date(datetime.fromisoformat(day).date())}
    for name in ('orders', 'cash', 'tencent'):
        path = inbox / (name + '.xlsx')
        if name == 'tencent' and not path.exists() and not path.is_symlink():
            continue
        if not path.is_file() or path.is_symlink():
            raise DailyBlocked(f'manual_input_missing_or_invalid:{name}')
        with path.open('rb') as stream:
            document[name] = {'path': str(path.resolve()), 'sha256': hashlib.file_digest(stream, 'sha256').hexdigest()}
    manifest = batch / 'manual-manifest.json'
    atomic_json(manifest, document)
    return manifest


def _record_business_observations(state, day, report):
    business = report.get('business') or {}
    if business.get('status') != 'published':
        return
    pair = business.get('sources') or {}
    sources = pair.get('sources') or {}
    bi, abroad = sources.get('bi', {}), sources.get('study_abroad', {})
    bi_coverage = bi.get('coverage') or {}
    if bi_coverage:
        state.observe_pointer('business_bi', bi['snapshot_id'],
                              min(bi_coverage['orders_max_date'], bi_coverage['cash_max_date']), verified=True)
    if abroad.get('through_date'):
        state.observe_pointer('study_abroad', abroad['snapshot_id'], abroad['through_date'], verified=True)
    content = pair.get('content_work_orders') or {}
    if content.get('status') == 'passed':
        state.observe_pointer('sync_content', pair['run_id'], day, verified=True)
    notification = report.get('notification') or {}
    if notification.get('status') == 'sent':
        state.observe_pointer('dingtalk_daily', notification['release_id'], day, verified=True)


def _retain_published(runtime, publication, record):
    from .retention import retain_candidates

    if 'candidate' not in publication:
        return
    index = runtime / 'release-retention.json'
    references = runtime / 'release-references.json'
    candidates = runtime / 'releases'
    try:
        enrolled = json.loads(index.read_text()) if index.exists() else []
        protected = json.loads(references.read_text()) if references.exists() else []
        entry = {'path': publication['candidate'], 'created_at': datetime.now(business.SHANGHAI).isoformat(),
                 'biz_day': publication['biz_day'], 'verified_release_id': publication['release']}
        if not isinstance(enrolled, list) or any(not isinstance(item, dict) for item in enrolled):
            raise ValueError('invalid candidate enrollment schema')
        if not any(item.get('path') == entry['path'] for item in enrolled):
            enrolled.append(entry)
        atomic_json(index, enrolled)
        removed = retain_candidates(candidates, enrolled=enrolled, current=publication['candidate'],
                                    predecessor=publication['predecessor'], referenced=protected)
        if removed:
            removed_paths = set(removed)
            atomic_json(index, [item for item in enrolled if item['path'] not in removed_paths])
        record({'status': 'passed', 'removed': removed})
    except (ValueError, OSError, KeyError, TypeError) as error:
        record({'status': 'failed', 'error_type': type(error).__name__})


def run_business(workspace: Path, runtime: Path, *, day: str, from_manual=False, no_notify=False,
                 batch_dir=None, business_inputs=None, force_refresh=False, orders_start_date=None,
                 orders_end_date=None, now=None, pipeline=None, notify=None) -> dict:
    state = OpsState(runtime)
    run_id = 'business-' + day + '-' + uuid4().hex[:12]
    batch = Path(batch_dir) if batch_dir is not None else runtime / 'business' / run_id
    pipeline = pipeline or business.run
    events = {}

    def stage(name, status, detail=None):
        detail = detail or {}
        events[name] = status
        if name == 'publish' and status == 'passed':
            state.observe_pointer('superset_live', detail['release'], detail['data_through'], verified=True)
            _retain_published(runtime, detail, lambda value: state.record_stage(run_id, 'retention', value['status'], detail=value))
        state.record_stage(run_id, name, status, detail={k: v for k, v in detail.items() if k != 'sources'},
                           artifact_sha256=detail.get('artifact_sha256'),
                           data_through=detail.get('data_through'))

    with _tracked_run(state, run_id, 'business', day):
        if from_manual:
            stage('acquire', 'running')
            try:
                business_inputs = _manual_manifest(runtime, day, batch)
            except DailyBlocked:
                stage('acquire', 'failed')
                raise
        report = pipeline(
            workspace, batch_dir=batch, day=day, now=now,
            no_notify=no_notify, refresh_business=from_manual or force_refresh,
            business_inputs=business_inputs, orders_start_date=orders_start_date,
            orders_end_date=orders_end_date, notify=notify or notify_published_resumable,
            on_stage=stage, candidate_root=runtime / 'releases',
        )
        good_publication = (report.get('business') or {}).get('status') == 'published'
        for name in _STAGES[:-1]:
            if name not in events and good_publication:
                stage(name, 'skipped', {'reason': 'reused_verified_publication'})
            elif events.get(name) == 'running':
                stage(name, 'failed')
        outcome = report.get('notification') or {}
        if outcome.get('reason') == 'already_sent_today':
            stage('notify', 'skipped', outcome)
        elif outcome:
            stage('notify', outcome['status'], outcome)
        _record_business_observations(state, day, report)
        summary = {'report': str(batch / 'pipeline-result.json'), 'release': report.get('release'),
                   'business': report.get('business'), 'notification': outcome}
        code = None if report['status'] == 'complete' else (
            outcome.get('reason') or (report.get('business') or {}).get('reason')
            or (report.get('business') or {}).get('error_type'))
        state.end(run_id, report['status'], summary=summary, error_code=code)
        return {**report, 'ops_run_id': run_id}


def publish_costs(workspace, runtime, *, costs, on_stage, config_root=None):
    """Reuse the verified business release; publish only independently changed expenses."""
    from dashboard_product.shadow_bi.p5 import daily, sql_daily
    state = workspace / 'Output/ShadowDaily'
    with daily.production_lock(state):
        ssh, ssh_env = daily.ssh_config(workspace / '.private')
        run_id = 'run_shadow_fee_' + uuid4().hex
        verification = state / run_id
        verification.mkdir(parents=True)
        current = sql_daily.verify_current_pointer(
            workspace=workspace, ssh=ssh, ssh_env=ssh_env,
            log=verification / 'current.log', command_result=daily.command_result,
        )
        pointer, _, baseline, *_ = current
        business_day = baseline['as_of_date']
        previous_path = state / (business_day + '.json')
        previous = sql_daily._read_json(previous_path, 'current business release receipt')
        if (previous.get('release') != pointer['release'] or previous.get('day') != business_day
                or previous.get('status') != 'published'):
            raise ValueError('current business release lacks a matching local receipt')
        pair = previous['sources']
        if (pair['sources']['bi']['snapshot_id'] != baseline['snapshots']['training']
                or pair['sources']['study_abroad']['snapshot_id'] != baseline['snapshots']['abroad']):
            raise ValueError('fee publication business snapshot mismatch')
        release_id = daily._release_id(business_day, run_id, datetime.now(business.SHANGHAI).strftime('%H%M%S%f'))
        result = sql_daily.publish(
            workspace=workspace, day=business_day, pair=pair, run_id=run_id,
            release_id=release_id, folder=verification, advertising_manifest=None, ssh=ssh,
            ssh_env=ssh_env, command=daily.command, command_result=daily.command_result,
            config_root=config_root or sql_daily.ROOT, current_state=current, on_stage=on_stage,
            cloud_costs=costs, candidate_root=runtime / 'releases',
        )
        daily.write(previous_path, result)
        daily.write(state / 'current.json', result)
        return result


def ingest_costs(workspace: Path, runtime: Path, *, day: str, input_path: Path,
                 platform: str, confirmed_zero=(), publish=None) -> dict:
    from .costs import parse_input

    state = OpsState(runtime)
    run_id = 'costs-' + day + '-' + uuid4().hex[:12]
    publish = publish or publish_costs

    def stage(name, status, detail=None):
        if name == 'publish' and status == 'passed' and detail:
            _retain_published(runtime, detail, lambda value: state.record_stage(run_id, 'retention', value['status'], detail=value))
        state.record_stage(run_id, name, status, detail=detail)

    with _tracked_run(state, run_id, 'expenses', day):
        stage('validate', 'running')
        costs = parse_input(input_path, platform=platform, confirmed_zero=confirmed_zero)
        if any(row['end_date'] > day for row in costs['rows']):
            raise ValueError('费用日期晚于本次录入业务日')
        stage('validate', 'passed')
        result = publish(workspace, runtime, costs=costs, on_stage=stage)
        if result.get('status') != 'published':
            raise ValueError('fee publication was not confirmed')
        cutoff = result['coverage']['data_through']
        state.observe_pointer('superset_live', result['release'], cutoff, verified=True)
        latest_confirmed = max((row['end_date'] for row in costs['rows'] if row['amount'] is not None), default=None)
        prior = next((item['data_through'] for item in state.status()['live_pointers']
                      if item['domain'] == 'ad_costs'), None)
        dates = [date for date in (latest_confirmed, prior) if date is not None]
        state.observe_pointer('ad_costs', result['release'], max(dates) if dates else None, verified=True)
        summary = {'release': result['release'], 'expenses': result['expenses']}
        state.end(run_id, 'complete', summary=summary)
        return {**result, 'ops_run_id': run_id}
