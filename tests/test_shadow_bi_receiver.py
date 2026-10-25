"""Synthetic regression for the exact deployed receiver recovered into Git."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
try:
    import flask
except ModuleNotFoundError:
    raise unittest.SkipTest('Run receiver tests in the locked Superset/Flask runtime')


class ReceiverContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'receiver'
        self.token = 'synthetic-receiver-fixture'
        with patch.dict(os.environ, SHADOW_RECEIVER_ROOT=str(self.root),
                        SHADOW_RECEIVER_TOKEN_SHA256=hashlib.sha256(self.token.encode()).hexdigest()):
            spec = importlib.util.spec_from_file_location('synthetic_receiver',
                Path(__file__).resolve().parents[1] / 'dashboard_product/shadow_bi/p5/receiver.py')
            self.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.module)
        self.client = self.module.app.test_client()
        self.headers = {'Authorization': 'Bearer ' + self.token,
                        'X-Shadow-BI-Release': 'daily-fixture'}

    def archive(self, payload=b'{"value":1}\n', bad_hash=False):
        m = {'schema_version':'business_query_library.v1', 'batch_id':'run_fixture',
             'coverage':{'data_through':'2026-10-24'}, 'tables':{'facts':{'data':{
                'path':'tables/facts.jsonl','size_bytes':len(payload),
                'sha256':('0'*64 if bad_hash else hashlib.sha256(payload).hexdigest())}}}}
        out = io.BytesIO()
        with tarfile.open(fileobj=out, mode='w:gz') as tar:
            for name, body in [('library_manifest.json',json.dumps(m).encode()),('tables/facts.jsonl',payload)]:
                item=tarfile.TarInfo(name);item.size=len(body);tar.addfile(item,io.BytesIO(body))
        return out.getvalue()

    def test_authentication_is_required_for_upload_and_status(self):
        self.assertEqual(self.client.post('/v1/batches').status_code,401)
        self.assertEqual(self.client.get('/v1/batches/daily-fixture').status_code,401)
        self.assertEqual(self.client.post('/v1/batches',headers={'Authorization':'Bearer wrong'}).status_code,401)
        self.assertFalse(self.root.exists())

    def test_same_batch_is_idempotent_and_changed_content_is_rejected(self):
        body=self.archive()
        for _ in range(2):
            self.assertEqual(self.client.post('/v1/batches',data=body,headers=self.headers).status_code,202)
        self.assertEqual(self.client.post('/v1/batches',data=self.archive(b'{"value":2}\n'),headers=self.headers).status_code,409)
        self.assertEqual((self.root/'daily-fixture/tables.tar.gz').read_bytes(),body)
        self.assertFalse(list(self.root.glob('.incoming-*')))
        self.assertTrue((self.root/'pending/daily-fixture').is_file())

    def test_invalid_hash_does_not_queue_or_publish(self):
        self.assertEqual(self.client.post('/v1/batches',data=self.archive(bad_hash=True),headers=self.headers).status_code,400)
        self.assertFalse((self.root/'pending/daily-fixture').exists())
        self.assertFalse((self.root/'daily-fixture').exists())

    def test_cutoff_cannot_move_backwards(self):
        m=self.root.parent/'current/library/library_manifest.json';m.parent.mkdir(parents=True)
        m.write_text(json.dumps({'coverage':{'data_through':'2026-10-25'}}))
        self.assertEqual(self.client.post('/v1/batches',data=self.archive(),headers=self.headers).status_code,400)
        self.assertFalse((self.root/'pending/daily-fixture').exists())

    def test_archive_paths_and_resource_limits_fail_closed(self):
        def item(name,size=0):
            entry=tarfile.TarInfo(name);entry.size=size;return entry
        manifest=item('library_manifest.json')
        rejected=[[manifest,item('../escape')], [manifest,item('/escape')],
                  [manifest,item('tables/x',256*1024**2+1)],
                  [manifest]+[item('tables/'+str(i),256*1024**2) for i in range(9)],
                  [manifest]+[item('tables/'+str(i)) for i in range(2048)]]
        link=item('tables/link');link.type=tarfile.SYMTYPE;link.linkname='/etc/passwd';rejected.append([manifest,link])
        for members in rejected:
            with self.subTest(members=len(members)):
                with self.assertRaises(ValueError):self.module._safe_members(members)
        accepted=[manifest]+[item('tables/'+str(i),30*1024**2) for i in range(39)]
        self.assertEqual(len(self.module._safe_members(accepted)),40)


if __name__ == '__main__':
    unittest.main()
