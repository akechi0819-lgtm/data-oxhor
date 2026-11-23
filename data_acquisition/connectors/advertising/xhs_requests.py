"""XHS native export using observed requests and protected project auth state.

No browser launch or login extraction. URLs/auth headers never enter receipts.
"""
from __future__ import annotations
import argparse, json, hashlib, time, re, fcntl, ssl
import certifi
from datetime import datetime, timedelta, date
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler
from urllib.parse import urlsplit
from urllib.error import HTTPError
from data_acquisition.auth.auth_sessions import AuthSessionPaths, AuthSessionMissingError, AuthSessionExpiredError
from data_acquisition.connectors.advertising.native_exports import inspect_xhs
from data_acquisition.jobs.intake_advertising import intake
ORIGIN = 'https://mcc.xiaohongshu.com'
CREATE = '/api/mcc/board/rtb_metrics/download'
TASKS = '/api/edith/task/list'
TZ = ZoneInfo('Asia/Shanghai')
IDENTITY = ('accountOrgName', 'taskTypeName', 'platformName')

class ExportPending(RuntimeError):
    pass

class ExportBlocked(RuntimeError):
    pass

def now():
    return datetime.now(TZ)

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def write(path, value):
    path = Path(path)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)

# Authentication redirects must not forward the Cookie header.
class NoRedirect(HTTPRedirectHandler):

    def redirect_request(self, *args, **kwargs):
        return None

class XHSExport:

    def __init__(self, *, cookie_file=None, request_timeout=30, generation_timeout=900, transfer_timeout=900, post=None, transfer=None, sleep=time.sleep, clock=now):
        self.cookie_file = Path(cookie_file) if cookie_file else None
        self.request_timeout = request_timeout
        self.generation_timeout = generation_timeout
        self.transfer_timeout = transfer_timeout
        self.post = post or self._post
        self.transfer = transfer or self._transfer
        self.sleep = sleep
        self.clock = clock

    def _cookie(self, path):
        if self.cookie_file is None or not self.cookie_file.is_file():
            raise AuthSessionMissingError('xhs_auth_state_missing')
        if self.cookie_file.stat().st_mode & 63:
            raise ExportBlocked('xhs_auth_file_not_private')
        try:
            cookies = json.loads(self.cookie_file.read_text())
        except Exception:
            raise ExportBlocked('xhs_auth_state_invalid') from None
        if not isinstance(cookies, list):
            raise ExportBlocked('xhs_auth_state_invalid')
        pairs = []
        scoped = expired = 0
        for c in cookies:
            if not isinstance(c, dict):
                raise ExportBlocked('xhs_auth_state_invalid')
            domain = str(c.get('domain', '')).lstrip('.').lower()
            cp = c.get('path', '/')
            expiry = c.get('expires', c.get('expirationDate', -1))
            if not domain or not ('mcc.xiaohongshu.com' == domain or 'mcc.xiaohongshu.com'.endswith('.' + domain)):
                continue
            if domain != 'xiaohongshu.com' and (not domain.endswith('.xiaohongshu.com')):
                continue
            if not isinstance(cp, str) or not (cp == '/' or path == cp or path.startswith(cp.rstrip('/') + '/')):
                continue
            scoped += 1
            try:
                if 0 <= float(expiry) <= time.time():
                    expired += 1
                    continue
            except (TypeError, ValueError):
                continue
            name, value = (c.get('name'), c.get('value'))
            if not isinstance(name, str) or not re.fullmatch("[!#$%&\\'*+.^_`|~0-9A-Za-z-]+", name) or (not isinstance(value, str)) or any((x in value for x in '\r\n;')):
                raise ExportBlocked('xhs_auth_cookie_invalid')
            pairs.append(name + '=' + value)
        if not pairs:
            if scoped and expired == scoped:
                raise AuthSessionExpiredError('xhs_auth_cookies_expired')
            raise ExportBlocked('xhs_auth_wrong_domain_or_path')
        return '; '.join(pairs)

    def _post(self, path, body):
        request = Request(ORIGIN + path, data=json.dumps(body).encode(), method='POST', headers={'Content-Type': 'application/json', 'Origin': ORIGIN, 'Referer': ORIGIN + '/', 'Cookie': self._cookie(path)})
        try:
            with build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where()))).open(request, timeout=self.request_timeout) as response:
                result = json.loads(response.read())
        except HTTPError as error:
            if error.code == 401:
                raise AuthSessionExpiredError('xhs_http_401_login_required') from None
            raise ExportBlocked('xhs_http_' + str(error.code)) from None
        except ExportBlocked:
            raise
        except Exception:
            raise ExportPending('xhs_request_result_unconfirmed') from None
        if result.get('code') != 0 or result.get('success') is not True:
            raise ExportBlocked('xhs_api_rejected')
        return result

    def _transfer(self, url, path):
        target = urlsplit(url)
        if target.scheme != 'https' or not target.hostname or target.username or target.password:
            raise ExportBlocked('xhs_download_url_not_https')
        # Signed file URL stays in memory; storage receives no MCC auth headers.
        started = time.monotonic()
        try:
            with build_opener(HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where()))).open(Request(url, method='GET'), timeout=self.request_timeout) as response, path.open('xb') as out:
                while True:
                    if time.monotonic() - started > self.transfer_timeout:
                        raise ExportPending('xhs_transfer_deadline_pending')
                    chunk = response.read(262144)
                    if not chunk:
                        break
                    out.write(chunk)
        except ExportPending:
            raise
        except Exception:
            raise ExportPending('xhs_transfer_result_unconfirmed') from None

    def _inspect(self, path, start, through, expected, excluded=()):
        with path.open('rb') as handle:
            return inspect_xhs(handle, date.fromisoformat(start), date.fromisoformat(through), expected, excluded)

    def _tasks(self, body):
        data = self.post(TASKS, body).get('data', {})
        rows = data.get('dataList')
        if not isinstance(rows, list):
            raise ExportBlocked('xhs_task_list_schema_changed')
        return rows

    def run(self, *, folder, contract, verification, start, through):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / '.run.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ExportBlocked('xhs_job_already_running') from None
            return self._run(folder=folder, contract=contract, verification=verification, start=start, through=through)

    def _run(self, *, folder, contract, verification, start, through):
        folder = Path(folder)
        state_path = folder / 'state.json'
        body = dict(contract['export']['body'])
        body.update(timeStart=start, timeEnd=through)
        if contract['origin'] != ORIGIN or contract['export']['path'] != CREATE or contract['tasks']['path'] != TASKS or (body['period'] != 'day'):
            raise ExportBlocked('xhs_observed_contract_mismatch')
        if date.fromisoformat(start) > date.fromisoformat(through) or date.fromisoformat(through) >= self.clock().date():
            raise ExportBlocked('xhs_window_not_closed')
        key = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        expected = verification['account_ids']
        excluded = verification.get('excluded_account_ids', [])
        if (not isinstance(excluded, list) or any(not isinstance(a, str) or not a.isdigit() for a in excluded)
                or len(set(excluded)) != len(excluded) or set(excluded) & set(expected)):
            raise ExportBlocked('xhs_excluded_account_ids_invalid')
        identity = verification.get('organization_identity')
        if (not isinstance(identity, dict) or set(identity) != set(IDENTITY)
                or any(not isinstance(v, str) or not v for v in identity.values())
                or verification.get('account_org_code') != body.get('accountOrgCode')):
            raise ExportBlocked('xhs_confirmed_organization_scope_missing_or_changed')
        task_body = contract['tasks']['body']
        final = folder / 'native.xlsx'
        if state_path.exists():
            state = json.loads(state_path.read_text())
            if state['input_key'] != key or state['expected_accounts'] != expected or state['match'] != identity:
                raise ExportBlocked('xhs_job_input_changed')
            if state['phase'] == 'verified':
                if sorted(excluded) != state.get('native', {}).get('excluded_account_ids', []):
                    raise ExportBlocked('xhs_verified_exclusion_scope_changed')
                if sha(final) != state['file_sha256']:
                    raise ExportBlocked('xhs_verified_file_changed')
                return state
        else:
            if set((p.name for p in folder.iterdir())) - {'.run.lock'}:
                raise ExportBlocked('xhs_unowned_output_directory')
            baseline = self._tasks(task_body)
            if not any(all(row.get(k) == v for k, v in identity.items()) for row in baseline):
                raise ExportBlocked('xhs_confirmed_organization_not_in_task_list')
            state = {'schema': 'xhs_request_export.v1', 'input_key': key, 'expected_accounts': expected, 'phase': 'creation_uncertain', 'started_at': self.clock().isoformat(), 'before': [r['code'] for r in baseline], 'match': dict(identity), 'submissions': 1, 'timings': {}, 'published': False}
            write(state_path, state)
            t = time.monotonic()
            try:
                self.post(CREATE, body)
                state['create_acknowledged'] = True
            except (ExportPending, ExportBlocked):
                state['create_acknowledged'] = False
            state['timings']['create_seconds'] = round(time.monotonic() - t, 3)
            write(state_path, state)
        # Resume the same uncertain task; never reissue CREATE from this job.
        while True:
            rows = self._tasks(task_body)
            if state.get('task_id'):
                matches = [r for r in rows if r.get('code') == state['task_id']]
            else:
                matches = []
                for row in rows:
                    if row.get('code') in state['before'] or not all((row.get(k) == v for k, v in state['match'].items())):
                        continue
                    try:
                        created = datetime.strptime(row['createTime'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=TZ)
                    except (ValueError, KeyError):
                        continue
                    if created >= datetime.fromisoformat(state['started_at']) - timedelta(seconds=5):
                        matches.append(row)
            if len(matches) > 1:
                raise ExportBlocked('xhs_new_task_ambiguous')
            task = matches[0] if matches else None
            if task:
                if not all((task.get(k) == v for k, v in state['match'].items())):
                    raise ExportBlocked('xhs_task_identity_changed')
                state['task_id'] = task['code']
                state['native_status'] = {k: task.get(k) for k in ['taskResult', 'taskProgress', 'taskProgressValue', 'createTime', 'endTime']}
                write(state_path, state)
                ready = task.get('taskResult') == 1 and task.get('taskProgress') == '下载完成' and (task.get('taskProgressValue') == 2) and isinstance(task.get('downloadFile'), str) and bool(task['downloadFile'])
                if ready:
                    break
            state['phase'] = 'pending_generation'
            write(state_path, state)
            if (self.clock() - datetime.fromisoformat(state['started_at'])).total_seconds() >= self.generation_timeout:
                raise ExportPending('xhs_generation_pending_no_resubmit')
            self.sleep(2)
        state['phase'] = 'transfer_pending'
        write(state_path, state)
        t = time.monotonic()
        partial = folder / 'native.part'
        if not final.exists():
            if partial.exists():
                try:
                    self._inspect(partial, start, through, expected, excluded)
                    partial.replace(final)
                except Exception:
                    partial.rename(folder / ('incomplete-' + str(time.time_ns()) + '.part'))
            if not final.exists():
                self.transfer(task['downloadFile'], partial)
                self._inspect(partial, start, through, expected, excluded)
                partial.replace(final)
        native = self._inspect(final, start, through, expected, excluded)
        state['timings']['transfer_and_validation_seconds'] = round(time.monotonic() - t, 3)
        try:
            state['timings']['server_generation_seconds'] = (datetime.strptime(task['endTime'], '%Y-%m-%d %H:%M:%S') - datetime.strptime(task['createTime'], '%Y-%m-%d %H:%M:%S')).total_seconds()
        except (KeyError, ValueError):
            pass
        evidence = folder / 'evidence.json'
        write(evidence, {'task_id': state['task_id'], 'match': state['match'], 'native_status': state['native_status'], 'timings': state['timings'], 'window': [start, through], 'native': native, 'route': 'observed_http_requests', 'signed_url_saved': False})
        inv = folder / 'raw_inventory.json'
        write(inv, {'as_of_date': self.clock().date().isoformat(), 'captures': [{'source': 'xhs', 'status': 'downloaded', 'captured_at': self.clock().isoformat(), 'account_ids': native['account_ids'], 'selected_window': [start, through], 'native_file': str(final.resolve()), 'sha256': sha(final), 'export_task_id': state['task_id'], 'evidence_files': [str(evidence.resolve())], 'completion': {'verified': True, 'through_date': through, 'basis': 'native_export_window'}}]})
        receipt = folder / 'intake/intake-receipt.json'
        if not (folder / 'intake').exists():
            intake(inv, folder / 'intake', now=self.clock())
        if not receipt.is_file() or json.loads(receipt.read_text())['failed_sources']:
            raise ExportBlocked('xhs_intake_incomplete')
        state.update(phase='verified', file_sha256=sha(final), native=native, intake_receipt=str(folder / 'intake/intake-receipt.json'))
        write(state_path, state)
        return state

def build_candidate(folder, mapping_manifest, *, native_file, evidence_file,
                    captured_at, start, through, expected_accounts, excluded_account_ids=()):
    """Create a source fragment for full_daily, keeping formal registration read-only."""
    from dashboard_product.management.candidate_sources import load_candidate_sources
    folder = Path(folder).resolve(strict=True)
    mapping_manifest = Path(mapping_manifest).resolve(strict=True)
    native_file = Path(native_file).resolve(strict=True)
    evidence_file = Path(evidence_file).resolve(strict=True)
    if (mapping_manifest.is_relative_to(folder) or not native_file.is_relative_to(folder)
            or not evidence_file.is_relative_to(folder)):
        raise ExportBlocked('xhs_candidate_paths_not_isolated')
    mapping_raw = mapping_manifest.read_bytes()
    entries = [item for item in json.loads(mapping_raw)['sources']
               if item.get('kind') == 'xhs_mcc_daily']
    if len(entries) != 1:
        raise ExportBlocked('xhs_confirmed_mapping_missing_or_ambiguous')
    native = XHSExport()._inspect(native_file, start, through, expected_accounts, excluded_account_ids)
    entry = {**entries[0], 'path':str(native_file), 'sha256':sha(native_file),
             'start_date':start, 'end_date':through}
    entry.pop('excluded_account_ids', None)
    entry.pop('excluded_zero_account_ids', None)
    if native['excluded_account_ids']:
        entry['excluded_account_ids'] = native['excluded_account_ids']
    if native['extra_zero_account_ids']:
        entry['excluded_zero_account_ids'] = native['extra_zero_account_ids']
    manifest = folder/'candidate-sources.json'
    write(manifest, {'sources':[entry]})
    parsed = load_candidate_sources(manifest)
    actual_accounts = {str(row['account_id']) for row in parsed['rows']}
    if actual_accounts != set(expected_accounts):
        raise ExportBlocked('xhs_candidate_parsed_scope_mismatch')
    if hashlib.sha256(mapping_manifest.read_bytes()).hexdigest() != hashlib.sha256(mapping_raw).hexdigest():
        raise ExportBlocked('xhs_confirmed_mapping_changed')
    source = {'source_id':'xhs', 'status':'success', 'captured_at':captured_at,
              'start_date':start, 'through_date':through,
              'account_ids':native['account_ids'],
              'files':[{'path':str(native_file), 'sha256':sha(native_file)}],
              'evidence':{'path':str(evidence_file), 'sha256':sha(evidence_file)},
              'completion':{'complete':True, 'through_date':through,
                            'basis':'native_export_window'}}
    capture = {'manifest_path':str(manifest), 'sources':[source]}
    write(folder/'capture.json', capture)
    write(folder/'candidate-validation.json', {
        'source_id':entry['source_id'], 'native':native, 'rows':len(parsed['rows']),
        'mapping_manifest_sha256':hashlib.sha256(mapping_raw).hexdigest(),
        'full_source_scope_complete':False, 'production_ready':False, 'published':False})
    return {'manifest':str(manifest), 'capture':str(folder/'capture.json')}


def save_login(workspace, *, confirm=input):
    """One normal XHS login in a dedicated script context; no Chrome attachment.

    Uses the same installed Playwright and writer pattern as BI. This must be
    invoked explicitly: it opens a window and waits for the user to finish login.
    Only the XHS site's applicable cookies/localStorage are saved.
    """
    from playwright.sync_api import sync_playwright
    from data_acquisition.auth.auth_sessions import write_auth_session
    paths = AuthSessionPaths(Path(workspace), 'xhs')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=False)
        try:
            context = browser.new_context(accept_downloads=True)
            if paths.cookies.is_file():
                context.add_cookies(json.loads(paths.cookies.read_text()))
            if paths.local_storage.is_file():
                storage = json.loads(paths.local_storage.read_text())
                context.add_init_script('if(location.origin===' + json.dumps(ORIGIN) + '){const saved=' + json.dumps(storage) + ';for(const [key,value] of Object.entries(saved))localStorage.setItem(key,value)}')
            page = context.new_page()
            page.goto(ORIGIN, wait_until='domcontentloaded')
            confirm('在新开的小红书专用窗口完成正常登录后，回到终端按回车继续。')
            if urlsplit(page.url).scheme != 'https' or urlsplit(page.url).netloc != 'mcc.xiaohongshu.com':
                raise ExportBlocked('xhs_login_not_on_expected_origin')
            verified = page.evaluate('''async ({path,body}) => {
                const response = await fetch(path, {method:'POST',credentials:'same-origin',
                    headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(30000)});
                const value = await response.json();
                return {http:response.status,code:value.code,success:value.success};
            }''', {'path':TASKS,'body':{'taskTypes':[],'platforms':[],'pageIndex':1,'pageSize':20,'entryType':0}})
            if verified != {'http':200,'code':0,'success':True}:
                raise ExportBlocked('xhs_login_task_query_not_verified')
            cookies = context.cookies([ORIGIN])
            storage = page.evaluate('Object.fromEntries(Object.entries(localStorage))')
            if not cookies or not isinstance(storage, dict):
                raise ExportBlocked('xhs_login_state_empty_or_invalid')
            write_auth_session('xhs', cookies=cookies, local_storage=storage, paths=paths)
            return {'service':'xhs','credentials_written':True,'login_task_query_verified':True}
        finally:
            browser.close()


def run_authenticated(client, workspace, *, login=None, **job):
    """Cookie-first; one login only for missing/confirmed unauthenticated state.

    Retrying this same job preserves any unknown create outcome and task binding.
    Permission, business, schema and timeout errors do not trigger login.
    """
    try:
        return client.run(**job)
    except (AuthSessionMissingError, AuthSessionExpiredError):
        (login or save_login)(workspace)
        return client.run(**job)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace', type=Path, required=True)
    p.add_argument('--contract', type=Path, required=True)
    p.add_argument('--verification', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--start', required=True)
    p.add_argument('--through', required=True)
    p.add_argument('--mapping-manifest', type=Path)
    p.add_argument('--login', action='store_true', help='Login recovery is cookie-first and automatic; valid saved state never opens a window')
    a = p.parse_args()
    try:
        client = XHSExport(cookie_file=AuthSessionPaths(a.workspace, 'xhs').cookies)
        r = run_authenticated(client, a.workspace, folder=a.output_dir, contract=json.loads(a.contract.read_text()), verification=json.loads(a.verification.read_text()), start=a.start, through=a.through)
        candidate = build_candidate(a.output_dir, a.mapping_manifest or a.workspace/'Input/AdvertisingCosts/sources.json', native_file=a.output_dir/'native.xlsx', evidence_file=a.output_dir/'evidence.json', captured_at=r['started_at'], start=a.start, through=a.through, expected_accounts=r['expected_accounts'], excluded_account_ids=r['native'].get('excluded_account_ids', []))
        print(json.dumps({**{k: r[k] for k in ['phase', 'task_id', 'native', 'timings', 'intake_receipt']}, 'candidate':candidate}, ensure_ascii=False))
        return 0
    except (AuthSessionMissingError, AuthSessionExpiredError):
        print(json.dumps({'status':'login_required','reason':'xhs_auth_not_recovered_after_one_login'}))
        return 2
    except (ExportBlocked, ExportPending) as e:
        print(json.dumps({'status': 'pending' if isinstance(e, ExportPending) else 'blocked', 'reason': str(e)}, ensure_ascii=False))
        return 2
if __name__ == '__main__':
    raise SystemExit(main())
