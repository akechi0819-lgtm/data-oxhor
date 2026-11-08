"""SEM whole-workbook export using the current model and authenticated requests.

The headless page supplies DingTalk's own Excel-compatible serialization and
request authentication. No menu, click, historical payload, or download event is
used. The protocol was verified against flex-table-app 2.72.0 on 2026-11-04.
"""
from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
import uuid
from zoneinfo import ZoneInfo

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from data_acquisition.auth.auth_sessions import AuthSessionExpiredError
from .native_exports import ExportError, ExportPending, _text

ORIGIN = "https://alidocs.dingtalk.com"
DOCUMENT = "Obva6QBXJw9lXeeoF7P7GMqqWn4qY5Pr"
OSS_HOST = "alidocs-body.oss-cn-zhangjiakou.aliyuncs.com"

_REQUEST = r"""async (el, arg) => {
 const w = el.ownerDocument.defaultView;
 if (!w.__oxhorSEMRequire) {
   if (!Array.isArray(w.webpackChunkflex_table_app))
     return {__sem_error:true, code:'sem_frontend_contract_changed'};
   w.webpackChunkflex_table_app.push([
     ['oxhor-sem-request-' + Date.now()], {}, r => {w.__oxhorSEMRequire=r;}
   ]);
 }
 const req=w.__oxhorSEMRequire;
 if (typeof req !== 'function')
   return {__sem_error:true, code:'sem_frontend_contract_changed'};
 const http=(path, options)=>req(400094).he(path, options);
 try {
   if (arg.action === 'prepare') {
     const deadline=Date.now()+30000;
     let store;
     while (Date.now()<deadline) {
       store=req(559300).z().getState();
       if (store.editor?.editor?.controller) break;
       await new Promise(resolve=>w.setTimeout(resolve,100));
     }
     const c=store?.editor?.editor?.controller;
     if (!c || typeof c.model?.serialize!=='function' ||
         typeof c.model.book?.loadAllSheets!=='function')
       return {__sem_error:true, code:'sem_current_model_not_ready'};
     await c.model.book.loadAllSheets();
     return {title:store.data.fileName,
       payload:c.model.serialize({compatible:'excel'}),
       checkpoint_version:w.rawDataStore?.docData?.value?.documentContent?.checkpoint?.baseVersion};
   }
   if (arg.action === 'guard') return await http('/box/api/v1/dentry/operationGuard', {
     method:'post',data:{operationType:'DOWNLOAD',resourceType:0,resourceIdList:[arg.data.document]}
   });
   if (arg.action === 'upload') {
     const v=await http('/core/api/resources/9/upload_info', {method:'post',data:{
       size:new TextEncoder().encode(arg.data.payload).length,
       resourceName:arg.data.title,contentType:''
     }});
     if (!v.isSuccess || typeof v.uploadUrl!=='string' || typeof v.storagePath!=='string')
       return {isSuccess:false};
     const u=new URL(v.uploadUrl);
     if (u.protocol!=='https:' || u.hostname!==arg.data.oss_host)
       return {__sem_error:true,code:'sem_upload_origin_mismatch'};
     const response=await w.fetch(v.uploadUrl, {method:'PUT',credentials:'omit',
       body:new Blob([arg.data.payload],{type:''})});
     return {isSuccess:v.isSuccess,storagePath:v.storagePath,upload_status:response.status};
   }
   if (arg.action === 'submit') return await http('/core/api/document/submitExportJob', {
     method:'post',data:{exportType:'dingTalksheetToxlsx',storagePath:arg.data.storage_path}
   });
   if (arg.action === 'query') return await http('/core/api/document/queryExportJobInfo', {
     method:'get',params:{jobId:arg.data.job_id}
   });
   return {__sem_error:true,code:'sem_request_action_invalid'};
 } catch (e) {
   return {__sem_error:true,http_status:e?.response?.status || null};
 }
}"""

_FRONTEND_READY = "el => {const w=el.ownerDocument.defaultView; return Array.isArray(w.webpackChunkflex_table_app) && w.webpackChunkflex_table_app.push !== w.Array.prototype.push;}"


def _evaluate(page, action, payload=None):
    body = page.frame_locator('#wiki-new-sheet-iframe').locator('body')
    try:
        body.wait_for_function(_FRONTEND_READY, timeout=30000)
    except PlaywrightTimeoutError:
        raise ExportError('sem_frontend_contract_changed') from None
    value = body.evaluate(_REQUEST, {'action': action, 'data': payload or {}})
    if not isinstance(value, dict):
        raise ExportError('sem_request_response_invalid')
    if value.get('__sem_error'):
        if value.get('http_status') == 401:
            raise AuthSessionExpiredError('dingtalk_sem_auth_expired')
        codes = {'sem_frontend_contract_changed', 'sem_current_model_not_ready',
                 'sem_upload_origin_mismatch', 'sem_request_action_invalid'}
        raise ExportError(value['code'] if value.get('code') in codes else 'sem_request_failed')
    return value


def _write(path, value):
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _valid_job(value):
    return isinstance(value, (str, int)) and not isinstance(value, bool) and bool(
        re.fullmatch(r'[0-9]{1,30}', str(value)))


def download_sem_requests(page, *, destination, workbook_title, expected_sheets,
                          start_date, through_date, timeout_sec=180,
                          phase_callback=None, submission_callback=None):
    """Create once, or resume a known job; never resubmit an unknown outcome."""
    if date.fromisoformat(start_date) > date.fromisoformat(through_date):
        raise ExportError('sem_window_reversed')
    selected = urlsplit(page.url)
    if selected.scheme != 'https' or selected.hostname != 'alidocs.dingtalk.com' or selected.path != '/i/nodes/' + DOCUMENT:
        raise ExportError('sem_page_not_approved_workbook')
    if workbook_title != '汇报202610SEM' or not expected_sheets:
        raise ExportError('sem_source_scope_invalid')
    destination = Path(destination).absolute()
    destination.parent.mkdir(parents=True, exist_ok=True)
    state_path = destination.with_suffix('.request-state.json')
    identity = {'workbook_title': workbook_title, 'start_date': start_date,
                'through_date': through_date, 'expected_sheets': sorted(expected_sheets)}
    if state_path.exists():
        state = json.loads(state_path.read_text())
        if any(state.get(k) != v for k, v in identity.items()):
            raise ExportError('sem_request_scope_changed')
    else:
        if destination.exists():
            raise ExportError('sem_destination_already_exists')
        state = {**identity, 'state': 'pre_submit', 'job_id': None,
                 'submission_count': 0}
        _write(state_path, state)
    if state['state'] == 'submission_outcome_unknown' and not state.get('job_id'):
        raise ExportPending('sem_export_submission_outcome_unknown')
    if state['state'] in {'task_failed', 'task_rejected'}:
        raise ExportError('sem_export_task_failed')
    if state['state'] not in {'pre_submit', 'submission_outcome_unknown', 'task_submitted', 'downloaded'}:
        raise ExportError('sem_request_state_invalid')

    def phase(name):
        if phase_callback:
            phase_callback(name)

    job_id = state.get('job_id')
    if job_id is not None and not _valid_job(job_id):
        raise ExportError('sem_saved_job_id_invalid')
    if state['state'] in {'task_submitted', 'downloaded'} and job_id is None:
        raise ExportError('sem_saved_job_id_missing')
    if state['state'] != 'downloaded' and job_id is None:
        guard = _evaluate(page, 'guard', {'document': DOCUMENT})
        if guard.get('isSuccess') is not True or guard.get('isBlocked') is not False:
            raise ExportError('sem_download_permission_denied')
        prepared = _evaluate(page, 'prepare')
        payload = prepared.get('payload')
        if prepared.get('title') != workbook_title or not isinstance(payload, str) or not payload:
            raise ExportError('sem_current_serialization_invalid')
        state.update(snapshot_sha256=hashlib.sha256(payload.encode()).hexdigest(),
                     snapshot_bytes=len(payload.encode()),
                     checkpoint_version=prepared.get('checkpoint_version'))
        _write(state_path, state)
        phase('current_workbook_serialized')
        uploaded = _evaluate(page, 'upload', {'payload': payload, 'title': workbook_title,
                                               'oss_host': OSS_HOST})
        del payload
        storage = uploaded.get('storagePath')
        if (uploaded.get('isSuccess') is not True or uploaded.get('upload_status') != 200
                or not isinstance(storage, str) or not storage.startswith('tmp_cp/')):
            raise ExportError('sem_temporary_upload_failed')
        state.update(state='submission_outcome_unknown', submission_count=1)
        _write(state_path, state)
        phase('export_request_pending')
        try:
            submitted = _evaluate(page, 'submit', {'storage_path': storage})
        except AuthSessionExpiredError:
            state.update(state='pre_submit', submission_count=0)
            _write(state_path, state)
            raise
        except Exception:
            raise ExportPending('sem_export_submission_outcome_unknown') from None
        if submitted.get('isSuccess') is not True:
            state['state'] = 'task_rejected'
            _write(state_path, state)
            raise ExportError('sem_export_submission_rejected')
        if not _valid_job(submitted.get('jobId')):
            raise ExportPending('sem_export_submission_outcome_unknown')
        job_id = str(submitted['jobId'])
        state.update(state='task_submitted', job_id=job_id)
        _write(state_path, state)
        if submission_callback:
            submission_callback({'kind': 'submit', 'task_id': job_id,
                                 'http_status': None, 'response_body_status': 'parsed'})

    if state['state'] != 'downloaded':
        deadline = time.monotonic() + timeout_sec
        while True:
            try:
                result = _evaluate(page, 'query', {'job_id': job_id})
            except AuthSessionExpiredError:
                raise
            except Exception:
                raise ExportPending('sem_export_query_unknown') from None
            if result.get('isSuccess') is not True or str(result.get('jobId')) != job_id:
                raise ExportPending('sem_export_query_unverified')
            if result.get('status') == 'failed':
                state['state'] = 'task_failed'
                _write(state_path, state)
                raise ExportError('sem_export_task_failed')
            if result.get('status') == 'success':
                url = result.get('ossUrl')
                if not isinstance(url, str):
                    raise ExportError('sem_export_download_url_missing')
                parsed = urlsplit(url)
                if parsed.scheme != 'https' or parsed.hostname != OSS_HOST or parsed.username or parsed.password:
                    raise ExportError('sem_download_origin_mismatch')
                break
            if time.monotonic() >= deadline:
                raise ExportPending('sem_export_task_timeout')
            page.wait_for_timeout(1000)
        try:
            response = page.context.request.get(url, timeout=120000, max_redirects=0)
            if response.status != 200:
                raise ExportPending('sem_export_download_failed')
            data = response.body()
        except ExportPending:
            raise
        except Exception:
            raise ExportPending('sem_export_download_unknown') from None
        temp = destination.with_name('.' + destination.name + '.' + uuid.uuid4().hex)
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.replace(temp, destination)
        state['native_sha256'] = _sha(destination)
    if not destination.is_file() or _sha(destination) != state.get('native_sha256'):
        raise ExportError('sem_native_digest_mismatch')
    try:
        from openpyxl import load_workbook
        book = load_workbook(destination, read_only=True, data_only=True)
        try:
            names = book.sheetnames
            if not set(expected_sheets) <= set(names):
                raise ExportError('sem_whole_workbook_missing_sheets')
        finally:
            book.close()
    except ExportError:
        raise
    except Exception:
        raise ExportError('sem_native_workbook_invalid') from None
    state['state'] = 'downloaded'
    _write(state_path, state)
    phase('native_file_saved')
    phase('native_workbook_validated')
    completed = re.findall(r'(?:数据更新至|数据截至|已更新至|填报完成至)\s*[:：]?\s*(\d{4}-\d{2}-\d{2})', _text(page))
    complete = bool(completed) and set(completed) == {through_date}
    evidence = destination.with_suffix('.evidence.json')
    proof = {**identity, 'task_id': job_id, 'snapshot_sha256': state.get('snapshot_sha256'),
             'snapshot_bytes': state.get('snapshot_bytes'),
             'checkpoint_version': state.get('checkpoint_version'),
             'sheetnames': names, 'requested_window': [start_date, through_date],
             'native_completed_dates': completed, 'completion_missing': not complete,
             'method': 'cookie_injected_current_model_and_request_export',
             'automatic_menu_clicks': 0, 'submission_count': state['submission_count']}
    _write(evidence, proof)
    return {'source_id': 'sem', 'status': 'success',
            'captured_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
            'start_date': start_date, 'through_date': through_date,
            'account_ids': list(expected_sheets), 'task_id': job_id,
            'files': [{'path': str(destination), 'sha256': state['native_sha256']}],
            'evidence': {'path': str(evidence), 'sha256': _sha(evidence)},
            'completion': {'complete': complete, 'through_date': through_date if complete else None,
                           'basis': 'source_updated_through' if complete else 'download_only'}}
