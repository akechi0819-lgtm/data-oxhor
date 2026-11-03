"""Validate observed SEM export evidence without replaying incomplete requests."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

SUBMIT = '/core/api/document/submitExportJob'
QUERY = '/core/api/document/queryExportJobInfo'
UPLOAD = '/core/api/resources/9/upload_info'


def inspect_contract(value):
    if value.get('platform') != 'dingtalk_sem' or value.get('source_title') != '汇报202610SEM':
        raise ValueError('sem_observed_source_mismatch')
    requests = value.get('observed_requests')
    if not isinstance(requests, list):
        raise ValueError('sem_observed_requests_missing')
    def one(path, method):
        rows = [(i, row) for i, row in enumerate(requests) if row.get('path') == path and row.get('method') == method]
        if len(rows) != 1:
            raise ValueError('sem_observed_request_missing_or_ambiguous')
        return rows[0]
    upload_i, upload = one(UPLOAD, 'POST')
    submit_i, submit = one(SUBMIT, 'POST')
    query_i, query = one(QUERY, 'GET')
    if not upload_i < submit_i < query_i:
        raise ValueError('sem_observed_stage_order_invalid')
    if upload.get('body', {}).get('resourceName') != value['source_title']:
        raise ValueError('sem_upload_title_mismatch')
    if submit.get('body_schema', {}).get('exportType') != 'dingTalksheetToxlsx':
        raise ValueError('sem_export_type_unobserved')
    job = query.get('query', {}).get('jobId')
    if not isinstance(job, str) or not job.isdigit():
        raise ValueError('sem_observed_job_id_missing')
    if value.get('response_body_status') != 'unavailable' and not str(value.get('response_body_status', '')).startswith('Original response buffers no longer available'):
        raise ValueError('sem_response_contract_requires_review')
    # HTTP 200 is transport evidence only. It cannot establish API-level success,
    # status enums, upload storagePath, generated file identity or completion.
    return {
        'schema': 'dingtalk_observed_export.v1', 'source_title': value['source_title'],
        'job_id': job, 'status': 'existing_job_outcome_unconfirmed',
        'observed_http': {name: row.get('status') for name, row in
                          [('upload_info', upload), ('submitExportJob', submit), ('queryExportJobInfo', query)]},
        'request_chain_observed': True, 'api_success_proven': False,
        'response_schema_known': False, 'native_file_verified': False,
        'download_status': value.get('download_status'),
        'listener_disable_confirmed': value.get('network_listener_cleanup') == 'Network.disable succeeded after tool resumed naturally',
        'tool_blocker': value.get('exact_tool_blocker'),
        'replay_performed': False, 'safe_to_create_another_job': False,
        'script_ready': False, 'intake_ready': False, 'published': False,
        'missing_evidence': ['upload_info response and temporary copy serialization',
                             'submitExportJob response schema and job binding',
                             'queryExportJobInfo response schema and terminal status',
                             'native local file path, hash, workbook and yesterday coverage'],
        'next_action': 'Resolve only existing job via browser owner; do not resubmit or infer response fields.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.contract.read_bytes()
    result = inspect_contract(json.loads(raw))
    result['contract_sha256'] = hashlib.sha256(raw).hexdigest()
    with args.output.open('x') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    print(json.dumps({'status':result['status'], 'job_id':result['job_id'], 'script_ready':False}))

if __name__ == '__main__':
    main()
