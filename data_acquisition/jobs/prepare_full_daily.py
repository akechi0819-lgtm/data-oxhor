"""Preview fees locally, or publish business and notify before updating fees."""
import argparse,json
from datetime import date,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import datetime
from data_acquisition.auth.auth_sessions import (
    AuthSessionPaths, AuthSessionMissingError, AuthSessionExpiredError,
)
from data_acquisition.connectors.advertising.xhs_requests import (
    XHSExport, build_candidate as xhs_candidate,
    run_authenticated as run_xhs_authenticated,
)
from data_acquisition.connectors.advertising.ocean_requests import OceanExport,ACCOUNTS,build_candidate as ocean_candidate
from data_acquisition.connectors.advertising.tencent_requests import (
    TencentExport, TencentLoginRequired, ExportBlocked,
    run_authenticated as run_tencent_authenticated,
    save_login as save_tencent_login,
    verify_promotion_scope,
)
from dashboard_product.management.candidate_sources import validate_candidate_authorities,CandidateSourceError
from dashboard_product.shadow_bi.p5.full_daily import run,receipt_collector,DailyBlocked,digest,atomic_json


def sem_auth_workspace():
    """Return the code repository root where the dedicated site auth is stored."""
    return Path(__file__).resolve().parents[2]


def resolve_sem_receipt(*, workspace, mapping_manifest, output, start, through,
                        receipt=None, use_saved_session=False,
                        executable_path=None, sem_runner=None):
    """Use an explicit receipt or run the dedicated saved-session host once."""
    if receipt is not None:
        if use_saved_session:
            raise DailyBlocked("sem_input_mode_ambiguous")
        return Path(receipt).resolve(strict=True)
    if not use_saved_session:
        raise DailyBlocked("sem_capture_receipt_required")
    if sem_runner is None:
        from data_acquisition.connectors.advertising.sem_host import run_authenticated
        sem_runner = run_authenticated
    result = sem_runner(
        workspace=workspace,
        mapping_manifest=mapping_manifest,
        output=output,
        start_date=start,
        through_date=through,
        executable_path=executable_path,
    )
    if (not isinstance(result, dict) or result.get("status") != "success"
            or result.get("published") is not False
            or not result.get("capture_receipt")):
        raise DailyBlocked("sem_export_not_verified")
    return Path(result["capture_receipt"]).resolve(strict=True)


def sem_capture_status(source):
    """Describe marker coverage without blocking use of the latest whole workbook."""
    completion = source.get('completion') or {}
    if source.get('status') != 'success':
        return {'accepted': False, 'status': 'capture_failed'}
    marked_complete = completion.get('complete') is True and bool(completion.get('through_date'))
    return {
        'accepted': True,
        'status': 'marker_verified' if marked_complete else 'partial_marker_unavailable',
        'completion_marked': marked_complete,
        'completion_through_date': completion.get('through_date'),
        'completion_basis': completion.get('basis'),
        'available_start_date': source.get('start_date'),
        'available_through_date': source.get('through_date'),
        'available_account_count': len(source.get('account_ids', [])),
        'available_file_count': len(source.get('files', [])),
    }


def resume_ocean_account(client, *, account, start, through, output, day):
    """Resume only a verified account from this batch; never re-export it."""
    proof=Path(output)/'verification.json'
    if not proof.exists():return client.run(account=account,start=start,through=through,output=output)
    value=json.loads(proof.read_text())
    if value.get('account_id')!=account[0] or value.get('selected_window')!=[start,through]:raise DailyBlocked('ocean_partial_scope_changed')
    if datetime.fromisoformat(value['captured_at']).astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()!=day:raise DailyBlocked('ocean_partial_not_today')
    root=Path(output).resolve(strict=True)
    for spec in [value['file'],*value['query_pages']]:
        path=Path(spec['path']).resolve(strict=True)
        if not path.is_relative_to(root) or digest(path)!=spec['sha256']:raise DailyBlocked('ocean_partial_input_changed')
    return value


def _verify_promotion_scope_with_login(workspace, **kwargs):
    try:
        return verify_promotion_scope(workspace, **kwargs)
    except (AuthSessionMissingError,AuthSessionExpiredError,TencentLoginRequired):
        save_tencent_login(workspace)
        return verify_promotion_scope(workspace, **kwargs)


def _tencent_scope_confirmation(path=None):
    if path is None:
        path = (Path(__file__).resolve().parents[2] /
                ".local/audits/full-daily-20261029-morning/tencent-scope-explicit-addition-approval-20261029.json")
    path = Path(path).resolve(strict=True)
    pause_path = (Path(__file__).resolve().parents[2] /
                  ".local/audits/full-daily-20261029-morning/tencent-scope-business-confirmation-20261029.json")
    pause_record = json.loads(pause_path.read_text())
    statement = pause_record.get('user_statement', '')
    pause_sha = digest(pause_path)
    return {
        "account_id": "74749810",
        "product_scopes": ["display_plus", "legacy_search"],
        "combine_rule": "sum",
        "evidence": {"path": str(path), "sha256": digest(path)},
        "display_sparse_scope": {
            "allowed": (pause_record.get('evidence_type') == 'user_confirmed_business_scope'
                        and pause_record.get('account_id') == '74749810'
                        and '展示' in statement and '会停' in statement),
            "evidence": {"path": str(pause_path.resolve()), "sha256": pause_sha},
        },
    }


def tencent_window_status(result, inventory, *, scope, selected_window,
                          sparse_display_allowed=False):
    """Validate the requested native report window, keeping daily rows sparse."""
    native = result.get('native', {})
    completion = inventory.get('completion', {})
    if (result.get('phase') != 'verified'
            or result.get('product_scope') != scope
            or result.get('window') != selected_window
            or not result.get('task_id')
            or str(inventory.get('export_task_id')) != str(result.get('task_id'))
            or result.get('file_sha256') != inventory.get('sha256')
            or native.get('product_scope') != scope
            or native.get('selected_window') != selected_window
            or completion.get('verified') is not True
            or completion.get('basis') != 'native_export_window'
            or completion.get('through_date') != selected_window[1]):
        raise DailyBlocked('tencent_native_window_unverified')
    unreported = native.get('missing_selected_dates')
    if not isinstance(unreported, list):
        raise DailyBlocked('tencent_native_date_scope_unverifiable')
    dense = len(unreported) == 0
    sparse_accepted = scope == 'display_plus' and sparse_display_allowed
    if not dense and not sparse_accepted:
        raise DailyBlocked('tencent_sparse_window_not_confirmed')
    return {
        'export_window_verified': True,
        'native_dates_complete': dense,
        'unreported_dates': unreported,
        'sparse_display_accepted': sparse_accepted and not dense,
    }


def collector(batch,contracts,xhs_scope,sem_receipt=None,*,sem_auto=False,
              sem_executable_path=None,sem_runner=None,tencent_confirmation=None):
    batch=Path(batch).resolve();contracts=Path(contracts).resolve()
    def collect(workspace,day,run_id,capture_dir):
        through=(date.fromisoformat(day)-timedelta(days=1)).isoformat()
        config=json.loads((workspace/'.private/full-daily-sources.json').read_text())['expected_sources']
        batch.mkdir(parents=True,exist_ok=True)
        report={'day':day,'through':through,'sources':{},'blockers':[],'warnings':[],'published':False}
        entries=[];sources=[];tencent_parts=[]
        try:
            scope_confirmation=_tencent_scope_confirmation(tencent_confirmation)
        except Exception:
            scope_confirmation=None
        def record(name,action):
            try:
                manifest,capture=action()
                value=json.loads(Path(capture).read_text())
                entries.extend(json.loads(Path(manifest).read_text())['sources'])
                sources.extend(value['sources'])
                report['sources'][name]={'status':'verified','capture':str(capture)}
            except Exception as e:
                report['sources'][name]={'status':'blocked','error_type':type(e).__name__}
                report['blockers'].append(name+':collection_failed')
        def xhs():
            folder=batch/'xhs'
            client=XHSExport(cookie_file=AuthSessionPaths(workspace,'xhs').cookies)
            result=run_xhs_authenticated(client,workspace,
                folder=folder,
                contract=json.loads((contracts/'xhs-network-sample/network-contract.json').read_text()),
                verification=json.loads(Path(xhs_scope).read_text()),
                start=config['xhs']['start_date'],through=through)
            built=xhs_candidate(
                folder,workspace/'Input/AdvertisingCosts/sources.json',
                native_file=folder/'native.xlsx',evidence_file=folder/'evidence.json',
                captured_at=result['started_at'],start=config['xhs']['start_date'],
                through=through,expected_accounts=result['expected_accounts'])
            return built['manifest'],built['capture']
        def ocean():
            folder=batch/'ocean';root=folder/'verification.json'
            if root.exists():
                values=json.loads(root.read_text())['accounts']
                if any(v['selected_window']!=[config['ocean']['start_date'],through]
                       or datetime.fromisoformat(v['captured_at']).astimezone(
                           ZoneInfo('Asia/Shanghai')).date().isoformat()!=day for v in values):
                    raise DailyBlocked('ocean_cached_capture_not_today')
            else:
                client=OceanExport(workspace)
                values=[resume_ocean_account(client,account=a,start=config['ocean']['start_date'],
                        through=through,output=folder/a[0],day=day) for a in ACCOUNTS]
                atomic_json(root,{'accounts':values,'known_account_scope_complete':True,'published':False})
            built=ocean_candidate(folder,workspace/'Input/AdvertisingCosts/sources.json')
            return built['manifest'],built['capture']
        record('xhs',xhs)
        record('ocean',ocean)
        scope_review=config['tencent_ads_abroad'].get('scope_review')
        scope_status=scope_review.get('status') if isinstance(scope_review,dict) else None
        tencent_scope_gate_blocked=(scope_review is not None
                                    and scope_status not in ('pending','observed_contract'))
        tencent_scope_pending=scope_review is not None and scope_status=='pending'
        if tencent_scope_pending or tencent_scope_gate_blocked:
            report['sources']['tencent_ads_abroad']={
                'status':'blocked','reason':'promotion_scope_unverified',
            }
            report['blockers'].append('tencent_ads_abroad:promotion_scope_unverified')
        else:
            for label,scope,contract_name in [
                ('tencent_search','legacy_search','legacy-network-contract.json'),
                ('tencent_display','display_plus','dedicated-network-contract.json'),
            ]:
                try:
                    folder=batch/label
                    result=run_tencent_authenticated(TencentExport(workspace),
                        folder=folder,
                        contract=json.loads((contracts/'tencent-network-sample'/contract_name).read_text()),
                        start=config['tencent_ads_abroad']['start_date'],through=through)
                    native=folder/'native.csv';proof=folder/'state.json'
                    inventory=json.loads((folder/'raw_inventory.json').read_text())['captures'][0]
                    if (inventory.get('product_scope')!=scope
                            or inventory.get('selected_window')!=[config['tencent_ads_abroad']['start_date'],through]
                            or inventory.get('account_ids')!=['74749810']
                            or digest(native)!=inventory.get('sha256')):
                        raise DailyBlocked('tencent_native_inventory_mismatch')
                    window_status=tencent_window_status(
                        result,inventory,scope=scope,
                        selected_window=[config['tencent_ads_abroad']['start_date'],through],
                        sparse_display_allowed=bool((scope_confirmation or {}).get(
                            'display_sparse_scope',{}).get('allowed')))
                    entries.append({
                        'source_id':'tencent_abroad_'+scope,'kind':'tencent_native_csv',
                        'path':str(native.resolve()),'sha256':digest(native),
                        'business_line':'abroad','business_group':'留学整体',
                        'platform':'腾讯广告','account_id':'74749810','product_scope':scope,
                        'time_basis':'播放口径','start_date':config['tencent_ads_abroad']['start_date'],
                        'end_date':through,
                        'capture_evidence':{'path':str(proof.resolve()),'sha256':digest(proof)},
                    })
                    tencent_parts.append({
                        'scope':scope,'folder':folder,'native':native,'proof':proof,
                        'inventory':inventory,'state':result,
                        **window_status,
                    })
                    report['sources'][label]={
                        'status':'verified','task_id':result.get('task_id'),
                        **window_status,
                        'unreported_date_count':len(window_status['unreported_dates']),
                    }
                except Exception as e:
                    detail={'status':'blocked','error_type':type(e).__name__}
                    if isinstance(e,TencentLoginRequired):
                        detail.update(
                            error_code=4501,
                            recovery='login_required',
                            message='腾讯广告登录状态需要恢复',
                        )
                    report['sources'][label]=detail
                    report['blockers'].append(label+':collection_failed')
        if len(tencent_parts)==2:
            promotion_scope=None
            promotion_scope_failure=None
            promotion_output=Path(capture_dir)/'tencent-promotion-scope'
            if scope_status=='observed_contract':
                try:
                    contract_path=scope_review.get('contract_path')
                    contract_sha256=scope_review.get('contract_sha256')
                    if not isinstance(contract_path,str) or not contract_sha256:
                        raise ExportBlocked('tencent_promotion_contract_missing')
                    contract_path=Path(contract_path)
                    if not contract_path.is_absolute():
                        contract_path=Path(__file__).resolve().parents[2]/contract_path
                    native_files={part['scope']:part['native'] for part in tencent_parts}
                    promotion_scope=_verify_promotion_scope_with_login(
                        workspace,contract_path=contract_path,
                        contract_sha256=contract_sha256,
                        start=config['tencent_ads_abroad']['start_date'],
                        through=through,native_files=native_files,
                        output_dir=promotion_output,
                    )
                    if promotion_scope.get('status')!='verified':
                        raise ExportBlocked('tencent_promotion_scope_unverified')
                except Exception as e:
                    promotion_scope_failure={'status':'blocked','error_type':type(e).__name__}
                    receipt_path=promotion_output/'promotion-scope-check.json'
                    if receipt_path.is_file():
                        promotion_scope_failure['receipt']={
                            'path':str(receipt_path.resolve()),'sha256':digest(receipt_path),
                        }
                        try:
                            saved_receipt=json.loads(receipt_path.read_text())
                            promotion_scope_failure['files']=saved_receipt.get('files',[])
                        except (OSError,ValueError):
                            pass
                    report['sources']['tencent_ads_abroad']=promotion_scope_failure
                    report['blockers'].append(
                        'tencent_ads_abroad:promotion_scope_verification_failed')
            scope_complete=(all(part['export_window_verified'] for part in tencent_parts)
                            and (scope_status!='observed_contract'
                                 or promotion_scope is not None))
            evidence_path=batch/'tencent-abroad-capture-evidence.json'
            evidence={
                'source_id':'tencent_ads_abroad','account_id':'74749810',
                'selected_window':[config['tencent_ads_abroad']['start_date'],through],
                'combine_rule':'sum','technical_disjointness_proven':False,
                'scopes':[{
                    'product_scope':part['scope'],
                    'task_id':str(part['state'].get('task_id')),
                    'native_sha256':digest(part['native']),
                    'export_window_verified':part['export_window_verified'],
                    'native_dates_complete':part['native_dates_complete'],
                    'unreported_dates':part['unreported_dates'],
                    'sparse_display_accepted':part['sparse_display_accepted'],
                    'captured_at':part['inventory']['captured_at'],
                } for part in tencent_parts],
                'unreported_dates_are_zero_filled':False,
            }
            if promotion_scope is not None:
                evidence['promotion_scope']={
                    'status':'verified','receipt':promotion_scope['receipt'],
                    'scope_summaries':promotion_scope['scope_summaries'],
                    'daily_comparison':promotion_scope['daily_comparison'],
                }
            elif promotion_scope_failure is not None:
                evidence['promotion_scope']=promotion_scope_failure
            atomic_json(evidence_path,evidence)
            captured_at=max(datetime.fromisoformat(p['inventory']['captured_at'])
                            for p in tencent_parts).isoformat()
            tencent_files=[]
            for part in tencent_parts:
                for source_file in (part['native'],part['proof']):
                    tencent_files.append({
                        'path':str(source_file.resolve()),'sha256':digest(source_file),
                    })
            if promotion_scope is not None:
                tencent_files.extend(promotion_scope['files'])
            elif promotion_scope_failure is not None:
                tencent_files.extend(promotion_scope_failure.get('files',[]))
                if promotion_scope_failure.get('receipt'):
                    tencent_files.append(promotion_scope_failure['receipt'])
            if promotion_scope_failure is None:
                completion={
                    'complete':scope_complete,
                    'through_date':through if scope_complete else None,
                    'basis':'native_export_window',
                    'coverage_semantics':'verified requested report window; preserve native sparse dates; never fill unreported dates with zero',
                }
                if scope_status=='observed_contract':
                    completion['promotion_scope_verified']=True
                sources.append({
                    'source_id':'tencent_ads_abroad','status':'success',
                    'captured_at':captured_at,
                    'start_date':config['tencent_ads_abroad']['start_date'],
                    'through_date':through,'account_ids':['74749810'],
                    'completion':completion,
                    'files':tencent_files,
                    'evidence':{'path':str(evidence_path.resolve()),'sha256':digest(evidence_path)},
                })
                tencent_source_report={
                    'status':'verified','scope_complete':scope_complete,
                    'captured_at':captured_at,
                }
                if scope_status=='observed_contract':
                    tencent_source_report['promotion_scope_verified']=True
                report['sources']['tencent_ads_abroad']=tencent_source_report
        elif not tencent_scope_pending and not tencent_scope_gate_blocked:
            report['blockers'].append('tencent_ads_abroad:source_scope_incomplete')
        if sem_receipt is not None or sem_auto:
            def sem():
                from data_acquisition.connectors.advertising.sem_candidate import load_sem_bundle
                mapping=workspace/'Input/AdvertisingCosts/sources.json'
                sem_folder=batch/'sem'
                receipt_path=resolve_sem_receipt(
                    workspace=sem_auth_workspace(),mapping_manifest=mapping,output=sem_folder,
                    start=config['sem']['start_date'],through=through,receipt=sem_receipt,
                    use_saved_session=sem_auto,executable_path=sem_executable_path,
                    sem_runner=sem_runner)
                bundle=json.loads(receipt_path.read_text())
                manifest_path=Path(bundle['manifest_path'])
                if not manifest_path.is_absolute():manifest_path=receipt_path.parent/manifest_path
                sem_entries,sem_sources=load_sem_bundle(receipt_path)
                if len(sem_sources)!=1:raise DailyBlocked('sem_receipt_scope_invalid')
                return manifest_path,receipt_path
            record('sem',sem)
            sem_result=report['sources'].get('sem',{})
            if sem_result.get('status')=='blocked':
                report['blockers'].append('sem:collection_failed')
            else:
                sem_capture=json.loads(Path(sem_result['capture']).read_text())
                sem_source=sem_capture['sources'][0]
                sem_status=sem_capture_status(sem_source)
                report['sources']['sem'].update(sem_status)
                if not sem_status['accepted']:
                    report['blockers'].append('sem:sample_only_not_live_capture')
                elif not sem_status['completion_marked']:
                    report['warnings'].append('sem_completion_marker_unavailable_latest_workbook_retained')
        else:
            report['blockers'].append('sem:current_native_capture_required')
        manifest={'sources':entries}
        try:
            if scope_confirmation is None:
                raise CandidateSourceError('tencent_scope_confirmation_missing')
            manifest['business_scope_confirmation']=scope_confirmation
            authority_map=validate_candidate_authorities(manifest)
            report['candidate_authorities']=authority_map
        except Exception as e:
            report['blockers'].append(
                str(e) if isinstance(e,CandidateSourceError)
                else 'tencent_scope_confirmation_missing')
        atomic_json(batch/'collection-report.json',report)
        if report['blockers']:
            raise DailyBlocked('collection_incomplete:see_collection_report')
        manifest_path=batch/'candidate-sources.json'
        bundle_path=batch/'capture.json'
        atomic_json(manifest_path,manifest)
        atomic_json(bundle_path,{
            'manifest_path':str(manifest_path.resolve()),
            'sources':sources,
        })
        return receipt_collector(bundle_path)(workspace,day,run_id,capture_dir)
    return collect

def build_parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--batch-dir',type=Path,required=True)
    p.add_argument('--source-contracts',type=Path,required=True)
    p.add_argument('--xhs-scope',type=Path,required=True)
    run_mode=p.add_mutually_exclusive_group()
    run_mode.add_argument('--prepare',action='store_true',help='Build a local candidate only (the default)')
    run_mode.add_argument('--publish',action='store_true',help='Publish business, send the daily notification, then update fees through the existing gates')
    p.add_argument('--refresh-business',action='store_true',
                   help='Force a fresh same-day business source refresh for a manual correction; requires --publish')
    p.add_argument('--orders-start-date', help='Explicit recovery order window start; cash keeps its normal window')
    p.add_argument('--orders-end-date', help='Explicit recovery order window end')
    p.add_argument('--business-inputs',type=Path,
                   help='Use a SHA-verified orders/cash/Tencent manifest; requires --publish --refresh-business')
    sem_mode=p.add_mutually_exclusive_group()
    sem_mode.add_argument('--sem-receipt',type=Path)
    sem_mode.add_argument('--sem-auto',action='store_true',help='Export SEM through requests with its saved site-scoped auth; missing/expired auth uses the dedicated login recovery once')
    p.add_argument('--sem-executable-path',type=Path,help='Explicit installed Chrome for Testing binary for the SEM host')
    p.add_argument('--tencent-scope-confirmation',type=Path,help='Evidence record for the user-confirmed Tencent search+display sum rule')
    return p

def main(argv=None, *, run_fn=None):
    parser=build_parser()
    a=parser.parse_args(argv)
    if bool(a.orders_start_date) != bool(a.orders_end_date) or (a.orders_start_date and not a.publish):
        parser.error('order recovery requires both dates and --publish')
    if a.refresh_business and not a.publish:
        parser.error('--refresh-business requires --publish')
    if a.business_inputs is not None and not (a.publish and a.refresh_business):
        parser.error('--business-inputs requires --publish --refresh-business')
    if run_fn is None and a.publish:
        from data_acquisition.jobs.business_first_daily import run as selected_run
    else:
        selected_run=run if run_fn is None else run_fn
    try:
        kwargs={
            'prepare':not a.publish,
            'collect':collector(a.batch_dir,a.source_contracts,a.xhs_scope,a.sem_receipt,
                               sem_auto=a.sem_auto,sem_executable_path=a.sem_executable_path,
                               tencent_confirmation=a.tencent_scope_confirmation),
        }
        if a.publish:
            kwargs['batch_dir']=a.batch_dir
        if a.refresh_business:
            kwargs['refresh_business']=True
        if a.business_inputs is not None:
            kwargs['business_inputs']=a.business_inputs
        if a.orders_start_date:
            kwargs.update(orders_start_date=a.orders_start_date, orders_end_date=a.orders_end_date)
        result=selected_run(a.workspace.resolve(),**kwargs)
        print(json.dumps(result))
        return 2 if result.get('status') in {'blocked','failed','partial'} else 0
    except DailyBlocked as e:
        result={'status':'blocked','reason':str(e),'report':str(a.batch_dir/'collection-report.json')}
        if a.publish:
            result['pipeline_report']=str(a.batch_dir/'pipeline-result.json')
        else:
            result['published']=False
        print(json.dumps(result));return 2
    except Exception as e:
        result={'status':'failed','reason':type(e).__name__}
        if a.publish:
            result['pipeline_report']=str(a.batch_dir/'pipeline-result.json')
        else:
            result['published']=False
        print(json.dumps(result));return 1
if __name__=='__main__':raise SystemExit(main())
