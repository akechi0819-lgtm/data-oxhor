"""Tencent native report export from the observed, authorized account protocol.

Cookie first, no ordinary Chrome attachment. Signed file URLs stay in memory.
The captured product scope is retained; missing native days are never zeros.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
import json
from pathlib import Path
import re
import ssl
import tempfile
import time
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler
from zoneinfo import ZoneInfo
import certifi
from data_acquisition.auth.auth_sessions import AuthSessionPaths, write_auth_session, AuthSessionMissingError, AuthSessionExpiredError
from data_acquisition.connectors.advertising.tencent_native import inspect_report
from data_acquisition.jobs.intake_advertising import intake
ORIGIN = 'https://ad.qq.com'
QUERY = '/api/v3.0/integrated_list_multiaccount/get'
LEGACY_QUERY='/ap/integrated_list/get_user_integrated_list'
QUERY_PATHS={'display_plus':QUERY,'legacy_search':LEGACY_QUERY}
CREATE = '/ap/async_task/create'
POLL = '/bff/contract/trpc.dp.dpbff.task_cgi.task_cgi/GetAsyncRequestDetail'
DOWNLOAD = '/ap/async_task/download'
TASKS = '/ap/async_task/get_list'
TZ = ZoneInfo('Asia/Shanghai')

class ExportBlocked(RuntimeError):
    pass

class TencentLoginRequired(ExportBlocked):
    """A narrowly observed Tencent response that requires restoring login."""
    error_code = 4501

    def __init__(self):
        super().__init__('tencent_login_required')

class TencentLoginRecoveryUnverified(ExportBlocked):
    """The account session was saved, but its export query scopes were not verified."""

class ExportPending(RuntimeError):
    pass

def _auth_query_values(url):
    """Keep only known auth fields from the observed normal browser request URL."""
    parsed = parse_qs(urlsplit(url).query, keep_blank_values=True)
    return {key: parsed[key] for key in ('mp_tk', 'g_tk') if key in parsed}

def _one_auth_value(query, name):
    values = query.get(name)
    if isinstance(values, str):
        return values or None
    if isinstance(values, list) and len(values) == 1 and isinstance(values[0], str):
        return values[0] or None
    return None

def _normal_query_succeeded(value):
    return (isinstance(value, dict)
            and type(value.get('code')) is int and value.get('code') == 0
            and ('ret' not in value or (type(value.get('ret')) is int and value.get('ret') == 0))
            )

def _query_capture_count(captured, scope):
    path = QUERY_PATHS[scope]
    return sum(1 for captured_path, _headers, _query in captured if captured_path == path)

def _wait_for_query_scope(page, captured, scope, *, after=0, timeout_seconds=30):
    deadline = time.monotonic() + timeout_seconds
    while _query_capture_count(captured, scope) <= after and time.monotonic() < deadline:
        page.wait_for_timeout(200)
    return _query_capture_count(captured, scope) > after

def _required_login_scopes_captured(captured):
    return all(_query_capture_count(captured, scope) > 0 for scope in ('display_plus', 'legacy_search'))

def _unique_visible_text(page, text):
    visible = [locator for locator in page.get_by_text(text, exact=True).all()
               if locator.is_visible()]
    if len(visible) != 1:
        raise ExportBlocked('tencent_legacy_navigation_not_unique')
    return visible[0]

def _wait_for_unique_visible_text(page, text, *, timeout_seconds=10):
    deadline = time.monotonic() + timeout_seconds
    while True:
        visible = [locator for locator in page.get_by_text(text, exact=True).all()
                   if locator.is_visible()]
        if len(visible) == 1:
            return visible[0]
        if len(visible) > 1 or time.monotonic() >= deadline:
            raise ExportBlocked('tencent_legacy_navigation_not_unique')
        page.wait_for_timeout(200)

def _open_legacy_search(page):
    _unique_visible_text(page, '竞价-展示投放').click()
    _wait_for_unique_visible_text(page, '搜索投放').click()

def _refresh_export_auth(auth, captured):
    """Refresh configured auth fields only from the matching observed request path."""
    parts = [auth[name] for name in ('create', 'poll', 'list', 'download')]
    parts.extend(auth['queries'].values())
    fresh_g_tk = None
    for _path, headers, query in captured:
        for header_name, query_name in (('g-tk', 'g_tk'),):
            header_value = headers.get(header_name)
            query_value = _one_auth_value(query, query_name)
            if query_name in query and not query_value:
                raise ExportBlocked('tencent_auth_refresh_ambiguous')
            if header_value and query_value and header_value != query_value:
                raise ExportBlocked('tencent_auth_refresh_ambiguous')
            value = header_value or query_value
            if value and fresh_g_tk and fresh_g_tk != value:
                raise ExportBlocked('tencent_auth_refresh_ambiguous')
            if value:
                fresh_g_tk = value

    for part in parts:
        if not isinstance(part, dict) or 'headers' not in part:
            continue
        query_part = part.get('query') or {}
        for key in ('x-tsa-client-authentication', 'user-agent', 'sec-ch-ua',
                    'sec-ch-ua-mobile', 'sec-ch-ua-platform'):
            observed = next((headers[key] for _path, headers, _query in reversed(captured)
                             if key in headers), None)
            if observed is not None and key in part['headers']:
                part['headers'][key] = observed
        if fresh_g_tk and 'g-tk' in part['headers']:
            part['headers']['g-tk'] = fresh_g_tk
        if fresh_g_tk and 'g_tk' in query_part:
            query_part['g_tk'] = fresh_g_tk

    for path, headers, query in captured:
        matching = [part for part in parts if part.get('path') == path]
        if len(matching) != 1:
            continue
        part = matching[0]
        part_headers = part.get('headers') or {}
        part_query = part.get('query') or {}
        if not ('mp-tk' in part_headers or 'mp_tk' in part_query):
            continue
        header_value = headers.get('mp-tk')
        query_value = _one_auth_value(query, 'mp_tk')
        if 'mp_tk' in query and not query_value:
            raise ExportBlocked('tencent_auth_refresh_ambiguous')
        if header_value and query_value and header_value != query_value:
            raise ExportBlocked('tencent_auth_refresh_ambiguous')
        value = header_value or query_value
        if not value:
            raise ExportBlocked('tencent_additional_auth_refresh_not_observed')
        if 'mp-tk' in part_headers:
            part_headers['mp-tk'] = value
        if 'mp_tk' in part_query:
            part_query['mp_tk'] = value

class NoRedirect(HTTPRedirectHandler):

    def redirect_request(self, *args, **kwargs):
        return None

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def now():
    return datetime.now(TZ)

def write(path, value):
    path = Path(path)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)

def private_json(path):
    if not path.is_file():
        raise AuthSessionMissingError('tencent_auth_state_missing')
    if path.stat().st_mode & 63:
        raise ExportBlocked('tencent_auth_file_not_private')
    try:
        return json.loads(path.read_text())
    except Exception:
        raise ExportBlocked('tencent_auth_format_invalid') from None

class TencentExport:

    def __init__(self, workspace, *, post=None, transfer=None, clock=now, sleep=time.sleep, request_timeout=30, generation_timeout=900, transfer_timeout=900):
        self.paths = AuthSessionPaths(Path(workspace), 'tencent_ads')
        self.scope='display_plus'
        self.post = post or self._post
        self.transfer = transfer or self._transfer
        self.clock = clock
        self.sleep = sleep
        self.request_timeout = request_timeout
        self.generation_timeout = generation_timeout
        self.transfer_timeout = transfer_timeout

    def _cookie(self, path):
        cookies = private_json(self.paths.cookies)
        if not isinstance(cookies, list):
            raise ExportBlocked('tencent_auth_format_invalid')
        pairs = []
        scoped = expired = 0
        for c in cookies:
            if not isinstance(c, dict):
                raise ExportBlocked('tencent_auth_format_invalid')
            domain = str(c.get('domain', '')).lstrip('.')
            cp = c.get('path', '/')
            if not domain or not ('ad.qq.com' == domain or 'ad.qq.com'.endswith('.' + domain)):
                continue
            if not isinstance(cp, str) or not (cp == '/' or path == cp or path.startswith(cp.rstrip('/') + '/')):
                continue
            scoped += 1
            try:
                expiry = float(c.get('expires', c.get('expirationDate', -1)))
                if 0 <= expiry <= time.time():
                    expired += 1
                    continue
            except (TypeError, ValueError):
                raise ExportBlocked('tencent_cookie_expiry_invalid') from None
            name, value = (c.get('name'), c.get('value'))
            if not isinstance(name, str) or not re.fullmatch("[!#$%&'*+.^_`|~0-9A-Za-z-]+", name) or (not isinstance(value, str)) or any((v in value for v in '\r\n;')):
                raise ExportBlocked('tencent_cookie_invalid')
            pairs.append(name + '=' + value)
        if not pairs:
            if scoped and scoped == expired:
                raise AuthSessionExpiredError('tencent_cookies_expired')
            raise ExportBlocked('tencent_cookie_domain_or_path_mismatch')
        return '; '.join(pairs)

    def _post(self, kind, body):
        auth = private_json(self.paths.root / 'export-auth.json')
        if auth.get('account_id') != '74749810':
            raise ExportBlocked('tencent_auth_account_mismatch')
        part = auth['queries'][self.scope] if kind=='query' else auth[kind]
        expected = QUERY_PATHS[self.scope] if kind=='query' else {'create':CREATE,'poll':POLL,'list':TASKS}[kind]
        if part['path'] != expected:
            raise ExportBlocked('tencent_auth_path_mismatch')
        query = {} if kind == 'query' and self.scope=='display_plus' else dict(part['query'])
        if kind == 'list':
            query.update(body)
        url = ORIGIN + expected + ('?' + urlencode(query) if query else '')
        headers = {k: v for k, v in part['headers'].items() if not k.startswith(':') and k.lower() not in {'cookie', 'content-length', 'accept-encoding'}}
        headers['Cookie'] = self._cookie(expected)
        request = Request(url, data=None if kind == 'list' else json.dumps(body, ensure_ascii=False).encode(), method='GET' if kind == 'list' else 'POST', headers=headers)
        try:
            with build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where()))).open(request, timeout=self.request_timeout) as response:
                raw = response.read(3000001)
            if len(raw) > 3000000:
                raise ExportBlocked('tencent_response_too_large')
            value = json.loads(raw)
        except HTTPError as error:
            if error.code == 401:
                raise AuthSessionExpiredError('tencent_http_401') from None
            raise ExportBlocked('tencent_http_' + str(error.code)) from None
        except ExportBlocked:
            raise
        except Exception:
            raise ExportPending('tencent_request_result_unconfirmed') from None
        if (isinstance(value, dict)
                and type(value.get('code')) is int and value.get('code') == 4501
                and type(value.get('ret')) is int and value.get('ret') == 4501):
            raise TencentLoginRequired()
        if not isinstance(value, dict) or value.get('code') != 0 or ('ret' in value and value['ret'] != 0):
            raise ExportBlocked('tencent_api_rejected')
        return value

    def _transfer(self, task, path):
        auth = private_json(self.paths.root / 'export-auth.json')
        part = auth['download']
        if part['path'] != DOWNLOAD or part['method'] != 'POST':
            raise ExportBlocked('tencent_download_contract_mismatch')
        body = {**part['body'], 'task_id': str(task['task_id']), 'file_id': str(task['file_id'])}
        headers = {k: v for k, v in part['headers'].items() if not k.startswith(':') and k.lower() not in {'cookie', 'content-length', 'accept-encoding'}}
        headers['Cookie'] = self._cookie(DOWNLOAD)
        url = ORIGIN + DOWNLOAD + ('?' + urlencode(part['query']) if part['query'] else '')
        request = Request(url, data=urlencode(body).encode(), headers=headers, method='POST')
        started = time.monotonic()
        try:
            with build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where()))).open(request, timeout=self.request_timeout) as response, path.open('xb') as handle:
                while True:
                    if time.monotonic() - started >= self.transfer_timeout:
                        raise ExportPending('tencent_file_transfer_pending')
                    raw = response.read(262144)
                    if not raw:
                        break
                    handle.write(raw)
        except HTTPError as error:
            if error.code == 401:
                raise AuthSessionExpiredError('tencent_download_http_401') from None
            raise ExportBlocked('tencent_download_http_' + str(error.code)) from None
        except (ExportPending, ExportBlocked):
            raise
        except Exception:
            raise ExportPending('tencent_file_result_unconfirmed') from None

    def _tasks(self):
        rows = []
        page = 1
        while True:
            value = self.post('list', {'page': page, 'page_size': 20})
            data = value.get('data', {})
            conf = data.get('conf', {})
            if not isinstance(data.get('list'), list) or not isinstance(conf.get('total_page'), int) or (not 0 <= conf['total_page'] <= 500):
                raise ExportBlocked('tencent_task_list_schema_changed')
            rows += data['list']
            if page >= conf['total_page']:
                return rows
            page += 1

    def _query(self, contract, start, through, folder):
        body = deepcopy(contract['query']['body'])
        body['date_range'] = {'start_date': start, 'end_date': through}
        if body.get('account_id_list')!=[74749810]:raise ExportBlocked('tencent_query_account_scope_changed')
        body['page'] = 1
        rows = []
        pages = None
        total = None
        while True:
            value = self.post('query', body)
            data = value.get('data', {})
            info = data.get('page_info', {})
            if not isinstance(data.get('list'), list) or not all((isinstance(info.get(k), int) for k in ('page', 'page_size', 'total_number', 'total_page'))) or info['page'] != body['page'] or (info['page_size'] != body['page_size']) or (not 0 <= info['total_number'] <= 10000) or (not 0 <= info['total_page'] <= 500):
                raise ExportBlocked('tencent_query_page_schema_changed')
            if pages is None:
                pages, total = (info['total_page'], info['total_number'])
            if (pages, total) != (info['total_page'], info['total_number']):
                raise ExportBlocked('tencent_query_changed_during_paging')
            write(folder / f'query-page-{body['page']:03d}.json', value)
            rows += data['list']
            if body['page'] >= pages:
                break
            body['page'] += 1
        if len(rows) != total:
            raise ExportBlocked('tencent_query_row_count_mismatch')
        seen = set()
        for row in rows:
            r = row.get('report', {})
            day = r.get('date')
            if r.get('account_id') != 74749810 or not isinstance(day, str) or (not start <= day <= through) or (day in seen):
                raise ExportBlocked('tencent_query_account_date_mismatch')
            seen.add(day)
        return rows

    def run(self, *, folder, contract, start, through):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / '.run.lock').open('a') as held:
            try:
                fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ExportBlocked('tencent_job_busy') from None
            return self._run(folder, contract, start, through)

    def _run(self, folder, contract, start, through):
        self.scope=contract.get('product_scope')
        if contract.get('origin') != ORIGIN or contract.get('account_id') != '74749810' or self.scope not in QUERY_PATHS or (contract['query']['path'] != QUERY_PATHS[self.scope]) or (contract['create']['path'] != CREATE) or (contract['poll']['path'] != POLL) or (contract['download']['path'] != DOWNLOAD) or (contract['tasks']['path'] != TASKS):
            raise ExportBlocked('tencent_observed_contract_mismatch')
        if date.fromisoformat(start) > date.fromisoformat(through) or date.fromisoformat(through) >= self.clock().date():
            raise ExportBlocked('tencent_window_not_closed')
        body = deepcopy(contract['create']['body'])
        spec = body['task_spec']
        if body['account_id'] != 74749810 or spec['account_id_list'] != [74749810] or spec['time_line'] != 'REQUEST_TIME':
            raise ExportBlocked('tencent_confirmed_scope_changed')
        if self.scope=='display_plus' and (spec.get('level')!='ADVERTISER' or spec.get('group_by')!=['date']):raise ExportBlocked('tencent_confirmed_display_scope_changed')
        if self.scope=='legacy_search' and spec.get('breakdown')!=['ACCOUNT_REPORT_BY_DATE']:raise ExportBlocked('tencent_confirmed_search_scope_changed')
        old = spec['date_range']
        body['task_name'] = body['task_name'].replace(old['start_date'] + '至' + old['end_date'], start + '至' + through)
        spec['date_range'] = {'start_date': start, 'end_date': through}
        body['task_spec'] = json.dumps(spec, ensure_ascii=False)
        key = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        state_path = folder / 'state.json'
        final = folder / 'native.csv'
        if state_path.exists():
            state = json.loads(state_path.read_text())
            if state['input_key'] != key or state['product_scope']!=self.scope:
                raise ExportBlocked('tencent_job_input_changed')
            if state['phase'] == 'verified':
                if sha(final) != state['file_sha256']:
                    raise ExportBlocked('tencent_verified_file_changed')
                return state
            if not state.get('task_id'):
                candidates = [row for row in self._tasks() if row.get('uid') == 74749810 and row.get('task_id') not in state.get('before_tasks', []) and (row.get('task_type') == contract['tasks']['task_type_numeric']) and str(row.get('task_name', '')).startswith(state['task_name'] + '(') and isinstance(row.get('created_time'), int) and (row['created_time'] >= datetime.fromisoformat(state['started_at']).timestamp() - 5)]
                if len(candidates) > 1:
                    raise ExportBlocked('tencent_new_task_ambiguous')
                if not candidates:
                    raise ExportPending('tencent_create_outcome_unknown_checked_tasks_no_resubmit')
                state.update(task_id=candidates[0]['task_id'], phase='pending_generation')
                write(state_path, state)
        else:
            started = time.monotonic()
            rows = self._query(contract, start, through, folder)
            baseline = self._tasks()
            state = {'schema': 'tencent_request_export.v1', 'input_key': key, 'phase': 'creation_uncertain', 'started_at': self.clock().isoformat(), 'account_id': '74749810', 'product_scope': self.scope, 'window': [start, through], 'submissions': 1, 'before_tasks': [r['task_id'] for r in baseline], 'task_name': body['task_name'], 'query_rows': len(rows), 'timings': {'preflight_seconds': round(time.monotonic() - started, 3)}, 'published': False}
            write(state_path, state)
            started = time.monotonic()
            created = self.post('create', body)
            task = created.get('data', {}).get('task_id')
            if not isinstance(task, int) or task <= 0:
                raise ExportPending('tencent_create_task_id_unconfirmed')
            state.update(task_id=task, phase='pending_generation')
            state['timings']['create_seconds'] = round(time.monotonic() - started, 3)
            write(state_path, state)
        poll_start = time.monotonic()
        while True:
            value = self.post('poll', {'task_id': state['task_id'], 'account_id': 74749810})
            task = value.get('data', {})
            if task.get('task_id') != state['task_id'] or task.get('task_type') != contract['create']['body']['task_type']:
                raise ExportBlocked('tencent_task_identity_mismatch')
            state['native_status'] = {k: task.get(k) for k in ('status', 'result_status', 'created_time', 'end_time')}
            write(state_path, state)
            if task.get('status') == 'TASK_STATUS_COMPLETED' and task.get('result_status') == 'TASK_RESULT_STATUS_SUCCESS' and (task.get('file_id') is not None) and str(task['file_id']):
                break
            if time.monotonic() - poll_start >= self.generation_timeout:
                raise ExportPending('tencent_generation_pending_no_resubmit')
            self.sleep(2)
        elapsed_poll = round(time.monotonic() - poll_start, 3)
        state['timings']['resume_poll_seconds' if 'poll_seconds' in state['timings'] else 'poll_seconds'] = elapsed_poll
        state['phase'] = 'transfer_pending'
        write(state_path, state)
        started = time.monotonic()
        partial = folder / 'native.part'

        query_rows=[]
        for query_path in sorted(folder.glob('query-page-*.json')):
            query_rows+=json.loads(query_path.read_text())['data']['list']
        expected={r['report']['date']:r['report']['cost'] for r in query_rows}
        from decimal import Decimal
        def inspect(path):
            native=inspect_report(path,account_id='74749810',product_scope=self.scope,time_basis='播放口径',start_date=start,through_date=through)
            if native['rows']!=state['query_rows'] or {r['date'] for r in native['rows_data']}!=set(expected):
                raise ExportBlocked('tencent_native_query_row_mismatch')
            if any(Decimal(r['spend'])!=Decimal(expected[r['date']]) for r in native['rows_data']):
                raise ExportBlocked('tencent_native_query_cost_mismatch')
            return native
        if not final.exists():
            if partial.exists():
                try:
                    inspect(partial);partial.replace(final)
                except Exception:
                    partial.rename(folder/f'incomplete-{time.time_ns()}.part')
            if not final.exists():
                self.transfer(task,partial);inspect(partial);partial.replace(final)
        native=inspect(final)
        state['timings']['transfer_and_validation_seconds'] = round(time.monotonic() - started, 3)
        evidence = {'task_id': state['task_id'], 'native_status': state['native_status'], 'timings': state['timings'], 'selected_window': [start, through], 'product_scope': self.scope, 'native': {k: v for k, v in native.items() if k != 'rows_data'}, 'route': 'independent_python_http', 'signed_url_saved': False, 'whole_account_complete': False}
        write(folder / 'evidence.json', evidence)
        inventory = {'as_of_date': self.clock().date().isoformat(), 'captures': [{'source': 'tencent_ads_abroad', 'status': 'downloaded', 'captured_at': self.clock().isoformat(), 'account_ids': ['74749810'], 'selected_window': [start, through], 'native_file': str(final.resolve()), 'sha256': sha(final), 'export_task_id': str(state['task_id']), 'native_format': 'tencent_account_csv', 'product_scope': self.scope, 'time_basis': '播放口径', 'evidence_files': [str((folder / 'evidence.json').resolve())], 'completion': {'verified': True, 'through_date': through, 'basis': 'native_export_window', 'source_scope_complete': native['scope_dates_complete']}}]}
        write(folder / 'raw_inventory.json', inventory)
        if not (folder / 'intake').exists():
            intake(folder / 'raw_inventory.json', folder / 'intake', now=self.clock())
        receipt = folder / 'intake/intake-receipt.json'
        if not receipt.is_file() or json.loads(receipt.read_text())['failed_sources']:
            raise ExportBlocked('tencent_intake_incomplete')
        state.update(phase='verified', file_sha256=sha(final), native=evidence['native'], intake_receipt=str(receipt), whole_account_complete=False)
        write(state_path, state)
        return state

def _brand_proxy_post(client, path, body):
    """POST one observed brand-scope query with the existing dedicated session."""
    auth = private_json(client.paths.root / 'export-auth.json')
    if auth.get('account_id') != '74749810':
        raise ExportBlocked('tencent_auth_account_mismatch')
    part = auth.get('queries', {}).get('legacy_search')
    if not isinstance(part, dict) or part.get('path') != LEGACY_QUERY:
        raise ExportBlocked('tencent_auth_path_mismatch')
    headers = {k: v for k, v in (part.get('headers') or {}).items()
               if not k.startswith(':') and k.lower() not in {
                   'mp-tk', 'cookie', 'content-length', 'accept-encoding'
               }}
    headers['Cookie'] = client._cookie(path)
    url = ORIGIN + path
    request = Request(url, data=json.dumps(body, ensure_ascii=False).encode(),
                      headers=headers, method='POST')
    try:
        with build_opener(
                NoRedirect(),
                HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where()))
        ).open(request, timeout=client.request_timeout) as response:
            raw = response.read(3000001)
        if len(raw) > 3000000:
            raise ExportBlocked('tencent_response_too_large')
        return json.loads(raw)
    except HTTPError as error:
        if error.code == 401:
            raise AuthSessionExpiredError('tencent_http_401') from None
        raise ExportBlocked('tencent_http_' + str(error.code)) from None
    except ExportBlocked:
        raise
    except Exception:
        raise ExportPending('tencent_request_result_unconfirmed') from None


def verify_promotion_scope(workspace, *, contract_path, contract_sha256,
                           start, through, native_files, output_dir, post=None):
    """Reconcile observed promotion query branches against verified native CSVs."""
    try:
        start_date, through_date = date.fromisoformat(start), date.fromisoformat(through)
    except (TypeError, ValueError):
        raise ExportBlocked('tencent_promotion_window_invalid') from None
    if start_date.isoformat() != start or through_date.isoformat() != through or start_date > through_date:
        raise ExportBlocked('tencent_promotion_window_invalid')
    try:
        contract_file = Path(contract_path).resolve(strict=True)
    except OSError:
        raise ExportBlocked('tencent_promotion_contract_missing') from None
    contract_hash = sha(contract_file)
    if not isinstance(contract_sha256, str) or contract_hash != contract_sha256:
        raise ExportBlocked('tencent_promotion_contract_sha256_mismatch')
    try:
        contract = json.loads(contract_file.read_text())
    except (OSError, ValueError):
        raise ExportBlocked('tencent_promotion_contract_invalid') from None

    scopes = {
        'bidding_queries': ['bidding_display', 'bidding_search', 'bidding_search_upgrade'],
        'brand_queries': [
            'brand_touch_contract', 'brand_search_contract', 'brand_content_contract',
        ],
        'additional_brand_queries': [
            'brand_touch_rtb_all_states', 'brand_content_boost_all_created_dates',
        ],
    }
    if not isinstance(contract, dict):
        raise ExportBlocked('tencent_promotion_contract_invalid')
    if (contract.get('schema') != 'tencent_promotion_scope_observed.v2'
            or contract.get('account_id') != '74749810'
            or contract.get('confirmed_required') != ['竞价推广', '品牌推广']
            or contract.get('confirmed_excluded') != ['智能投放']
            or contract.get('ordinary_browser_auth_copied') is not False):
        raise ExportBlocked('tencent_promotion_contract_scope_mismatch')
    observed_window = contract.get('window_observed')
    try:
        if (not isinstance(observed_window, list) or len(observed_window) != 2
                or any(date.fromisoformat(value).isoformat() != value for value in observed_window)
                or date.fromisoformat(observed_window[0]) > date.fromisoformat(observed_window[1])):
            raise ValueError
    except (TypeError, ValueError):
        raise ExportBlocked('tencent_promotion_contract_window_invalid') from None
    query_specs = {}
    for group, names in scopes.items():
        values = contract.get(group)
        if (not isinstance(values, list) or len(values) != len(names)
                or any(not isinstance(item, dict) for item in values)
                or [item.get('scope') for item in values] != names):
            raise ExportBlocked('tencent_promotion_contract_scope_mismatch')
        query_specs.update({item['scope']: item for item in values})
    for scope in ('bidding_display', 'bidding_search_upgrade'):
        filtering = query_specs[scope].get('body', {}).get('filtering', [])
        if not any(item.get('field') == 'adgroup.smart_delivery_platform'
                   and item.get('operator') == 'LESS'
                   and item.get('values') == ['SMART_DELIVERY_PLATFORM_EDITION_SCENE']
                   for item in filtering if isinstance(item, dict)):
            raise ExportBlocked('tencent_promotion_smart_exclusion_missing')

    if not isinstance(native_files, dict) or set(native_files) != {'display_plus', 'legacy_search'}:
        raise ExportBlocked('tencent_promotion_native_export_required')
    native_paths, native_hashes, native_rows = {}, {}, {}
    for product_scope, filename in native_files.items():
        try:
            native_path = Path(filename).resolve(strict=True)
            native = inspect_report(
                native_path, account_id='74749810', product_scope=product_scope,
                time_basis='播放口径', start_date=start, through_date=through,
            )
        except (OSError, ValueError):
            raise ExportBlocked('tencent_promotion_native_export_required') from None
        native_paths[product_scope] = native_path
        native_hashes[product_scope] = sha(native_path)
        native_rows[product_scope] = {
            row['date']: Decimal(row['spend']) for row in native['rows_data']
        }

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    query_dir = output_dir / 'queries'
    query_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = output_dir / 'promotion-scope-check.json'
    receipt = {
        'schema': 'tencent_promotion_scope_check.v1', 'status': 'checking',
        'account_id': '74749810', 'window': [start, through],
        'contract': {'path': str(contract_file), 'sha256': contract_hash},
        'native_files': {scope: {'path': str(path), 'sha256': native_hashes[scope]}
                         for scope, path in native_paths.items()},
        'queries': [], 'known_empty_scopes': [], 'scope_summaries': {},
        'daily_comparison': {},
        'scope_note': 'brand_content_contract_is_a_subset_of_brand_touch_contract_not_additive',
    }
    write(receipt_path, receipt)

    def fail(code, scope=None):
        failure = {'code': code}
        if scope is not None:
            failure['scope'] = scope
        receipt.update(status='blocked', failure=failure)
        write(receipt_path, receipt)
        raise ExportBlocked(code)

    def redact(value):
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                normalized = key.lower().replace('-', '_')
                result[key] = ('[redacted]' if any(secret in normalized for secret in (
                    'token', 'cookie', 'auth', 'secret', 'signature', 'mp_tk'))
                               else redact(item))
            return result
        if isinstance(value, list):
            return [redact(item) for item in value]
        return value

    def query(path, body):
        if post is not None:
            return post(path, body)
        if path == QUERY:
            client.scope = 'display_plus'
            return client._post('query', body)
        if path == LEGACY_QUERY:
            client.scope = 'legacy_search'
            return client._post('query', body)
        if path.startswith('/bff/proxy/'):
            return _brand_proxy_post(client, path, body)
        raise ExportBlocked('tencent_promotion_contract_path_unrecognized')

    def query_rows(scope, values, ledger_keys):
        branch_rows = {}
        branch_sum = Decimal('0')
        for row in values:
            if not isinstance(row, dict) or not isinstance(row.get('report'), dict):
                fail('tencent_promotion_query_row_invalid', scope)
            report = row['report']
            if report.get('account_id') is not None and str(report['account_id']) != '74749810':
                fail('tencent_promotion_query_account_mismatch', scope)
            day = report.get('date')
            if not isinstance(day, str):
                fail('tencent_promotion_query_date_invalid', scope)
            try:
                if date.fromisoformat(day).isoformat() != day or not start <= day <= through:
                    raise ValueError
                raw_cost = report.get('cost')
                if raw_cost is None or (isinstance(raw_cost, str) and not raw_cost.strip()):
                    raise InvalidOperation
                amount = Decimal(str(raw_cost))
                if not amount.is_finite():
                    raise InvalidOperation
            except (TypeError, ValueError, InvalidOperation):
                fail('tencent_promotion_query_date_or_cost_invalid', scope)
            group = ('adgroup' if scope.startswith('bidding_')
                     or scope in additional_brand_scopes else 'campaign')
            entity_field = group + '_id'
            entity = report.get(entity_field)
            if entity is None:
                nested = row.get(group)
                entity = nested.get(entity_field) if isinstance(nested, dict) else row.get(entity_field)
            if entity is None or not str(entity).strip():
                fail('tencent_promotion_query_entity_id_missing', scope)
            key = (day, group, str(entity))
            if key in branch_rows:
                fail('tencent_promotion_duplicate_date_entity', scope)
            branch_rows[key] = amount
            branch_sum += amount
        receipt['scope_summaries'][scope] = {
            'row_count': len(values), 'total': str(branch_sum),
            'ledger': ledger_keys.get(scope),
            'native_product_scope': native_scope_for_scope.get(scope),
            'included_in_ledger': scope in ledger_keys,
            'nonempty_action': ('included_in_native_ledger' if scope in ledger_keys
                                else 'verified_subset_not_added'
                                if scope == 'brand_content_contract'
                                else 'not_in_native_ledger'),
        }
        return branch_rows, branch_sum

    client = TencentExport(workspace)
    ledger_rows = {'v3': {}, 'legacy': {}}
    ledger_daily = {'v3': defaultdict(Decimal), 'legacy': defaultdict(Decimal)}
    branch_rows_by_scope = {}
    additional_brand_scopes = set(scopes['additional_brand_queries'])
    ledger_for_scope = {
        'bidding_display': 'v3', 'bidding_search_upgrade': 'v3',
        'bidding_search': 'legacy', 'brand_touch_contract': 'legacy',
        'brand_search_contract': 'legacy',
        'brand_touch_rtb_all_states': 'v3',
        'brand_content_boost_all_created_dates': 'legacy',
    }
    native_scope_for_scope = {
        'bidding_display': 'display_plus', 'bidding_search_upgrade': 'display_plus',
        'bidding_search': 'legacy_search', 'brand_touch_contract': 'legacy_search',
        'brand_search_contract': 'legacy_search', 'brand_content_contract': 'legacy_search',
        'brand_touch_rtb_all_states': 'display_plus',
        'brand_content_boost_all_created_dates': 'legacy_search',
    }
    for scope in [name for names in scopes.values() for name in names]:
        spec = query_specs[scope]
        query_path = spec.get('path')
        body = deepcopy(spec.get('body'))
        parsed_path = urlsplit(query_path) if isinstance(query_path, str) else None
        if (parsed_path is None or not query_path.startswith('/') or parsed_path.scheme
                or parsed_path.netloc or parsed_path.query or not isinstance(body, dict)
                or body.get('account_id_list') != [74749810]
                or body.get('date_range') != {
                    'start_date': observed_window[0], 'end_date': observed_window[1]
                }
                or type(body.get('page')) is not int or body['page'] != 1
                or type(body.get('page_size')) is not int or body['page_size'] != 20
                or body.get('time_line') != 'REQUEST_TIME'):
            fail('tencent_promotion_contract_query_scope_mismatch', scope)
        if query_path not in (QUERY, LEGACY_QUERY) and not query_path.startswith('/bff/proxy/'):
            fail('tencent_promotion_contract_path_unrecognized', scope)
        if scope in additional_brand_scopes:
            fields = body.get('fields')
            required_fields = {'report.date', 'report.cost', 'report.adgroup_id'}
            filters = body.get('filtering')

            report_grain_valid = isinstance(fields, list) and required_fields.issubset(fields)
            if scope == 'brand_touch_rtb_all_states':
                report_grain_valid = (
                    report_grain_valid
                    and query_path == QUERY
                    and body.get('level') == 'ADGROUP'
                    and body.get('group_by') == ['date', 'adgroup_id']
                    and filters == [{'field': 'adgroup.brand_ad_type',
                                     'operator': 'EQUALS',
                                     'values': ['BRAND_AD_TYPE_RTB']}]
                )
            else:
                report_grain_valid = (
                    report_grain_valid
                    and query_path == LEGACY_QUERY
                    and body.get('breakdown') == ['ADGROUP_REPORT_BY_DATE_AND_ADGROUP']
                    and filters == [
                        {'field': 'campaign.campaign_type', 'operator': 'EQUALS',
                         'values': ['CAMPAIGN_TYPE_CONTENT_PROMOTION']},
                        {'field': 'adgroup.buying_type', 'operator': 'EQUALS',
                         'values': ['BUYINGTYPE_CONTRACT']},
                    ]
                )
            if not report_grain_valid:
                fail('tencent_promotion_contract_report_grain_mismatch', scope)
        body['date_range'] = {'start_date': start, 'end_date': through}
        safe_body = redact(body)
        query_record = {
            'scope': scope, 'path': query_path, 'request_body': safe_body,
            'request_sha256': hashlib.sha256(json.dumps(
                {'path': query_path, 'body': safe_body}, ensure_ascii=False,
                sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            'pages': [],
        }
        receipt['queries'].append(query_record)
        scope_rows, first_totals = [], None
        page = 1
        while True:
            page_body = deepcopy(body)
            page_body['page'] = page
            try:
                response = post(query_path, page_body) if post is not None else query(
                    query_path, page_body)
            except (AuthSessionMissingError, AuthSessionExpiredError,
                    ExportBlocked, ExportPending) as error:
                receipt.update(status='blocked', failure={
                    'scope': scope, 'error_type': type(error).__name__,
                })
                write(receipt_path, receipt)
                raise
            except Exception as error:
                receipt.update(status='blocked', failure={
                    'scope': scope, 'error_type': type(error).__name__,
                })
                write(receipt_path, receipt)
                raise ExportPending('tencent_request_result_unconfirmed') from None

            page_file = query_dir / f'{scope}-page-{page:03d}.json'
            write(page_file, redact(response))
            page_sha = sha(page_file)
            data = response.get('data') if isinstance(response, dict) else None
            info = data.get('page_info') if isinstance(data, dict) else None
            rows = data.get('list') if isinstance(data, dict) else None
            page_record = {
                'page': page, 'path': str(page_file.resolve()), 'sha256': page_sha,
                'row_count': len(rows) if isinstance(rows, list) else None,
                'page_info': ({key: info[key] for key in (
                    'page', 'page_size', 'total_number', 'total_page'
                ) if type(info.get(key)) is int} if isinstance(info, dict) else None),
            }
            query_record['pages'].append(page_record)
            receipt['files'] = receipt.get('files', []) + [
                {'path': str(page_file.resolve()), 'sha256': page_sha}
            ]
            if (isinstance(response, dict)
                    and type(response.get('code')) is int and response['code'] == 4501
                    and type(response.get('ret')) is int and response['ret'] == 4501):
                receipt.update(status='blocked', failure={
                    'scope': scope, 'error_type': 'TencentLoginRequired',
                })
                write(receipt_path, receipt)
                raise TencentLoginRequired()
            if not _normal_query_succeeded(response):
                fail('tencent_api_rejected', scope)
            if (not isinstance(info, dict) or not isinstance(rows, list)
                    or any(type(info.get(key)) is not int for key in (
                        'page', 'page_size', 'total_number', 'total_page'))
                    or info['page'] != page or info['page_size'] != body['page_size']
                    or not 0 <= info['total_number'] <= 10000
                    or not 0 <= info['total_page'] <= 500):
                fail('tencent_promotion_query_page_schema_changed', scope)
            totals = (info['total_number'], info['total_page'])
            if first_totals is None:
                first_totals = totals
            elif totals != first_totals:
                fail('tencent_promotion_query_changed_during_paging', scope)
            if info['total_number'] == 0:
                if info['total_page'] != 0 or rows:
                    fail('tencent_promotion_query_page_schema_changed', scope)
                receipt['known_empty_scopes'].append(scope)
                break
            if info['total_page'] == 0:
                fail('tencent_promotion_query_page_schema_changed', scope)
            scope_rows.extend(rows)
            if page >= info['total_page']:
                if len(scope_rows) != info['total_number']:
                    fail('tencent_promotion_query_row_count_mismatch', scope)
                break
            page += 1
        branch_rows, branch_sum = query_rows(scope, scope_rows, ledger_for_scope)
        branch_rows_by_scope[scope] = branch_rows
        if scope in ledger_for_scope:
            ledger = ledger_for_scope[scope]
            for key, amount in branch_rows.items():
                if any(key in rows for rows in ledger_rows.values()):
                    fail('tencent_promotion_duplicate_date_entity', scope)
                ledger_rows[ledger][key] = amount
                ledger_daily[ledger][key[0]] += amount
        write(receipt_path, receipt)

    for key, amount in branch_rows_by_scope.get('brand_content_contract', {}).items():
        if branch_rows_by_scope.get('brand_touch_contract', {}).get(key) != amount:
            fail('tencent_promotion_brand_subset_mismatch', 'brand_content_contract')
    receipt['scope_summaries']['brand_content_contract'].update(
        included_in_ledger=False, nonempty_action='verified_subset_not_added',
        subset_of='brand_touch_contract')

    comparisons = {}
    for ledger, product_scope in (('v3', 'display_plus'), ('legacy', 'legacy_search')):
        query_daily = dict(sorted(ledger_daily[ledger].items()))
        native_daily = native_rows[product_scope]
        matches = (query_daily.keys() == native_daily.keys()
                   and all(query_daily[day] == native_daily[day] for day in query_daily))
        comparisons[ledger] = {
            'product_scope': product_scope,
            'query_daily': {day: str(amount) for day, amount in query_daily.items()},
            'native_daily': {day: str(amount) for day, amount in sorted(native_daily.items())},
            'query_total': str(sum(query_daily.values(), Decimal('0'))),
            'native_total': str(sum(native_daily.values(), Decimal('0'))),
            'matches_exactly': matches,
        }
    receipt['daily_comparison'] = comparisons
    receipt['status'] = 'verified'
    if not all(value['matches_exactly'] for value in comparisons.values()):
        fail('tencent_promotion_native_export_required')
    write(receipt_path, receipt)
    receipt_file = {'path': str(receipt_path.resolve()), 'sha256': sha(receipt_path)}
    files = [*receipt.get('files', []), receipt_file]
    return {
        'status': 'verified', 'receipt': receipt_file,
        'files': files, 'scope_summaries': receipt['scope_summaries'],
        'daily_comparison': comparisons,
    }

def save_login(workspace, *, inject_saved_state=True):
    """Refresh the normal Tencent session in one dedicated browser context."""
    from playwright.sync_api import sync_playwright
    import os
    paths = AuthSessionPaths(Path(workspace), 'tencent_ads')
    auth_path = paths.root / 'export-auth.json'
    if not auth_path.is_file():
        raise ExportBlocked('tencent_initial_protocol_capture_required')
    auth = private_json(auth_path)
    captured = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=False)
        try:
            context = browser.new_context(accept_downloads=True)
            if inject_saved_state:
                if paths.cookies.is_file():
                    context.add_cookies(private_json(paths.cookies))
                if paths.local_storage.is_file():
                    storage = private_json(paths.local_storage)
                    context.add_init_script('if(location.origin==="https://ad.qq.com"){const saved=' + json.dumps(storage) + ';for(const [key,value] of Object.entries(saved))localStorage.setItem(key,value)}')
            page = context.new_page()

            def finished(request):
                if urlsplit(request.url).hostname != 'ad.qq.com' or urlsplit(request.url).path not in QUERY_PATHS.values():
                    return
                try:
                    body = json.loads(request.post_data or '{}')
                    response = request.response()
                    response_value = response.json() if response is not None else None
                    if body.get('account_id_list') == [74749810] and _normal_query_succeeded(response_value):
                        headers = request.all_headers()
                        query = _auth_query_values(request.url)
                        path = urlsplit(request.url).path
                        captured.append((path, headers, query))
                except Exception:
                    pass
            page.on('requestfinished', finished)
            page.goto(ORIGIN + '/atlas/74749810/report/index?tab=account', wait_until='domcontentloaded')
            print('腾讯专用窗口正在验证登录；若显示登录页，请用可访问74749810的原账号正常登录，不注册新账户。', flush=True)
            page.wait_for_function('document.body && document.body.innerText.includes("ID:74749810") && document.body.innerText.includes("北京新东方前途出国咨询有限公司")', timeout=600000)
            cookies = context.cookies([ORIGIN])
            local_storage = page.evaluate('Object.fromEntries(Object.entries(localStorage))')
            if not cookies or not isinstance(local_storage, dict):
                raise ExportBlocked('tencent_login_session_state_empty_or_invalid')
            # The exact account and company are verified above. Persist this context
            # before report-scope checks so a later UI/query failure cannot discard login.
            write_auth_session('tencent_ads', cookies=cookies,
                               local_storage=local_storage, paths=paths)
            try:
                if _query_capture_count(captured, 'display_plus') == 0:
                    page.reload(wait_until='domcontentloaded')
                    if not _wait_for_query_scope(page, captured, 'display_plus'):
                        raise ExportBlocked('tencent_display_query_not_verified')
                previous_legacy_queries = _query_capture_count(captured, 'legacy_search')
                _open_legacy_search(page)
                if not _wait_for_query_scope(page, captured, 'legacy_search', after=previous_legacy_queries):
                    raise ExportBlocked('tencent_legacy_search_query_not_verified')
                if not _required_login_scopes_captured(captured):
                    raise ExportBlocked('tencent_login_scope_query_not_verified')
                has_g_tk = any(headers.get('g-tk') or _one_auth_value(query, 'g_tk')
                                for _path, headers, query in captured)
                if not has_g_tk:
                    raise ExportBlocked('tencent_login_query_not_verified')
                _refresh_export_auth(auth, captured)
            except ExportBlocked as error:
                raise TencentLoginRecoveryUnverified(
                    f'{error}_session_saved'
                ) from None
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=paths.root, prefix='.auth-', delete=False) as handle:
                temporary = Path(handle.name)
                try:
                    os.fchmod(handle.fileno(), 384)
                    json.dump(auth, handle, ensure_ascii=False)
                    handle.flush()
                    os.fsync(handle.fileno())
                    temporary.replace(auth_path)
                finally:
                    temporary.unlink(missing_ok=True)
        finally:
            browser.close()

def run_authenticated(client, *, login=None, **job):
    try:
        return client.run(**job)
    except (AuthSessionMissingError, AuthSessionExpiredError, TencentLoginRequired):
        (login or save_login)(client.paths.repo_root)
        return client.run(**job)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('workspace', 'contract', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('start', 'through'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    try:
        result = run_authenticated(TencentExport(args.workspace), folder=args.output_dir, contract=json.loads(args.contract.read_text()), start=args.start, through=args.through)
        print(json.dumps({k: result[k] for k in ('phase', 'task_id', 'native', 'timings', 'file_sha256', 'intake_receipt', 'whole_account_complete')}, ensure_ascii=False))
        return 0
    except (AuthSessionMissingError, AuthSessionExpiredError):
        print(json.dumps({'status': 'login_required', 'reason': 'tencent_normal_login_required'}))
        return 2
    except (ExportBlocked, ExportPending) as error:
        print(json.dumps({'status': 'pending' if isinstance(error, ExportPending) else 'blocked', 'reason': str(error)}))
        return 2
if __name__ == '__main__':
    raise SystemExit(main())
