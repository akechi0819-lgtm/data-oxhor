import json
from pathlib import Path
import tempfile
import unittest

import duckdb

from data_platform.query.evidence import file_ref
from data_platform.query.service import QueryError
from data_platform.sql_candidate import query_candidate


class SqlCandidateQueryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.candidate=self.root/'candidate';self.candidate.mkdir()
        db=self.candidate/'warehouse.duckdb'
        with duckdb.connect(str(db)) as con:
            con.execute('CREATE SCHEMA business; CREATE SCHEMA meta; CREATE SCHEMA config')
            con.execute("CREATE TABLE meta.identity AS SELECT 'run_sql_query_test' AS batch_id")
            con.execute('CREATE TABLE config.inputs AS SELECT 1 AS n UNION ALL SELECT 2')
            con.execute('CREATE VIEW business.numbers AS SELECT * FROM config.inputs')
            con.execute('CREATE MACRO business.selected_numbers(values_) AS TABLE SELECT * FROM config.inputs WHERE values_ IS NULL OR list_contains(values_, n)')
        (self.candidate/'candidate.json').write_text(json.dumps({
            'schema_version':'sql_warehouse_candidate.v1','batch_id':'run_sql_query_test',
            'database':file_ref(db,self.candidate,'application/vnd.duckdb'),
            'snapshots':{'training':'snapshot_test','abroad':'snapshot_study_test'},
            'query_relations':['numbers'],'query_macros':['selected_numbers'],
            'schemas':['business','meta','config']}))

    def query(self,sql,**kw):
        return query_candidate(candidate=self.candidate,batch_id='run_sql_query_test',sql=sql,
            run_id='run_sql_query_check',output_root=self.root/'evidence',**kw)

    def test_registered_view_returns_bound_evidence(self):
        response=self.query('SELECT sum(n) AS total FROM business.numbers')
        self.assertEqual(response['result']['rows'],[[3]])
        receipt=self.root/'evidence'/response['receipt']['path']
        self.assertTrue(receipt.is_file())

    def test_write_external_read_and_unregistered_source_are_rejected(self):
        for sql in ('DELETE FROM config.inputs',"SELECT * FROM read_json('/tmp/data.json')",'SELECT * FROM config.inputs'):
            with self.subTest(sql=sql),self.assertRaises(QueryError):self.query(sql)

    def test_query_limit_is_a_failure(self):
        with self.assertRaises(QueryError):self.query('SELECT * FROM business.numbers',max_rows=1)

    def test_registered_macro_is_allowed_but_dynamic_functions_remain_denied(self):
        self.assertEqual(self.query('SELECT * FROM business.selected_numbers([2])')['result']['rows'], [[2]])
        for sql in ('SELECT * FROM selected_numbers([2])',
                    'SELECT * FROM config.selected_numbers([2])',
                    "SELECT * FROM business.selected_numbers((SELECT list(n) FROM config.inputs))",
                    'SELECT * FROM business.unregistered(NULL)'):
            with self.subTest(sql=sql), self.assertRaises(QueryError):self.query(sql)

    def test_database_change_invalidates_sealed_candidate(self):
        with duckdb.connect(str(self.candidate/'warehouse.duckdb')) as con:
            con.execute('INSERT INTO config.inputs VALUES (3)')
        with self.assertRaises(ValueError):self.query('SELECT * FROM business.numbers')


if __name__=='__main__':unittest.main()
