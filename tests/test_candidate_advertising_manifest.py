"""Candidate fee selection keeps registered input immutable and binds native bytes."""
from pathlib import Path
import hashlib
import json
import tempfile
import unittest
from unittest import mock
from dashboard_product.management import advertising_costs
from dashboard_product.shadow_bi import library


class CandidateManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.workspace = self.root / 'workspace'
        self.output = self.root / 'output'; self.output.mkdir()
        (self.workspace / 'Work').mkdir(parents=True)
        (self.workspace / 'Work/workspace.json').write_text(json.dumps({'current_warehouse_path':'unused.duckdb'}))
        self.registered = self.workspace / 'Input/AdvertisingCosts/sources.json'
        self.registered.parent.mkdir(parents=True); self.registered.write_text('registered input sentinel')
        self.native = self.root / 'native.csv'
        self.native.write_text('周期,投放ID,账户类型,广告主账户ID,总消耗\n20261027,123,代理商子账户,brand,2\n')
        self.manifest = self.root / 'candidate.json'
        self.entry = {'source_id':'xhs_candidate','kind':'xhs_mcc_daily','path':str(self.native),
                      'sha256':hashlib.sha256(self.native.read_bytes()).hexdigest(),
                      'start_date':'2026-10-27','end_date':'2026-10-27',
                      'brand_accounts':{'brand':{'business_line':'training','business_group':'大学'}}}
        self.manifest.write_text(json.dumps({'sources':[self.entry]}))

    def test_explicit_selection_uses_candidate_without_registered_read_or_write(self):
        online = {'metadata':{'data_through':'2026-10-27'},'periods':[]}
        before = self.registered.read_bytes()
        with mock.patch.object(advertising_costs, 'query', return_value=([], 'receipt')):
            advertising_costs.attach_advertising(online, [], self.workspace, 'snapshot_fixture',
                'run_fixture', self.output, manifest_path=self.manifest)
        costs = json.loads((self.output/'advertising_sources.json').read_text())
        self.assertEqual(costs['rows'][0]['source_id'],'xhs_candidate:123')
        self.assertEqual(costs['rows'][0]['amount'],2)
        self.assertEqual(self.registered.read_bytes(),before)

    def test_explicit_missing_candidate_never_falls_back(self):
        with mock.patch.object(advertising_costs, 'query') as query:
            with self.assertRaises(FileNotFoundError):
                advertising_costs.attach_advertising({}, [], self.workspace, 'snapshot_fixture',
                    'run_fixture', self.output, manifest_path=self.root/'missing.json')
        query.assert_not_called()

    def test_default_selection_keeps_registered_manifest_behavior(self):
        self.registered.write_text(json.dumps({'sources':[]}))
        online = {'metadata':{'data_through':'2026-10-27'},'periods':[]}
        with mock.patch.object(advertising_costs, 'query', return_value=([], 'receipt')):
            advertising_costs.attach_advertising(online, [], self.workspace, 'snapshot_fixture',
                'run_fixture', self.output)
        self.assertEqual(json.loads((self.output/'advertising_sources.json').read_text())['rows'],[])

    def test_library_binding_includes_explicit_manifest_and_native_closure(self):
        with mock.patch.object(library,'source_files',return_value=[]), \
             mock.patch.object(library,'code_files',return_value=[]):
            default = library.binding(self.workspace)
            bound = library.binding(self.workspace,self.manifest)
            self.assertNotIn('advertising_inputs',default)
            self.assertEqual(bound['advertising_inputs']['manifest']['sha256'],
                             hashlib.sha256(self.manifest.read_bytes()).hexdigest())
            self.assertEqual(bound['advertising_inputs']['files'][str(self.native.resolve())],self.entry['sha256'])
            self.native.write_text(self.native.read_text().replace(',2\n',',3\n'))
            with self.assertRaisesRegex(ValueError,'sha256'):
                library.binding(self.workspace,self.manifest)
        self.assertEqual(self.registered.read_text(),'registered input sentinel')

    def test_business_only_binding_does_not_read_registered_fee_inputs(self):
        empty = self.root/'business-only.json'
        empty.write_text(json.dumps({'sources': []}))
        business = self.workspace/'Work/workspace.json'
        real_sha = library.sha
        def reject_registered(path):
            if path.is_relative_to(self.registered.parent):
                raise PermissionError('registered fees are unavailable')
            return real_sha(path)
        with mock.patch.object(library, 'source_files', return_value=[business, self.registered]), \
             mock.patch.object(library, 'code_files', return_value=[]), \
             mock.patch.object(library, 'sha', side_effect=reject_registered):
            bound = library.binding(self.workspace, empty)
            self.assertEqual(set(bound['inputs']), {'Work/workspace.json'})
            self.assertEqual(bound['advertising_inputs']['files'], {})
            with self.assertRaises(PermissionError):
                library.binding(self.workspace)


if __name__=='__main__': unittest.main()
