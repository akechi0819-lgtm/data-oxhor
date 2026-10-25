from pathlib import Path
import json
import tempfile
import unittest
import duckdb
from data_platform.query.evidence import encode,file_ref,EvidenceError
from data_platform.query.service import QueryError
from data_platform.business_library import execute_library_query,read_library_result,describe_library

class BusinessLibraryTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.db=self.root/'business.duckdb'
        with duckdb.connect(str(self.db)) as c:
            c.execute('CREATE SCHEMA queries');c.execute("CREATE TABLE queries.batch AS SELECT 'run_fixture' AS batch_id")
            c.execute("CREATE TABLE queries.facts AS SELECT * FROM (VALUES ('a',1.25::DECIMAL(12,2)),('b',2.50::DECIMAL(12,2))) t(id,value)")
        self.manifest={'schema_version':'business_query_library.v1','batch_id':'run_fixture',
            'binding':{'inputs':{'file':'a'*64},'rules':{'rule':'b'*64}},
            'snapshots':{'training':'snapshot_fixture'},'source_queries':[{'snapshot_ref':{'snapshot_id':'snapshot_fixture'}}],
            'tables':{'facts':{'rows':2}},'database':file_ref(self.db,self.root,'application/vnd.duckdb')}
        (self.root/'library_manifest.json').write_bytes(encode(self.manifest))
    def query(self,sql,**kw):
        return execute_library_query(library=self.root,batch_id='run_fixture',sql=sql,run_id='run_query_fixture',output_root=self.root/'out',**kw)
    def test_decimal_and_page_receipt(self):
        r=self.query('SELECT id,value FROM queries.facts ORDER BY id LIMIT ? OFFSET ?;',parameters=[1,1])
        self.assertEqual(read_library_result(r,output_root=self.root/'out')['rows'],[['b','2.50']])
        self.assertEqual(describe_library(library=self.root,batch_id='run_fixture')['status'],'passed')
        receipt=self.root/'out'/r['run_id']/r['receipt']['path']
        data=receipt.parent/'result.json';data.write_text('{}')
        with self.assertRaises(EvidenceError):read_library_result(r,output_root=self.root/'out')
    def test_readonly_and_external_rejection(self):
        for sql in ['DELETE FROM queries.facts',"SELECT * FROM read_csv('/tmp/nonexistent')",'SELECT * FROM information_schema.tables','SELECT 1; SELECT 2']:
            with self.subTest(sql=sql),self.assertRaises(QueryError):self.query(sql)
    def test_limits_and_identity(self):
        with self.assertRaises(QueryError):self.query('SELECT * FROM queries.facts',max_rows=1)
        with self.assertRaises(QueryError):describe_library(library=self.root,batch_id='run_wrong')
        with self.db.open('ab') as f:f.write(b'changed')
        with self.assertRaises(EvidenceError):self.query('SELECT * FROM queries.facts')
    def test_missing_provenance(self):
        self.manifest['binding']['inputs']={}
        (self.root/'library_manifest.json').write_bytes(encode(self.manifest))
        with self.assertRaises(QueryError):self.query('SELECT * FROM queries.facts')

    def test_lossless_nested_row_and_unrounded_credit(self):
        from dashboard_product.shadow_bi.library import write_table,table_digest
        rows=[{'id':'a','payload':{'items':[1,None]},'weight':'0.3333333333333333333333333333','credited_value':'123.4567890123456789012345678'}]
        with duckdb.connect(str(self.db)) as c:
            info=write_table(c,self.root,'credits',rows)
        self.manifest['tables']['credits']=info
        self.manifest['database']=file_ref(self.db,self.root,'application/vnd.duckdb')
        (self.root/'library_manifest.json').write_bytes(encode(self.manifest))
        data=read_library_result(self.query('SELECT row_json,weight,credited_value FROM queries.credits'),output_root=self.root/'out')
        self.assertEqual(json.loads(data['rows'][0][0]),rows[0])
        self.assertEqual(data['rows'][0][1:], [rows[0]['weight'],rows[0]['credited_value']])
        self.assertEqual(table_digest(rows),table_digest(list(reversed(rows))))
