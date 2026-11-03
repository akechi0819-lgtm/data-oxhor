"""Observed Ocean project/day API, Cookie-first; raw JSON is the authority.

The website generates its XLSX in a local Blob, not a remote export task.
This client preserves every response and generates a clearly labelled projection
for the existing cost parser. No browser is needed when saved auth is valid.
"""
from __future__ import annotations
import argparse, copy, hashlib, json, re, ssl, time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPSHandler
from zoneinfo import ZoneInfo
import certifi
from data_acquisition.auth.auth_sessions import AuthSessionPaths, AuthSessionMissingError, AuthSessionExpiredError
from .xhs_requests import NoRedirect
from .ocean_download import ACCOUNTS, OceanCaptureError, validate_native
ORIGIN='https://localads.chengzijianzhan.cn'
QUERY='/api/lamp/pc/v2/statistics/data/statQuery'
TZ=ZoneInfo('Asia/Shanghai')
DIMENSIONS=(('cdp_project_id','项目ID'),('cdp_project_name','项目名称'),('stat_time_day','日期'),('cdp_marketing_goal','营销场景'),('campaign_type','投放类型'))
METRICS=(('stat_cost','消耗(元)'),('show_cnt','展示次数'),('click_cnt','点击次数'),('ctr','点击率'),('cpm_platform','平均千次展示费用(元)'),('attribution_deep_convert_new_clue_multiple_count','线索留资数(计费时间)'),('attribution_deep_convert_new_clue_multiple_cost','线索留资成本(计费时间)'),('attribution_clue_confirm','确认意向数(计费时间)'),('attribution_clue_confirm_cost','确认意向成本(计费时间)'),('attribution_clue_high_intention','预付定金数(计费时间)'),('attribution_clue_high_intention_cost','预付定金成本(计费时间)'),('attribution_intention_message_clue_cnt','私信意向数(计费时间)'),('attribution_intention_message_clue_cost','私信意向成本(计费时间)'))
class OceanBlocked(RuntimeError):pass

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')

def verified_native_empty_accounts(results):
    """Retain zero-account scope only when the native response proves it."""
    empty=[]
    for result in results:
        if result.get('rows') != 0:
            continue
        validation=result.get('native_validation',{})
        try:
            total=Decimal(str(result.get('total')))
            validation_total=Decimal(str(validation.get('total','NaN')))
        except Exception:
            raise OceanBlocked('ocean_empty_native_not_verified') from None
        if (not isinstance(validation,dict) or validation.get('native_empty') is not True
                or validation.get('rows') != 0 or not validation_total.is_finite()
                or validation_total != 0 or not total.is_finite() or total != 0
                or not result.get('query_pages') or not result.get('file',{}).get('sha256')):
            raise OceanBlocked('ocean_empty_native_not_verified')
        empty.append(str(result['account_id']))
    if len(empty)!=len(set(empty)):
        raise OceanBlocked('ocean_empty_native_account_duplicated')
    return sorted(empty)

def cookie_header(cookies, *, timestamp=None):
    now=time.time() if timestamp is None else timestamp
    pairs=[];scoped=expired=0
    for c in cookies:
        domain=str(c.get('domain','')).lstrip('.')
        if not domain or not ('localads.chengzijianzhan.cn'==domain or 'localads.chengzijianzhan.cn'.endswith('.'+domain)):continue
        cp=c.get('path','/')
        if not isinstance(cp,str) or not (cp=='/' or QUERY==cp or QUERY.startswith(cp.rstrip('/')+'/')):continue
        scoped+=1
        if 0<=float(c.get('expires',-1))<=now:expired+=1;continue
        n,v=c.get('name'),c.get('value')
        if not isinstance(n,str) or not re.fullmatch(r'[!#$%&\x27*+.^_`|~0-9A-Za-z-]+',n) or not isinstance(v,str) or any(s in v for s in '\r\n;'):raise OceanBlocked('ocean_invalid_cookie')
        pairs.append(n+'='+v)
    if not pairs:
        if scoped and expired==scoped:raise AuthSessionExpiredError('ocean_cookies_expired')
        raise AuthSessionMissingError('ocean_cookie_scope_missing')
    return '; '.join(pairs)

class OceanExport:
    def __init__(self, workspace, *, request_timeout=60, post=None):
        self.paths=AuthSessionPaths(Path(workspace),'ocean');self.timeout=request_timeout;self.post=post or self._post
    def _auth(self):
        files=[self.paths.cookies,self.paths.root/'query-auth.json']
        if any(not p.is_file() for p in files):raise AuthSessionMissingError('ocean_saved_state_missing')
        if self.paths.root.stat().st_mode&0o077 or any(p.stat().st_mode&0o077 for p in files):raise OceanBlocked('ocean_auth_not_private')
        try:return json.loads(files[0].read_text()),json.loads(files[1].read_text())
        except Exception:raise OceanBlocked('ocean_auth_invalid') from None
    def _post(self, account, body):
        cookies,spec=self._auth()
        headers={k:v for k,v in spec['headers'].items() if k.lower() in {'content-type','origin','referer','user-agent','x-secsdk-csrf-token'}}
        headers['Cookie']=cookie_header(cookies)
        request=Request(ORIGIN+QUERY+'?'+urlencode({'advid':account}),data=json.dumps(body).encode(),headers=headers,method='POST')
        try:
            with build_opener(NoRedirect(),HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where()))).open(request,timeout=self.timeout) as response:
                value=json.loads(response.read())
        except HTTPError as e:
            if e.code==401:raise AuthSessionExpiredError('ocean_http_401') from None
            raise OceanBlocked('ocean_http_'+str(e.code)) from None
        except Exception:raise OceanBlocked('ocean_read_result_unconfirmed') from None
        if value.get('status_code')!=0:raise OceanBlocked('ocean_query_rejected')
        return value
    def run(self, *, account, start, through, output):
        start=date.fromisoformat(start).isoformat();through=date.fromisoformat(through).isoformat()
        if account not in ACCOUNTS or start>through:raise OceanBlocked('ocean_scope_unconfirmed')
        folder=Path(output)
        if folder.exists():raise OceanBlocked('ocean_output_already_exists')
        _,spec=self._auth();body=copy.deepcopy(spec['body'])
        if body.get('DataSetKey')!='pc_data_adv2_detail_clue2' or body.get('PageParams')!={'Limit':'1000','Offset':'0'}:raise OceanBlocked('ocean_observed_query_changed')
        conditions=body['Filters']['Conditions']
        ids=[c for c in conditions if c.get('Field')=='advertiser_id']
        if len(ids)!=1:raise OceanBlocked('ocean_account_filter_ambiguous')
        ids[0]['Values']=[account[0]];body['StartTime']=start+' 00:00:00';body['EndTime']=through+' 23:59:59'
        began=time.monotonic();rows=[];seen=set();total_count=None;total=None;offset=0;pages=[]
        while True:
            body['PageParams']['Offset']=str(offset)
            value=self.post(account[0],copy.deepcopy(body))
            folder.mkdir(parents=True,exist_ok=False)
            data=value.get('data',{}).get('StatsData',{})
            try:count=int(data['TotalCount']);cost=Decimal(str(data['Totals']['stat_cost']['Value']))
            except Exception:raise OceanBlocked('ocean_response_schema_changed') from None
            if count<0 or count>1000 or not cost.is_finite():raise OceanBlocked('ocean_response_bounds_invalid')
            if total_count is None:total_count,total=count,cost
            if (count,cost)!=(total_count,total):raise OceanBlocked('ocean_report_changed_during_pagination')
            chunk=data.get('Rows',[])
            if not isinstance(chunk,list) or len(chunk)>1000 or (not chunk and len(rows)<count):raise OceanBlocked('ocean_page_incomplete')
            raw=folder/f'page-{offset:06d}.json';write(raw,value);pages.append({'path':str(raw.resolve()),'sha256':sha(raw),'offset':offset})
            for row in chunk:
                dims=row.get('Dimensions',{});metrics=row.get('Metrics',{})
                try:
                    key=tuple(str(dims[k]['Value']) for k in ('cdp_project_id','stat_time_day','cdp_marketing_goal','campaign_type'))
                    day=date.fromisoformat(dims['stat_time_day']['ValueStr']).isoformat()
                    amount=Decimal(str(metrics['stat_cost']['Value']))
                    for keyname,_ in DIMENSIONS:assert isinstance(dims[keyname]['ValueStr'],str)
                    for keyname,_ in METRICS:assert isinstance(metrics[keyname]['ValueStr'],str)
                except Exception:raise OceanBlocked('ocean_row_schema_changed') from None
                if key in seen or not start<=day<=through or not amount.is_finite():raise OceanBlocked('ocean_row_duplicate_or_outside_window')
                seen.add(key);rows.append(row)
            if len(rows)==count:break
            if len(rows)>count:raise OceanBlocked('ocean_page_count_exceeded')
            raise OceanBlocked('ocean_native_query_incomplete_no_guessed_pagination')
        if abs(sum((Decimal(str(r['Metrics']['stat_cost']['Value'])) for r in rows),Decimal(0))-total)>Decimal('0.011'):raise OceanBlocked('ocean_page_total_mismatch')
        if rows and account[2] is None:raise OceanBlocked('ocean_new_nonempty_account_needs_mapping')
        # Faithful projection of the observed client-side native workbook. Raw
        # platform JSON above remains sealed; this is not a downloaded XLSX.
        from openpyxl import Workbook
        book=Workbook();sheet=book.active;sheet.title='Sheet1'
        if rows:
            sheet.append([n for _,n in DIMENSIONS+METRICS]);sheet.append([None]*5+[data['Totals'][k]['ValueStr'] for k,_ in METRICS])
            for r in rows:sheet.append([r['Dimensions'][k]['ValueStr'] for k,_ in DIMENSIONS]+[r['Metrics'][k]['ValueStr'] for k,_ in METRICS])
        else:
            sheet.append([n for _,n in METRICS]);sheet.append(['-']*len(METRICS))
        projection=folder/'api-projection.xlsx';book.save(projection)
        summary={'count':len(rows),'total':str(total),'empty':not rows}
        checked=validate_native(projection,account,start,through,summary)
        result={'source':'ocean','account_id':account[0],'business_line':account[1],'business_group':account[2],'selected_window':[start,through],'actual_row_window':[min(r['Dimensions']['stat_time_day']['ValueStr'] for r in rows),max(r['Dimensions']['stat_time_day']['ValueStr'] for r in rows)] if rows else None,'captured_at':datetime.now(TZ).isoformat(),'rows':len(rows),'total':str(total),'query_pages':pages,'elapsed_seconds':round(time.monotonic()-began,3),'file':{'path':str(projection.resolve()),'sha256':sha(projection),'origin':'projection_of_sealed_native_api_json_not_browser_download'},'native_validation':checked,'browser_used':False,'remote_export_task':False,'published':False}
        write(folder/'verification.json',result);return result

def save_login(workspace, *, start, through, confirm=input):
    """One ordinary HTTPS login and verified native export; no Chrome attachment."""
    import os, tempfile
    from urllib.parse import urlsplit
    from playwright.sync_api import sync_playwright
    from data_acquisition.auth.auth_sessions import write_auth_session
    from .ocean_download import STANDARD_URL, _select_day
    paths=AuthSessionPaths(Path(workspace),'ocean');observed=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='chrome',headless=False)
        try:
            context=browser.new_context(accept_downloads=True)
            if paths.cookies.is_file():
                if paths.cookies.stat().st_mode&0o077:raise OceanBlocked('ocean_auth_not_private')
                context.add_cookies(json.loads(paths.cookies.read_text()))
            page=context.new_page();page.goto(STANDARD_URL+ACCOUNTS[0][0],wait_until='domcontentloaded')
            confirm('在唯一巨量专用窗口正常登录后，回到终端按回车继续。')
            page.goto(STANDARD_URL+ACCOUNTS[0][0],wait_until='domcontentloaded')
            page.get_by_role('button',name=re.compile('ID：'+ACCOUNTS[0][0])).wait_for(state='visible',timeout=30000)
            def finished(request):
                if urlsplit(request.url).hostname!='localads.chengzijianzhan.cn' or urlsplit(request.url).path!=QUERY:return
                try:
                    body=json.loads(request.post_data or '{}');response=request.response().json()
                    if 'IsDownload' in body and body.get('DataSetKey')=='pc_data_adv2_detail_clue2' and response.get('status_code')==0:
                        observed.append({'url':request.url,'body':body,'headers':{k:v for k,v in request.all_headers().items() if k.lower()!='cookie'}})
                except Exception:pass
            page.on('requestfinished',finished)
            page.get_by_text('项目',exact=True).click(timeout=30000)
            page.get_by_placeholder('开始时间',exact=True).click();_select_day(page,start)
            page.get_by_placeholder('结束时间',exact=True).click();_select_day(page,through)
            page.wait_for_timeout(1000)
            with page.expect_download(timeout=120000) as pending:page.locator('[name="StandardDownloadBtn"]').click()
            # Native file is only used to complete the ordinary website operation;
            # do not persist authentication in a report/download folder.
            pending.value.path();page.wait_for_timeout(300)
            matches=[s for s in observed if s['body'].get('StartTime')==start+' 00:00:00' and s['body'].get('EndTime')==through+' 23:59:59']
            if not matches:raise OceanBlocked('ocean_login_export_contract_not_observed')
            write_auth_session('ocean',cookies=context.cookies([ORIGIN,'https://business.oceanengine.com']),local_storage=page.evaluate('Object.fromEntries(Object.entries(localStorage))'),paths=paths)
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=paths.root,prefix='.query-',delete=False) as handle:
                temporary=Path(handle.name)
                try:
                    os.fchmod(handle.fileno(),0o600);json.dump(matches[-1],handle,ensure_ascii=False);handle.flush();os.fsync(handle.fileno());temporary.replace(paths.root/'query-auth.json')
                finally:temporary.unlink(missing_ok=True)
            return {'service':'ocean','credentials_written':True,'native_export_query_verified':True}
        finally:browser.close()

def run_authenticated(client, workspace, *, login=None, **job):
    try:return client.run(**job)
    except (AuthSessionMissingError,AuthSessionExpiredError):
        (login or save_login)(workspace,start=job['start'],through=job['through'])
        return client.run(**job)

def build_candidate(folder, mapping_manifest):
    """Bridge sealed API projections to the existing candidate-only fee parser."""
    from dashboard_product.management.candidate_sources import load_candidate_sources
    folder=Path(folder).resolve(strict=True);mapping_manifest=Path(mapping_manifest).resolve(strict=True)
    original=mapping_manifest.read_bytes();mapping=json.loads(original)['sources']
    record=json.loads((folder/'verification.json').read_text());results=record['accounts']
    if {r['account_id'] for r in results}!={a[0] for a in ACCOUNTS}:raise OceanBlocked('ocean_candidate_known_scope_incomplete')
    entries=[];files=[];windows=set();captured=[];total_rows=0
    for result in results:
        account=next(a for a in ACCOUNTS if a[0]==result['account_id']);native=Path(result['file']['path']).resolve(strict=True)
        if not native.is_relative_to(folder) or sha(native)!=result['file']['sha256']:raise OceanBlocked('ocean_candidate_projection_changed')
        proof=folder/account[0]/'verification.json'
        if json.loads(proof.read_text())!=result:raise OceanBlocked('ocean_candidate_evidence_changed')
        for page in result['query_pages']:
            path=Path(page['path']).resolve(strict=True)
            if not path.is_relative_to(folder) or sha(path)!=page['sha256']:raise OceanBlocked('ocean_candidate_raw_json_changed')
        files.append({'path':str(proof),'sha256':sha(proof)})
        files.extend({'path':p['path'],'sha256':p['sha256']} for p in result['query_pages'])
        windows.add(tuple(result['selected_window']));captured.append(result['captured_at']);files.append({'path':str(native),'sha256':sha(native)});total_rows+=result['rows']
        if not result['rows']:continue
        matches=[e for e in mapping if e.get('kind')=='ocean_daily' and e['business_line']==account[1] and e['business_group']==account[2]]
        # Sealed files are content-addressed, so their paths no longer carry
        # account IDs. The configured account's unique business group remains
        # authoritative; shared groups require explicit account identity.
        if len(matches)>1:
            matches=[e for e in matches if e.get('account_id')==account[0] or account[0] in e['source_id']]
        if len(matches)!=1:raise OceanBlocked('ocean_candidate_mapping_missing_or_ambiguous')
        entries.append({**matches[0],'path':str(native),'sha256':sha(native)})
    if len(windows)!=1:raise OceanBlocked('ocean_candidate_mixed_windows')
    start,through=next(iter(windows));manifest=folder/'candidate-sources.json';write(manifest,{'sources':entries});parsed=load_candidate_sources(manifest)
    if len(parsed['rows'])!=total_rows:raise OceanBlocked('ocean_candidate_row_count_changed')
    if mapping_manifest.read_bytes()!=original:raise OceanBlocked('ocean_formal_mapping_changed')
    empty_accounts=verified_native_empty_accounts(results)
    source={'source_id':'ocean','status':'success','captured_at':max(captured),'start_date':start,'through_date':through,'account_ids':[a[0] for a in ACCOUNTS],'native_empty_accounts':empty_accounts,'files':files,'evidence':{'path':str(folder/'verification.json'),'sha256':sha(folder/'verification.json')},'completion':{'complete':True,'through_date':through,'basis':'native_export_api_window'},'authority':'native:ocean'}
    write(folder/'capture.json',{'manifest_path':str(manifest),'sources':[source]})
    write(folder/'candidate-validation.json',{'rows':len(parsed['rows']),'amount':str(sum((Decimal(str(r['amount'])) for r in parsed['rows']),Decimal(0))),'known_accounts':source['account_ids'],'mapping_manifest_sha256':hashlib.sha256(original).hexdigest(),'through_date':through,'whole_platform_complete':False,'full_daily_ready':False,'published':False})
    return {'manifest':str(manifest),'capture':str(folder/'capture.json')}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--workspace',type=Path,required=True);p.add_argument('--start',required=True);p.add_argument('--through',required=True);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--account',action='append')
    a=p.parse_args();accounts=ACCOUNTS if not a.account else tuple(c for c in ACCOUNTS if c[0] in a.account)
    if a.account and {c[0] for c in accounts}!=set(a.account):p.error('unconfirmed account')
    client=OceanExport(a.workspace);results=[]
    try:
        for account in accounts:results.append(run_authenticated(client,a.workspace,account=account,start=a.start,through=a.through,output=a.output_dir/account[0]))
        write(a.output_dir/'verification.json',{'accounts':results,'known_account_scope_complete':len(results)==len(ACCOUNTS),'configured_accounts_only':True,'production_ready':False,'published':False})
        if len(accounts)==len(ACCOUNTS):build_candidate(a.output_dir,a.workspace/'Input/AdvertisingCosts/sources.json')
        print(json.dumps({'status':'verified','accounts':[{'account_id':r['account_id'],'rows':r['rows'],'total':r['total'],'seconds':r['elapsed_seconds']} for r in results],'published':False},ensure_ascii=False));return 0
    except Exception as e:
        reason=str(e) if isinstance(e,(OceanBlocked,OceanCaptureError,AuthSessionMissingError,AuthSessionExpiredError)) else type(e).__name__
        print(json.dumps({'status':'blocked','reason':reason,'completed_accounts':[r['account_id'] for r in results],'published':False}));return 2
if __name__=='__main__':raise SystemExit(main())
