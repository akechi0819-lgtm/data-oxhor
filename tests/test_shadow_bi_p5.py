import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from argparse import Namespace
from unittest import mock

from dashboard_product.shadow_bi.p5.daily import package_tables
from data_platform.query.evidence import EvidenceError
from data_platform.query.service import execute_query
from tests.platform.test_query_service import warehouse


class SealedTransferTests(unittest.TestCase):
    def prepare(self, root):
        source, presentation = root/'source', root/'presentation'
        source.mkdir(); presentation.mkdir()
        (source/'tables').mkdir()
        table = source/'tables/known.jsonl'
        table.write_text('{"orders":7}\n')
        (source/'business.duckdb').write_bytes(b'private customer database must stay local')
        manifest = {'tables': {'known': {'data': {'path': 'tables/known.jsonl',
                    'sha256': hashlib.sha256(table.read_bytes()).hexdigest()}}}}
        (presentation/'library_manifest.json').write_text(json.dumps(manifest))
        return source, presentation, manifest

    def test_only_manifest_jsonl_is_transferred(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); source, presentation, _ = self.prepare(root)
            package_tables(source, presentation, root/'transfer')
            files = {p.relative_to(root/'transfer').as_posix() for p in (root/'transfer').rglob('*') if p.is_file()}
            self.assertEqual(files, {'tables/known.jsonl', 'library_manifest.json'})

    def test_corruption_prevents_package(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); source, presentation, _ = self.prepare(root)
            (source/'tables/known.jsonl').write_text('corrupted')
            with self.assertRaisesRegex(ValueError, '摘要不符'):
                package_tables(source, presentation, root/'transfer')

    def test_path_outside_manifest_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); source, presentation, manifest = self.prepare(root)
            manifest['tables']['known']['data']['path'] = '../outside.jsonl'
            (presentation/'library_manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, '路径无效'):
                package_tables(source, presentation, root/'transfer')


class SourceReceiptCollectionTests(unittest.TestCase):
    def build_fixture(self, root, corrupt=False):
        from dashboard_product.shadow_bi import library
        db = root/'warehouse.duckdb'
        warehouse(db)
        run = 'run_receipt_fixture'
        result = execute_query(warehouse=db, snapshot_id='snapshot_query_test',
            sql='SELECT * FROM landing.values_table', run_id=run+'_orders',
            output_root=root/'Output/Query')
        receipt = root/'Output/Query'/(run+'_orders')/result['receipt']['path']
        if corrupt:
            (receipt.parent/'result.json').write_text('{}')
        unrelated = root/'Output/ShadowDaily/old/presentation/receipt.json'
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text(json.dumps({'schema_version':'business_query_receipt.v1',
                                        'run_id':'run_p3_annual_facts_00000'}))
        study = root/'Work/StudyAbroad/current.json'
        study.parent.mkdir(parents=True)
        study.write_text(json.dumps({'source_lineage':'Work/lineage.json'}))
        (root/'Work/lineage.json').write_text('{}')
        model = {'public':{'metadata':{},'periods':[{'id':'2026-10','teams':[{
                     'id':'total','lines':{'training':{'orders':{'actual':3},'cash':{'actual':125}}}
                 }]}]}, 'segments':{}, 'online_data':{},
                 'personnel_details':{}, 'diagnostics':{}}
        def calculate(*args, **kwargs):
            (root/'Output/ShadowBI'/run).mkdir(parents=True)
            return model
        args = Namespace(workspace=root, run_id=run, as_of_date='2026-10-24',
                         snapshot_id='snapshot_query_test', study_abroad_snapshot_id='snapshot_study_fixture')
        # 计算内容与回执筛选正交；来源回执由真实受控查询生成并完整校验。
        with mock.patch.object(library,'binding',return_value={'inputs':{'fixture':'a'*64},'rules':{}}), \
             mock.patch.object(library,'calculate',side_effect=calculate), \
             mock.patch.object(library,'tables',return_value={'facts':[{'id':'fixture'}]}), \
             mock.patch('dashboard_product.shadow_bi.acquisition.scoped_tables',return_value={}):
            result = library.build(args)
        return root/'Output/ShadowBI'/run/'library/library_manifest.json', result

    def test_unrelated_presentation_receipt_does_not_break_next_build(self):
        with tempfile.TemporaryDirectory() as t:
            manifest_path, _ = self.build_fixture(Path(t))
            manifest = json.loads(manifest_path.read_text())
            self.assertEqual(len(manifest['source_queries']), 1)
            self.assertEqual(manifest['source_queries'][0]['source_ids'], ['fixture'])

    def test_build_returns_key_metrics_without_calculated_intermediates(self):
        from dashboard_product.shadow_bi.p5.raw_compute import key_metrics
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            manifest_path, model = self.build_fixture(root)
            output = root/'Output/ShadowBI/run_receipt_fixture'
            self.assertFalse((output/'calculated').exists())
            self.assertIsNotNone(model['public'])

            expected = root/'expected/reference.json'
            expected.parent.mkdir()
            expected.write_text('{}')
            wanted = [['2026-10','total','training','orders',3],
                      ['2026-10','total','training','cash',125]]
            (expected.parent/'expected-key-metrics.json').write_text(json.dumps(wanted))
            self.assertEqual(key_metrics(model['public'],expected),
                             {'metrics':2,'actual':wanted,'match':True})

            (expected.parent/'expected-key-metrics.json').write_text(json.dumps([]))
            with self.assertRaisesRegex(ValueError,'same-source business metrics differ'):
                key_metrics(model['public'],expected)

            self.assertTrue(manifest_path.is_file())

    def test_corrupt_current_source_query_still_rejects_build(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(EvidenceError):
                self.build_fixture(Path(t), corrupt=True)
            self.assertFalse((Path(t)/'Output/ShadowBI/run_receipt_fixture/library/library_manifest.json').exists())


class OnlinePlatformScopeTests(unittest.TestCase):
    def project(self, facts, order_facts=None):
        from dashboard_product.management.online_view import online_view
        coverage={'start_date':'2026-06-01','through_date':'2026-06-02'}
        lines={line:{'orders':{'actual':0},'cash':{'actual':0}} for line in ('training','abroad')}
        lines['abroad']['source_coverage']=coverage
        period={'id':'test','status':'available','start_date':'2026-06-01','through_date':'2026-06-02',
                'prior_start_date':'2025-06-01','prior_through_date':'2025-06-02',
                'teams':[{'id':'online','business_groups':[],'channels':[],'lines':lines}]}
        public={'schema_version':'test','metadata':{'data_through':'2026-06-02',
                'study_abroad_source':coverage},'periods':[period]}
        return online_view(public,facts,{},order_facts=order_facts)['periods'][0]['lines']['training']['channels']

    def test_cross_scope_linked_cash_uses_full_order_context_without_changing_scope(self):
        order={'fact_id':'p-order','work_order_id':'shared','business_line':'training',
               'team_id':'online_platform','business_group':'大学','acquisition_mode':'被动',
               'metric':'orders','value':1,'second_channel':'抖音来客','first_channel':'平台',
               'event_date':'2026-06-02'}
        cash={**order,'fact_id':'a-cash','acquisition_mode':'主动','metric':'cash',
              'value':100,'second_channel':'灵蹊'}
        full=[order,cash]
        active=self.project([cash],order_facts=full)
        passive=self.project([order],order_facts=full)
        all_rows=self.project(full,order_facts=full)
        self.assertEqual([r['name'] for r in active],['抖音'])
        self.assertEqual(active[0]['cash'],100)
        self.assertEqual(passive[0]['cash'],0)
        self.assertEqual(all_rows[0]['cash'],active[0]['cash']+passive[0]['cash'])
        self.assertEqual(cash['acquisition_mode'],'主动')

    def test_scope_conservation_brand_additivity_and_group_drilldown(self):
        def fact(key,mode,metric,value,label,group,prior=False):
            return {'fact_id':key,'work_order_id':key,'business_line':'training',
                    'team_id':'online_platform','business_group':group,'acquisition_mode':mode,
                    'metric':metric,'value':value,'second_channel':label,'first_channel':'平台',
                    'event_date':'2025-06-02' if prior else '2026-06-02'}
        facts=[fact('p','被动','orders',1,'抖音来客','大学'),
               fact('a','主动','orders',1,'抖音本地推','高中'),
               fact('pp','被动','orders',1,'头条','大学',True),
               fact('ap','主动','orders',1,'巨量飞鱼','高中',True),
               fact('pc','被动','cash',35,'抖音来客','大学'),
               fact('ac','主动','cash',10,'抖音本地推','高中'),
               fact('an','主动','cash',-2,'抖音本地推','高中'),
               fact('x','主动','orders',1,'小红书','大学')]
        results={scope:{r['name']:r for r in self.project(
                    facts if scope=='全部' else [f for f in facts if f['acquisition_mode']==scope])}
                 for scope in ('被动','主动','全部')}
        self.assertEqual(set(results['全部']), {'抖音','小红书'})
        for platform,row in results['全部'].items():
            for metric in ('orders','prior_orders','today_orders','cash','prior_cash'):
                self.assertAlmostEqual(row[metric],sum(results[s].get(platform,{}).get(metric,0)
                                                       for s in ('被动','主动')))
        for scope,rows in results.items():
            current=[f for f in facts if f['event_date'].startswith('2026')
                     and (scope=='全部' or f['acquisition_mode']==scope)]
            for metric,field in [('orders','orders'),('cash','cash')]:
                self.assertAlmostEqual(sum(r[field] for r in rows.values()),
                                       sum(f['value'] for f in current if f['metric']==metric))
            for row in rows.values():
                for field in ('orders','prior_orders','cash','prior_cash'):
                    self.assertAlmostEqual(row[field],sum(g[field] for g in row['groups']))
                self.assertNotIn('heads',row)
                self.assertIsNone(row.get('advertising',{}).get('roi'))
        self.assertEqual({g['name'] for g in results['全部']['抖音']['groups']},{'大学','高中'})


if __name__ == '__main__':
    unittest.main()
