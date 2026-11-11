from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
import pytest
from monitoring_product import notification_job_reconcile as r
from dashboard_product.shadow_bi.p5 import notification_contract as c


def write_sql_release(library):
    snapshots={'training':'snapshot_training','abroad':'snapshot_abroad'}
    through='2026-10-25';as_of='2026-10-26';batch='run_fixture'
    coverage={'data_through':through,'snapshot_id':snapshots['training'],
              'study_abroad_source':{'snapshot_id':snapshots['abroad'],'through_date':through}}
    warehouse_bytes=b'synthetic warehouse bytes'
    (library/'warehouse.duckdb').write_bytes(warehouse_bytes)
    database={'path':'warehouse.duckdb','sha256':hashlib.sha256(warehouse_bytes).hexdigest(),
              'size_bytes':len(warehouse_bytes),'media_type':'application/vnd.duckdb'}
    candidate={'schema_version':'sql_warehouse_candidate.v1','batch_id':batch,
               'snapshots':snapshots,'as_of_date':as_of,'through_date':through,
               'database':database}
    raw=json.dumps(candidate).encode();(library/'candidate.json').write_bytes(raw)
    digest=hashlib.sha256(raw).hexdigest()
    release={'schema_version':'sql_warehouse_release.v1','release_id':library.parent.name,
             'batch_id':batch,'snapshots':snapshots,'as_of_date':as_of,'coverage':coverage,
             'candidate':{'path':'candidate.json','sha256':digest,'size_bytes':len(raw),
                          'media_type':'application/json'},'candidate_sha256':digest,
             'database_sha256':database['sha256']}
    (library/'release.json').write_text(json.dumps(release))
    return release

@pytest.fixture
def fixture(tmp_path):
    base=tmp_path/'warehouse';home=tmp_path/'notify';control=base/'notify-control'
    (control/'results').mkdir(parents=True);(home/'state').mkdir(parents=True)
    release=base/'releases/daily-fixture';(release/'library').mkdir(parents=True);(base/'current').symlink_to(release)
    manifest=write_sql_release(release/'library')
    job={'operation':'send-scheduled','expected_release':'daily-fixture','as_of_date':'2026-10-26','status':'unknown','retryable':False,'network_send_attempted':True}
    identifier=c.job_id({k:job[k] for k in ['operation','expected_release','as_of_date']});(control/'results'/(identifier+'.json')).write_text(json.dumps(job))
    rows={}
    for mid,channel in r.MESSAGES.items():
        rows['2026-10-26|'+channel+'|'+mid]={'status':'sent','run_id':'run_fixture','snapshot_id':'snapshot_training','data_through':'2026-10-25',
            'message_sha256':'a'*64,'asset_sha256':{'png':'b'*64,'xlsx':'c'*64,'markdown':'d'*64},
            'delivery':{'status':'sent','message_sha256':'a'*64,'asset_sha256':{'png':'b'*64,'xlsx':'c'*64,'markdown':'d'*64}}}
    state=home/'state/shared_delivery_state.json';state.write_text(json.dumps({'schema_version':'management_shared_delivery_state.v1','deliveries':rows}));(home/'state/shared_delivery.lock').touch()
    return base,home,control,identifier,state


def test_reconciliation_never_calls_sender_or_changes_original_unknown(fixture):
    base,home,control,identifier,state=fixture;job=control/'results'/(identifier+'.json');before=(job.read_bytes(),state.read_bytes())
    with patch('monitoring_product.delivery_transport.post_dingtalk',side_effect=AssertionError('no sending')):
        value=r.reconcile(identifier,control=control,home=home,warehouse=base)
    assert value['delivery_status']=='sent' and value['no_send_performed'] is True
    assert value['message_status_counts']=={'sent':8} and (job.read_bytes(),state.read_bytes())==before
    directory=control/'reconciliations';directory.mkdir(mode=0o750);(directory/(identifier+'.json')).write_text(json.dumps(value));(directory/(identifier+'.json')).chmod(0o640)
    assert r.read_receipt(control,identifier,before[0],os.geteuid())==value
    with pytest.raises(ValueError):r.read_receipt(control,identifier,b'bogus',os.geteuid())


@pytest.mark.parametrize('change',['sending','unknown','pending','wrong_batch','wrong_snapshot','wrong_date','asset_diff'])
def test_reconciliation_cannot_promote_unconfirmed_or_other_source_delivery(fixture,change):
    base,home,control,identifier,state=fixture;data=json.loads(state.read_bytes());row=next(iter(data['deliveries'].values()))
    if change in ['sending','unknown','pending']:row['status']=change
    elif change=='wrong_batch':row['run_id']='run_other'
    elif change=='wrong_snapshot':row['snapshot_id']='snapshot_other'
    elif change=='wrong_date':row['data_through']='2026-10-24'
    else:row['asset_sha256']['png']='0'*64
    state.write_text(json.dumps(data))
    with pytest.raises(ValueError):r.reconcile(identifier,control=control,home=home,warehouse=base)
    assert not (control/'reconciliations').exists()


def test_server_run_lock_busy_returns_before_build_or_credentials(fixture):
    from monitoring_product import server_notify as n
    base,home,control,identifier,state=fixture
    with patch.object(n.n,'require_imported_state'),patch.object(n.n,'require_send_date'),patch.object(n.fcntl,'flock',side_effect=BlockingIOError()),patch.object(n.n,'build_bundle',side_effect=AssertionError('no build')),patch('monitoring_product.delivery_transport.post_dingtalk',side_effect=AssertionError('no send')):
        value=n.run('send-scheduled',warehouse=base,home=home,env_file=home/'never-read.env',asset_root=home,now=datetime(2026,10,26,10,tzinfo=ZoneInfo('Asia/Shanghai')))
    assert value['status']=='blocked' and value['reason']=='notification_executor_busy' and value['network_send_attempted'] is False


def test_deduplicated_server_result_does_not_claim_a_new_http_send(fixture):
    from monitoring_product import server_notify as n
    base,home,control,identifier,state=fixture;manifest=json.loads((base/'current/library/release.json').read_bytes())
    version=hashlib.sha256(n.n.canonical({})).hexdigest()[:16];bundle=home/'bundles'/('daily-fixture-'+version);bundle.mkdir(parents=True);(bundle/'bundle.json').write_text('{}')
    result={'status':'sent','messages':[{'status':'sent','deduplicated':True} for _ in range(8)]}
    with patch.object(n.n,'require_imported_state'),patch.object(n.n,'require_send_date'),patch.object(n,'load_library',return_value=(manifest,None,None)),patch.object(n.n,'rule_binding',return_value={}),patch.object(n.n,'deliver_bundle',return_value=result),patch('monitoring_product.delivery_transport.post_dingtalk',side_effect=AssertionError('no send')):
        report=n.run('send-scheduled',warehouse=base,home=home,env_file=home/'never-read.env',asset_root=home,now=datetime(2026,10,26,10,tzinfo=ZoneInfo('Asia/Shanghai')))
    assert report['status']=='sent' and report['deduplicated']==8 and report['network_send_attempted'] is False


@pytest.mark.parametrize('hour', [9, 11])
def test_published_send_has_no_hour_gate_and_checks_each_send(fixture, hour):
    from monitoring_product import server_notify as n
    base,home,control,identifier,state=fixture
    manifest=json.loads((base/'current/library/release.json').read_bytes())
    def deliver(**kwargs):
        assert kwargs['dry_run'] is False
        kwargs['before_send']()
        return {'status':'sent','messages':[{'status':'sent'} for _ in range(8)]}
    with patch.object(n.n,'require_imported_state'),patch.object(n.n,'require_send_date'),patch.object(n,'load_library',return_value=(manifest,None,None)),patch.object(n.n,'rule_binding',return_value={}),patch.object(n.n,'build_bundle'),patch.object(n.n,'deliver_bundle',side_effect=deliver):
        value=n.run('send-published',warehouse=base,home=home,now=datetime(2026,10,26,hour,35,tzinfo=ZoneInfo('Asia/Shanghai')),expected_release='daily-fixture',expected_date='2026-10-26')
    assert value['status']=='sent'


@pytest.mark.parametrize('release,day', [(None,None),('daily-other','2026-10-26'),('daily-fixture','2026-10-25')])
def test_published_send_requires_bound_current(fixture, release, day):
    from monitoring_product import server_notify as n
    base,home,*_=fixture
    with pytest.raises(ValueError):
        n.run('send-published',warehouse=base,home=home,now=datetime(2026,10,26,9,35,tzinfo=ZoneInfo('Asia/Shanghai')),expected_release=release,expected_date=day)


def test_published_send_rejects_stale_formal_date(fixture):
    from monitoring_product import server_notify as n
    base,home,*_=fixture
    with pytest.raises(ValueError,match='today formal release'):
        n.run('send-published',warehouse=base,home=home,now=datetime(2026,10,27,9,35,tzinfo=ZoneInfo('Asia/Shanghai')),expected_release='daily-fixture',expected_date='2026-10-26')
