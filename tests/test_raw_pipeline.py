from datetime import date
import hashlib
import io
import json
from pathlib import Path
import tarfile
import zipfile
from unittest.mock import patch

import pytest
from openpyxl import Workbook
from dashboard_product.shadow_bi.p5 import raw_inputs as ri
from dashboard_product.shadow_bi.p5 import raw_compute as rc

DAY='2026-10-25'
COMPANY='workspace_bi_operations'

@pytest.fixture
def inputs(tmp_path):
    paths={}
    for key in ri.FILES:
        p=tmp_path/(key+'.xlsx');w=Workbook();w.active.append(['id']);w.active.append([1]);w.save(p);w.close();paths[key]=p
    return paths


def make(inputs,tmp_path,batch='raw-test',archive='inputs.tar'):
    a=tmp_path/archive;ri.pack(inputs,a,batch=batch,company=COMPANY,day=DAY);return a


def stage(a,tmp_path,**kwargs):
    return ri.stage(a,tmp_path/'received',company=COMPANY,day=DAY,minimum_cutoff='2026-10-24',**kwargs)


def rewrite(a,out,change):
    with tarfile.open(a,'r:') as source,tarfile.open(out,'w:') as dest:
        for item in source:
            payload=source.extractfile(item).read();name=item.name
            if name=='manifest.json':
                m=json.loads(payload);change(m);payload=json.dumps(m).encode()
            t=tarfile.TarInfo(name);t.size=len(payload);dest.addfile(t,io.BytesIO(payload))


def test_receive_is_immutable_idempotent_and_not_publish(inputs,tmp_path):
    a=make(inputs,tmp_path);r=stage(a,tmp_path);assert r['status']=='received' and r['published'] is False
    assert stage(a,tmp_path)==r
    target=tmp_path/'received/raw-test'
    assert (target/'inputs/orders.xlsx').stat().st_mode & 0o222 == 0
    assert not (target/'state.json').exists()


def test_package_determinism(inputs,tmp_path):
    a=make(inputs,tmp_path);b=make(inputs,tmp_path,archive='second.tar');assert ri.sha(a)==ri.sha(b)


def test_conflicting_same_batch(inputs,tmp_path):
    a=make(inputs,tmp_path);stage(a,tmp_path)
    w=Workbook();w.active.append(['changed']);w.save(inputs['cash']);w.close()
    b=make(inputs,tmp_path,archive='different.tar')
    with pytest.raises(ValueError,match='different hash'):stage(b,tmp_path)


@pytest.mark.parametrize('change',[
    lambda m:m['files'].pop('tencent'),
    lambda m:m.update(company_id='other'),
    lambda m:m.update(as_of_date='2026-10-24'),
    lambda m:m.update(data_through='2026-10-23'),
    lambda m:m.update(refresh_months=['2026-09']),
    lambda m:m['bi_window'].update(start='2026-01-01'),
    lambda m:m['files']['cash'].update(path='../cash.xlsx'),
    lambda m:m['files']['cash'].update(filename='../cash.xlsx'),
    lambda m:m['files']['cash'].update(sha256='0'*64),
    lambda m:m['files']['cash'].update(size_bytes=1),
    lambda m:m.update(command='anything'),
    lambda m:m.update(batch_id='../escape'),
])
def test_invalid_contract(inputs,tmp_path,change):
    a=make(inputs,tmp_path);b=tmp_path/'bad.tar';rewrite(a,b,change)
    with pytest.raises((ValueError,KeyError)):stage(b,tmp_path)
    assert not (tmp_path/'received/raw-test').exists()


@pytest.mark.parametrize('name,kind',[('../escape','file'),('/abs','file'),('inputs/../cash.xlsx','file'),('inputs\\cash.xlsx','file'),('symlink','link'),('manifest.json','duplicate')])
def test_unsafe_archive(inputs,tmp_path,name,kind):
    a=make(inputs,tmp_path)
    with tarfile.open(a,'a:') as tf:
        i=tarfile.TarInfo(name)
        if kind=='link':i.type=tarfile.SYMTYPE;i.linkname='/etc/passwd';tf.addfile(i)
        else:i.size=1;tf.addfile(i,io.BytesIO(b'x'))
    with pytest.raises(ValueError):stage(a,tmp_path)
    assert not (tmp_path/'escape').exists()


def test_nested_workbook_zip_bomb_rejected(inputs,tmp_path):
    p=inputs['cash']
    with zipfile.ZipFile(p,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','x');z.writestr('xl/workbook.xml','x'*10000)
    with patch.object(ri,'MAX_XML',100):
        with pytest.raises(ValueError):make(inputs,tmp_path)


def test_archive_size_limit(inputs,tmp_path):
    a=make(inputs,tmp_path)
    with patch.object(ri,'MAX_ARCHIVE',100):
        with pytest.raises(ValueError):stage(a,tmp_path)


def test_received_tampering_rejected(inputs,tmp_path):
    a=make(inputs,tmp_path);stage(a,tmp_path)
    p=tmp_path/'received/raw-test/inputs/cash.xlsx';p.chmod(0o640);p.write_bytes(b'changed')
    with pytest.raises(ValueError,match='stored input changed'):stage(a,tmp_path)


@pytest.fixture
def approved_cutoff(monkeypatch):
    # These failure/timeout tests isolate subprocess handling after evidence preflight.
    from dashboard_product.management.cutoff import VerifiedCompletion
    def approved(received):
        proof=VerifiedCompletion(DAY,'2026-10-24',received.name,ri.sha(received/'payload.tar'),'a'*64)
        return proof.metadata(),proof
    monkeypatch.setattr(rc,'resolve_source_completion',approved)


def test_compute_failure_never_publishes(inputs,tmp_path,approved_cutoff):
    a=make(inputs,tmp_path);stage(a,tmp_path)
    args=dict(received=tmp_path/'received/raw-test',baseline=tmp_path/'baseline',root=tmp_path/'compute',day=DAY,company=COMPANY,minimum_cutoff='2026-10-24')
    class Child:
        pid=123
        def __init__(self,*a,**kw):pass
        def wait(self,timeout):return 1
        def poll(self):return 1
    with patch.object(rc.subprocess,'Popen',Child):r=rc.run(**args)
    assert r['status']=='failed' and r['published'] is False
    assert rc.run(**args)==r


def test_timeout_kills_process_group(inputs,tmp_path,approved_cutoff):
    a=make(inputs,tmp_path);stage(a,tmp_path)
    class Child:
        pid=123
        n=0
        def __init__(self,*a,**kw):pass
        def wait(self,timeout):
            self.n+=1
            if self.n==1:raise rc.subprocess.TimeoutExpired('test',1)
            return -15
        def poll(self):return -15
    with patch.object(rc.subprocess,'Popen',Child),patch.object(rc.os,'killpg') as kill:
        r=rc.run(received=tmp_path/'received/raw-test',baseline=tmp_path/'baseline',root=tmp_path/'compute',day=DAY,company=COMPANY,minimum_cutoff='2026-10-24',timeout=1)
    assert r['status']=='timed_out' and r['published'] is False;kill.assert_called_once()


def test_raw_adapter_is_not_registered_in_production():
    from dashboard_product.shadow_bi.p5.receiver import app
    assert not any(rule.rule.startswith('/v1/raw-batches') for rule in app.url_map.iter_rules())


def test_http_adapter_auth_queue_and_status(inputs,tmp_path):
    from flask import Flask
    from dashboard_product.shadow_bi.p5.raw_receiver import register
    from datetime import datetime
    from zoneinfo import ZoneInfo
    day=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    from datetime import date,timedelta
    cutoff=(date.fromisoformat(day)-timedelta(days=1)).isoformat()
    a=tmp_path/'today.tar';ri.pack(inputs,a,batch='raw-http',company=COMPANY,day=day)
    app=Flask(__name__)
    register(app,authorized=lambda:rc.os.environ.get('RAW_TEST_AUTH')=='yes',context=lambda:(COMPANY,cutoff),received_root=tmp_path/'received',queue_root=tmp_path/'queue',status_root=tmp_path/'public-status')
    c=app.test_client()
    assert c.post('/v1/raw-batches',data=a.read_bytes()).status_code==401
    with patch.dict(rc.os.environ,RAW_TEST_AUTH='yes'):
        r=c.post('/v1/raw-batches',data=a.read_bytes());assert r.status_code==202 and r.json['published'] is False
        assert c.get('/v1/raw-batches/raw-http').json['status']=='queued'
        assert c.post('/v1/raw-batches',data=a.read_bytes()).status_code==202
        for name in ['raw-a','raw-b','raw-c']:(tmp_path/'queue'/name).write_text('{}')
        assert c.post('/v1/raw-batches',data=a.read_bytes()).status_code==202
        newer=tmp_path/'next.tar';ri.pack(inputs,newer,batch='raw-next',company=COMPANY,day=day)
        assert c.post('/v1/raw-batches',data=newer.read_bytes()).status_code==429
        assert not (tmp_path/'received/raw-next').exists()
        assert c.get('/v1/raw-batches/bad').status_code==400


def test_compact_ids_fit_existing_business_and_query_contracts():
    import re
    from interfaces.data_platform import RUN_ID
    suffix,source,business=rc.run_names(DAY,'a'*64)
    assert re.fullmatch(r'run_[a-z0-9_-]{3,45}',business)
    for name in (source, business+'_personnel_history_resources',business+'_study',source+'_history_resources'):
        assert RUN_ID.fullmatch(name)


def test_explicit_resume_needs_recorded_failed_state(inputs,tmp_path):
    a=make(inputs,tmp_path);stage(a,tmp_path)
    with pytest.raises(ValueError,match='recorded failed attempt'):
        rc.run(received=tmp_path/'received/raw-test',baseline=tmp_path/'baseline',root=tmp_path/'compute',day=DAY,company=COMPANY,minimum_cutoff='2026-10-24',resume_sources=True)


def test_recheck_rejects_nonfailed_candidate(tmp_path):
    output=tmp_path/'computed/raw-test';output.mkdir(parents=True)
    ri.write(output/'state.json',{'status':'running'})
    with pytest.raises(ValueError,match='failed sealed candidate'):
        rc.recheck(output=output,received=tmp_path/'received',baseline=tmp_path/'baseline',expected=tmp_path/'expected.json')


def test_setup_failure_is_durable_failed_state(inputs,tmp_path,approved_cutoff):
    a=make(inputs,tmp_path);stage(a,tmp_path)
    with patch.object(ri,'stage',side_effect=ValueError('injected freeze failure')):
        with pytest.raises(ValueError):
            rc.run(received=tmp_path/'received/raw-test',baseline=tmp_path/'baseline',root=tmp_path/'compute',day=DAY,company=COMPANY,minimum_cutoff='2026-10-24')
    state=json.loads((tmp_path/'compute/raw-test/state.json').read_bytes())
    assert state['status']=='failed' and state['published'] is False


def test_unknown_download_name_gets_safe_alias_and_honest_provenance(inputs,tmp_path):
    download=tmp_path/'unlabelled-download-uuid';download.write_bytes(inputs['cash'].read_bytes());inputs['cash']=download
    archive=make(inputs,tmp_path)
    manifest=stage(archive,tmp_path)
    stored=json.loads((tmp_path/'received/raw-test/manifest.json').read_bytes())
    assert stored['files']['cash']['filename']=='cash.xlsx'
    assert stored['files']['cash']['source_filename_unknown'] is True
    assert stored['files']['cash']['source_filename'] is None


def test_filename_provenance_cannot_claim_unknown_and_known(inputs,tmp_path):
    a=make(inputs,tmp_path);bad=tmp_path/'bad-name.tar'
    rewrite(a,bad,lambda m:m['files']['cash'].update(source_filename_unknown=True,source_filename='claimed.xlsx'))
    with pytest.raises(ValueError):stage(bad,tmp_path)
