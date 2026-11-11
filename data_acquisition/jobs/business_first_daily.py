"""Publish the business dashboard and its notification before advertising fees."""
from contextlib import contextmanager
from datetime import date, datetime
import fcntl
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from dashboard_product.shadow_bi.p5.full_daily import DailyBlocked, atomic_json, digest


SHANGHAI = ZoneInfo('Asia/Shanghai')
RESULT_NAME = 'pipeline-result.json'
EMPTY_ADVERTISING_MANIFEST = {'sources': []}
BUSINESS_INPUTS_FILENAME = 'business-inputs.json'
BUSINESS_INPUT_NAMES = ('orders', 'cash', 'tencent')


class _StageRejected(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


@contextmanager
def _batch_lock(batch_dir):
    batch_dir.mkdir(parents=True, exist_ok=True)
    path = batch_dir / '.business-first.lock'
    with path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DailyBlocked('business_first_batch_busy') from None
        yield


def _read_result(path):
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        raise DailyBlocked('pipeline_result_invalid') from None
    if not isinstance(value, dict):
        raise DailyBlocked('pipeline_result_invalid')
    return value


def _write_result(path, result):
    atomic_json(path, result)


def _safe_error(error):
    result = {'error_type': type(error).__name__}
    if isinstance(error, DailyBlocked):
        result['reason'] = str(error)
    elif isinstance(error, _StageRejected):
        result['reason'] = error.code
    return result


def _validated_business_inputs(path, day, batch_dir):
    try:
        raw = Path(path).read_bytes()
        value = json.loads(raw)
    except OSError:
        raise DailyBlocked('business_inputs_manifest_unreadable') from None
    except (TypeError, ValueError):
        raise DailyBlocked('business_inputs_manifest_invalid') from None
    if not isinstance(value, dict):
        raise DailyBlocked('business_inputs_manifest_invalid')
    as_of_date = value.get('as_of_date')
    bi_start_date = value.get('bi_start_date')
    try:
        parsed_as_of = date.fromisoformat(as_of_date)
    except (TypeError, ValueError):
        raise DailyBlocked('business_inputs_as_of_date_invalid') from None
    if parsed_as_of.isoformat() != as_of_date or as_of_date != day:
        raise DailyBlocked('business_inputs_as_of_date_mismatch')
    if not isinstance(bi_start_date, str):
        raise DailyBlocked('business_inputs_start_date_invalid')
    try:
        start = date.fromisoformat(bi_start_date)
    except (TypeError, ValueError):
        raise DailyBlocked('business_inputs_start_date_invalid') from None
    if start.isoformat() != bi_start_date:
        raise DailyBlocked('business_inputs_start_date_invalid')
    if start > date.fromisoformat(day):
        raise DailyBlocked('business_inputs_start_date_after_as_of')

    input_paths = {}
    for name in BUSINESS_INPUT_NAMES:
        spec = value.get(name)
        if not isinstance(spec, dict):
            raise DailyBlocked('business_inputs_file_spec_invalid')
        supplied_path, expected_sha = spec.get('path'), spec.get('sha256')
        if not isinstance(supplied_path, str) or not isinstance(expected_sha, str):
            raise DailyBlocked('business_inputs_file_spec_invalid')
        candidate = Path(supplied_path)
        if not candidate.is_absolute():
            raise DailyBlocked('business_inputs_path_must_be_absolute')
        try:
            candidate = candidate.resolve(strict=True)
        except OSError:
            raise DailyBlocked('business_inputs_file_missing') from None
        if not candidate.is_file():
            raise DailyBlocked('business_inputs_file_missing')
        if digest(candidate) != expected_sha:
            raise DailyBlocked('business_inputs_sha256_mismatch')
        input_paths[name] = candidate

    (Path(batch_dir) / BUSINESS_INPUTS_FILENAME).write_bytes(raw)
    return {'input_paths': input_paths, 'bi_start_date': bi_start_date}


def _business_result(raw, workspace, day, assert_ready):
    if not isinstance(raw, dict) or raw.get('status') != 'published':
        raise _StageRejected('business_publish_not_confirmed')
    reported_day = raw.get('day') if raw.get('day') is not None else raw.get('date')
    if (reported_day != day
            or (raw.get('day') is not None and raw.get('date') is not None
                and raw.get('day') != raw.get('date'))):
        raise _StageRejected('business_day_mismatch')
    release = raw.get('release')
    sources = raw.get('sources')
    if not isinstance(release, str) or not release:
        raise _StageRejected('business_release_missing')
    if not isinstance(sources, dict):
        raise _StageRejected('business_sources_missing')
    try:
        current_sources = assert_ready(workspace, day)
    except Exception as error:
        raise _StageRejected('business_sources_not_ready') from error
    if sources != current_sources:
        raise _StageRejected('business_sources_changed')
    return {
        'status': 'published',
        'day': day,
        'release': release,
        'sources': sources,
        'reused': bool(raw.get('reused')),
    }


def _notification_summary(raw, day, release):
    if not isinstance(raw, dict):
        return {'status': 'unknown', 'day': day, 'release': release}
    status = raw.get('status')
    summary = {'status': status if isinstance(status, str) else 'unknown',
               'day': day, 'release': release}
    for key in ('release_id', 'as_of_date', 'message_count'):
        if raw.get(key) is not None:
            summary[key] = raw[key]
    counts = raw.get('message_status_counts')
    if isinstance(counts, dict):
        summary['message_status_counts'] = counts
    return summary


def _notification_sent(raw, day, release):
    return (isinstance(raw, dict) and raw.get('status') == 'sent'
            and raw.get('release_id') == release and raw.get('as_of_date') == day
            and raw.get('message_count') == 8
            and raw.get('message_status_counts') == {'sent': 8})


def _notification_recorded_sent(value, day, release):
    return (isinstance(value, dict) and value.get('status') == 'sent'
            and value.get('day') == day and value.get('release') == release
            and value.get('release_id') == release and value.get('as_of_date') == day
            and value.get('message_count') == 8
            and value.get('message_status_counts') == {'sent': 8})


def _call_business(publish_business, workspace, day, manifest, assert_ready):
    raw = publish_business(workspace, day, advertising_manifest=manifest)
    stage = _business_result(raw, workspace, day, assert_ready)
    return raw, stage


def _business_recheck(publish_business, workspace, day, manifest, assert_ready,
                      expected_release, expected_sources):
    _, stage = _call_business(publish_business, workspace, day, manifest, assert_ready)
    if stage['sources'] != expected_sources:
        raise _StageRejected('business_sources_changed')
    if stage['release'] != expected_release:
        raise _StageRejected('business_current_release_changed')
    return stage


def _default_publishers():
    from dashboard_product.shadow_bi.p5.daily import run as publish_business
    from dashboard_product.shadow_bi.p5.full_daily import run as publish_expenses
    from data_acquisition.jobs.daily_warehouses import assert_daily_ready
    from data_acquisition.jobs.daily_notification import notify_published
    return publish_business, publish_expenses, notify_published, assert_daily_ready


def run(workspace, *, batch_dir, collect, prepare=False, day=None, now=None,
        publish_business=None, publish_expenses=None, notify=None,
        assert_ready=None, refresh_business=False, business_inputs=None,
        orders_start_date=None, orders_end_date=None):
    """Run the two-stage daily release while persisting each confirmed boundary."""
    if prepare:
        raise DailyBlocked('business_first_publish_only')
    if business_inputs is not None and not refresh_business:
        raise DailyBlocked('business_inputs_requires_refresh_business')
    if not callable(collect):
        raise DailyBlocked('advertising_collector_required')
    workspace = Path(workspace).resolve()
    batch_dir = Path(batch_dir).resolve()
    now = now or datetime.now(SHANGHAI)
    if now.tzinfo is None:
        raise DailyBlocked('timezone_required')
    today = now.astimezone(SHANGHAI).date()
    try:
        selected_day = date.fromisoformat(day).isoformat() if day is not None else today.isoformat()
    except (TypeError, ValueError):
        raise DailyBlocked('invalid_day') from None
    if selected_day != today.isoformat():
        raise DailyBlocked('not_shanghai_today')

    defaults = (publish_business, publish_expenses, notify, assert_ready)
    loaded = _default_publishers() if any(value is None for value in defaults) else defaults
    publish_business = publish_business or loaded[0]
    publish_expenses = publish_expenses or loaded[1]
    notify = notify or loaded[2]
    assert_ready = assert_ready or loaded[3]

    result_path = batch_dir / RESULT_NAME
    manifest_path = batch_dir / 'business-sources.json'
    with _batch_lock(batch_dir):
        previous = _read_result(result_path) if result_path.exists() else None
        if previous is not None and previous.get('day') != selected_day:
            raise DailyBlocked('pipeline_batch_day_mismatch')
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text())
            except (OSError, ValueError):
                raise DailyBlocked('business_manifest_invalid') from None
            if manifest != EMPTY_ADVERTISING_MANIFEST:
                raise DailyBlocked('business_manifest_not_empty')
        else:
            manifest = EMPTY_ADVERTISING_MANIFEST
            atomic_json(manifest_path, manifest)

        if previous is not None and previous.get('status') == 'complete':
            business = previous.get('business')
            expenses = previous.get('expenses')
            if (not isinstance(business, dict) or not isinstance(expenses, dict)
                    or not isinstance(expenses.get('release'), str)
                    or not expenses.get('release')):
                raise DailyBlocked('completed_pipeline_receipt_invalid')
            try:
                _business_recheck(publish_business, workspace, selected_day, manifest_path,
                                  assert_ready, expenses['release'], business['sources'])
            except Exception:
                raise DailyBlocked('completed_pipeline_current_mismatch') from None
            return previous

        state = previous or {
            'schema_version': 'business_first_daily.v1',
            'day': selected_day,
            'batch_dir': str(batch_dir),
            'status': 'running',
            'published': False,
            'business': None,
            'notification': None,
            'expenses': None,
        }
        state['status'] = 'running'
        _write_result(result_path, state)

        prior_business = state.get('business')
        if isinstance(prior_business, dict) and prior_business.get('status') == 'published':
            try:
                business = _business_recheck(
                    publish_business, workspace, selected_day, manifest_path,
                    assert_ready, prior_business.get('release'), prior_business.get('sources'))
            except Exception as error:
                state.update(status='partial', published=True,
                             business_recheck={'status': 'failed', **_safe_error(error)})
                _write_result(result_path, state)
                return state
            business = prior_business
        else:
            raw_business = None
            try:
                publish_kwargs = {'advertising_manifest': manifest_path}
                if refresh_business and previous is None:
                    publish_kwargs['force_refresh'] = True
                    if business_inputs is not None:
                        publish_kwargs.update(
                            _validated_business_inputs(business_inputs, selected_day, batch_dir))
                elif business_inputs is not None:
                    raise DailyBlocked('business_inputs_requires_new_batch')
                if orders_start_date is not None:
                    publish_kwargs.update(orders_start_date=orders_start_date, orders_end_date=orders_end_date)
                raw_business = publish_business(workspace, selected_day, **publish_kwargs)
                business = _business_result(raw_business, workspace, selected_day, assert_ready)
            except Exception as error:
                confirmed = isinstance(raw_business, dict) and raw_business.get('status') == 'published'
                reported_status = raw_business.get('status') if isinstance(raw_business, dict) else None
                business_record = {
                    'status': 'published' if confirmed else (reported_status or 'failed'),
                    **_safe_error(error),
                }
                if confirmed:
                    for key in ('day', 'date', 'release', 'sources'):
                        if raw_business.get(key) is not None:
                            business_record[key] = raw_business[key]
                state.update(
                    status='partial' if confirmed else ('blocked' if isinstance(error, DailyBlocked) else 'failed'),
                    published=confirmed,
                    business=business_record,
                    notification={'status': 'not_attempted'},
                    expenses={'status': 'not_attempted'},
                )
                _write_result(result_path, state)
                return state
            state.update(status='running', published=True, release=business['release'],
                         business=business, business_recheck={'status': 'passed'})
            _write_result(result_path, state)

        state.update(status='running', published=True, release=business['release'], business=business)
        if state.get('notification') is None or not _notification_recorded_sent(
                state['notification'], selected_day, business['release']):
            state['notification'] = {'status': 'running', 'day': selected_day,
                                     'release': business['release']}
            _write_result(result_path, state)
            try:
                notification_result = notify(
                    workspace, selected_day, business['release'], batch_dir)
            except Exception as error:
                state.update(status='partial', published=True,
                             notification={'status': 'failed', 'day': selected_day,
                                           'release': business['release'], **_safe_error(error)},
                             expenses={'status': 'not_attempted',
                                       'reason': 'notification_not_confirmed'})
                _write_result(result_path, state)
                return state
            notification = _notification_summary(
                notification_result, selected_day, business['release'])
            state['notification'] = notification
            if not _notification_sent(notification_result, selected_day, business['release']):
                state.update(status='partial', published=True,
                             expenses={'status': 'not_attempted',
                                       'reason': 'notification_not_confirmed'})
                _write_result(result_path, state)
                return state
            state['notification'].update(
                message_count=8, message_status_counts={'sent': 8})
            _write_result(result_path, state)

        try:
            if assert_ready(workspace, selected_day) != business['sources']:
                raise _StageRejected('business_sources_changed_before_expenses')
        except Exception as error:
            state.update(status='partial', published=True,
                         expenses={'status': 'failed', **_safe_error(error)})
            _write_result(result_path, state)
            return state

        def reused_business_capture(ws, selected_day, _run_id):
            if selected_day != state['day']:
                raise DailyBlocked('business_capture_day_mismatch')
            current_sources = assert_ready(ws, selected_day)
            if current_sources != business['sources']:
                raise DailyBlocked('business_pair_changed')
            return business['sources']

        state['expenses'] = {'status': 'running'}
        state.update(status='running', published=True)
        _write_result(result_path, state)
        try:
            expense_result = publish_expenses(
                workspace, selected_day, collect=collect, prepare=False,
                business_capture=reused_business_capture)
        except Exception as error:
            state.update(status='partial', published=True,
                         expenses={'status': 'failed', **_safe_error(error)})
            _write_result(result_path, state)
            return state

        if not isinstance(expense_result, dict) or expense_result.get('status') != 'published':
            error_type = ((expense_result or {}).get('error_type')
                          if isinstance(expense_result, dict) else None)
            state.update(status='partial', published=True,
                         expenses={'status': ((expense_result or {}).get('status')
                                             if isinstance(expense_result, dict) else 'failed'),
                                   'error_type': error_type or 'ExpensePublishNotConfirmed'})
            _write_result(result_path, state)
            return state
        expense_release = expense_result.get('release')
        if not isinstance(expense_release, str) or not expense_release:
            state.update(status='partial', published=True,
                         expenses={'status': 'failed', 'error_type': 'ExpenseReleaseMissing'})
            _write_result(result_path, state)
            return state

        state.update(status='complete', published=True,
                     expenses={'status': 'published', 'release': expense_release})
        _write_result(result_path, state)
        return state
