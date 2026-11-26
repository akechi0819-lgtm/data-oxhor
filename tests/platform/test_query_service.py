from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import duckdb

from data_platform.query.evidence import verify_receipt, read_query_result
from tests.evidence_helpers import manifest
from data_platform.query.service import QueryError, describe_warehouse, execute_query, promote_query, run_saved_query


def warehouse(path: Path, snapshot_id: str = "snapshot_query_test") -> None:
    with duckdb.connect(str(path)) as connection:
        for schema in ("ingest", "landing", "quality", "queries", "private"):
            connection.execute(f"CREATE SCHEMA {schema}")
        connection.execute("CREATE TABLE ingest.sources(source_id VARCHAR, snapshot_id VARCHAR)")
        connection.execute("INSERT INTO ingest.sources VALUES ('fixture', ?)", [snapshot_id])
        connection.execute("CREATE TABLE ingest.sheets(source_id VARCHAR, target_table VARCHAR, header_columns JSON)")
        connection.execute("INSERT INTO ingest.sheets VALUES ('fixture', 'values_table', ?)", [json.dumps([
            {"technical_name": "category", "original_name": "分类"},
            {"technical_name": "amount", "original_name": "金额"},
        ], ensure_ascii=False)])
        connection.execute("CREATE TABLE landing.values_table(category VARCHAR, amount INTEGER)")
        connection.execute("INSERT INTO landing.values_table VALUES ('a',1),('a',2),('b',3)")
        connection.execute("CREATE TABLE quality.issues(issue_code VARCHAR, source_id VARCHAR, sheet_name VARCHAR, source_row_number BIGINT)")
        connection.execute("INSERT INTO quality.issues VALUES ('TEST','fixture','Sheet1',1)")
        connection.execute("CREATE TABLE private.secret(value INTEGER)")
        connection.execute("INSERT INTO private.secret VALUES (7)")

    manifest(path, snapshot_id)

class QueryServiceTests(unittest.TestCase):
    def test_describe_and_read_query_features(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "warehouse.duckdb"
            warehouse(db)
            before = hashlib.sha256(db.read_bytes()).hexdigest()
            described = describe_warehouse(warehouse=db, snapshot_id="snapshot_query_test")
            self.assertEqual(described["status"], "passed")
            self.assertFalse(any(item["schema"] == "private" for item in described["relations"]))
            values = next(item for item in described["relations"] if item["schema"] == "landing" and item["name"] == "values_table")
            self.assertEqual(["分类", "金额"], [item["header_label"] for item in values["columns"]])
            queries = [
                "SELECT * FROM landing.values_table ORDER BY category, amount",
                "WITH selected AS (SELECT * FROM landing.values_table) SELECT category, sum(amount) total FROM selected GROUP BY category ORDER BY category",
                "SELECT category, amount, row_number() OVER (PARTITION BY category ORDER BY amount) AS row_rank FROM landing.values_table",
                "SELECT a.category, a.amount, b.amount other FROM landing.values_table a JOIN landing.values_table b USING(category)",
            ]
            for sql in queries:
                with self.subTest(sql=sql):
                    result = execute_query(warehouse=db, snapshot_id="snapshot_query_test", sql=sql, run_id="run_query_test", output_root=root)
                    self.assertEqual(result["status"], "passed")
                    self.assertEqual(verify_receipt(root / "run_query_test" / result["receipt"]["path"])[0]["referenced_source_ids"], ["fixture"])

    def test_provenance_uses_sql_parser_for_literals_comments_and_empty_results(self):
        queries = [
            ("SELECT '--说明' AS note, amount FROM landing.values_table", None, 3),
            ("SELECT '/*说明*/ landing.fake' AS note FROM landing.values_table -- landing.fake", None, 3),
            ("/* outer /* nested */ comment */ SELECT * FROM LANDING.VALUES_TABLE WHERE false", None, 0),
            ("WITH selected AS (SELECT * FROM landing.values_table WHERE amount > ?) SELECT * FROM selected", [1], 2),
            ("SELECT '$category ? --' AS note FROM landing.values_table WHERE category=$category", {"category": "a"}, 2),
            ("SELECT * FROM landing.values_table a NATURAL JOIN landing.values_table b", None, 3),
            ("SELECT a.* FROM landing.values_table a JOIN landing.values_table b ON a.amount=b.amount AND EXISTS (SELECT 1 FROM landing.values_table c WHERE c.amount=?)", [1], 3),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "warehouse.duckdb"
            warehouse(db)
            for sql, parameters, row_count in queries:
                with self.subTest(sql=sql):
                    result = execute_query(warehouse=db, snapshot_id="snapshot_query_test", sql=sql,
                                           parameters=parameters, run_id="run_query_test", output_root=root)
                    receipt = verify_receipt(root / "run_query_test" / result["receipt"]["path"])[0]
                    self.assertEqual(receipt["referenced_relations"], ["landing.values_table"])
                    self.assertEqual(receipt["referenced_source_ids"], ["fixture"])
                    self.assertEqual(len(read_query_result(result, output_root=root)["rows"]), row_count)
            result = execute_query(warehouse=db, snapshot_id="snapshot_query_test",
                                   sql="SELECT 'landing.values_table' AS note", run_id="run_query_test", output_root=root)
            receipt = verify_receipt(root / "run_query_test" / result["receipt"]["path"])[0]
            self.assertEqual(receipt["referenced_relations"], [])

    def test_provenance_expands_views_and_preserves_registered_quoted_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "warehouse.duckdb"
            warehouse(db)
            with duckdb.connect(str(db)) as connection:
                connection.execute('CREATE TABLE landing."Odd.Name""X"(amount INTEGER)')
                connection.execute("INSERT INTO ingest.sheets VALUES ('quoted', ?, '[]')", ['Odd.Name"X'])
                connection.execute('CREATE VIEW queries.selected AS SELECT * FROM landing."Odd.Name""X"')
            manifest(db, 'snapshot_query_test')
            for sql in ['SELECT * FROM LANDING."odd.name""x"', 'SELECT * FROM queries.selected']:
                with self.subTest(sql=sql):
                    result = execute_query(warehouse=db, snapshot_id="snapshot_query_test", sql=sql,
                                           run_id="run_query_test", output_root=root)
                    receipt = verify_receipt(root / "run_query_test" / result["receipt"]["path"])[0]
                    self.assertEqual(receipt["referenced_relations"], ['landing.Odd.Name"X'])
                    self.assertEqual(receipt["referenced_source_ids"], ["quoted"])

    def test_provenance_rejects_unregistered_relations_and_unresolved_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "warehouse.duckdb"
            warehouse(db)
            with duckdb.connect(str(db)) as connection:
                connection.execute("CREATE TABLE landing.unregistered(amount INTEGER)")
                connection.execute("CREATE VIEW queries.joined AS SELECT * FROM landing.values_table a JOIN landing.values_table b USING(category)")
            manifest(db, "snapshot_query_test")
            queries = [
                ("SELECT * FROM landing.unregistered", None),
                ("SELECT * FROM queries.joined", None),
                ("SELECT * FROM query_table($table_name)", {"table_name": "landing.values_table"}),
            ]
            for sql, parameters in queries:
                with self.subTest(sql=sql), self.assertRaises(QueryError) as error:
                    execute_query(warehouse=db, snapshot_id="snapshot_query_test", sql=sql,
                                  parameters=parameters, run_id="run_query_test", output_root=root)
                self.assertEqual(error.exception.code, "QUERY_PROVENANCE_INVALID")

    def test_parameter_dependent_table_selection_cannot_emit_false_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "warehouse.duckdb"
            warehouse(db)
            with duckdb.connect(str(db)) as connection:
                connection.execute("CREATE TABLE landing.other_table AS SELECT * FROM landing.values_table WHERE false")
                connection.execute("INSERT INTO ingest.sources VALUES ('other', 'snapshot_query_test')")
                connection.execute("INSERT INTO ingest.sheets VALUES ('other', 'other_table', '[]')")
            manifest(db, "snapshot_query_test")
            sql = "SELECT * FROM query_table(CASE WHEN ? THEN 'landing.values_table' ELSE 'landing.other_table' END)"
            for parameters in ([True], [False]):
                with self.subTest(parameters=parameters), self.assertRaises(QueryError) as error:
                    execute_query(warehouse=db, snapshot_id="snapshot_query_test", sql=sql,
                                  parameters=parameters, run_id="run_query_test", output_root=root)
                self.assertEqual(error.exception.code, "QUERY_PROVENANCE_INVALID")
            self.assertFalse((root / "run_query_test").exists())

    def test_rejects_writes_external_access_and_multiple_statements(self):
        denied = [
            "CREATE TABLE landing.bad(a int)",
            "INSERT INTO landing.values_table VALUES ('x', 1)",
            "COPY (SELECT 1) TO '/tmp/query.csv'",
            "ATTACH '/tmp/other.db' AS other",
            "DETACH other",
            "INSTALL httpfs",
            "LOAD httpfs",
            "PRAGMA version",
            "CALL checkpoint()",
            "SELECT * FROM read_csv('/tmp/query.csv')",
            "SELECT * FROM duckdb_tables()",
            "SELECT * FROM information_schema.tables",
            "SELECT * FROM system.information_schema.columns",
            'SELECT * FROM "information_schema"."tables"',
            'SELECT * FROM "system"."information_schema"."columns"',
            "SELECT 1; SELECT 2",
            "SELECT * FROM private.secret",
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "warehouse.duckdb"
            warehouse(db)
            before = hashlib.sha256(db.read_bytes()).hexdigest()
            for sql in denied:
                with self.subTest(sql=sql), self.assertRaises(QueryError):
                    execute_query(warehouse=db, snapshot_id="snapshot_query_test", sql=sql, run_id="run_query_test", output_root=root)
            after = hashlib.sha256(db.read_bytes()).hexdigest()
            self.assertEqual(after, before)
            with duckdb.connect(str(db), read_only=True) as connection:
                self.assertEqual(connection.execute("SELECT count(*) FROM landing.values_table").fetchone()[0], 3)
            with self.assertRaises(QueryError) as invalid_run:
                execute_query(warehouse=db, snapshot_id="snapshot_query_test", sql="SELECT 1", run_id="../escape", output_root=root)
            self.assertEqual(invalid_run.exception.code, "RUN_ID_INVALID")

    def test_row_byte_and_artifact_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "warehouse.duckdb"
            warehouse(db)
            with self.assertRaises(QueryError) as row_error:
                execute_query(warehouse=db, snapshot_id="snapshot_query_test", sql="SELECT * FROM landing.values_table", run_id="run_query_test", output_root=root, max_rows=2)
            self.assertEqual(row_error.exception.code, "QUERY_LIMIT_EXCEEDED")
            with self.assertRaises(QueryError) as byte_error:
                execute_query(warehouse=db, snapshot_id="snapshot_query_test", sql="SELECT repeat('x', 1000)", run_id="run_query_test", output_root=root, max_result_bytes=100)
            self.assertEqual(byte_error.exception.code, "QUERY_LIMIT_EXCEEDED")
            result = execute_query(warehouse=db, snapshot_id="snapshot_query_test", sql="SELECT repeat('x', 1000)", run_id="run_query_test", output_root=root, inline_bytes=10)
            self.assertIsNone(result["result"])
            self.assertTrue((root / "run_query_test" / result["receipt"]["path"]).is_file())
            self.assertEqual(1, len(read_query_result(result, output_root=root)["rows"]))

    def test_failed_receipt_does_not_remove_existing_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            db=root/'warehouse.duckdb'
            warehouse(db)
            good=execute_query(warehouse=db,snapshot_id='snapshot_query_test',sql='SELECT 1',run_id='run_query_test',output_root=root)
            with mock.patch('data_platform.query.service.verify_receipt',side_effect=ValueError('failed verification')):
                with self.assertRaises(ValueError):
                    execute_query(warehouse=db,snapshot_id='snapshot_query_test',sql='SELECT 2',run_id='run_query_test',output_root=root)
            self.assertEqual([[1]],read_query_result(good,output_root=root)['rows'])
            self.assertEqual(1,len(list((root/'run_query_test/data/query_results').iterdir())))

    def test_promote_requires_confirmation_is_versioned_and_parameterized(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "warehouse.duckdb"
            registry = root / "registry"
            warehouse(db)
            before = hashlib.sha256(db.read_bytes()).hexdigest()
            sql = "SELECT * FROM landing.values_table WHERE category = $category ORDER BY amount"
            with self.assertRaises(QueryError):
                promote_query(warehouse=db, snapshot_id="snapshot_query_test", sql=sql, registry_root=registry, query_id="category_values", version="v1", confirmed_by="")
            promoted = promote_query(warehouse=db, snapshot_id="snapshot_query_test", sql=sql, registry_root=registry, query_id="category_values", version="v1", confirmed_by="user@example")
            self.assertEqual(promoted["status"], "passed")
            self.assertTrue((registry / "category_values/v1/query.sql").is_file())
            with self.assertRaises(QueryError) as duplicate:
                promote_query(warehouse=db, snapshot_id="snapshot_query_test", sql=sql, registry_root=registry, query_id="category_values", version="v1", confirmed_by="user@example")
            self.assertEqual(duplicate.exception.code, "QUERY_VERSION_EXISTS")
            result = run_saved_query(warehouse=db, snapshot_id="snapshot_query_test", registry_root=registry, query_id="category_values", version="v1", parameters={"category": "a"}, run_id="run_query_test", output_root=root, max_rows=10, max_result_bytes=10000)
            self.assertEqual(len(read_query_result(result, output_root=root)["rows"]), 2)
            self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(), before)
            manifest = json.loads((registry / "category_values/v1/manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["sha256"], hashlib.sha256((registry / "category_values/v1/query.sql").read_bytes()).hexdigest())

    def test_saved_query_runs_against_another_valid_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "warehouse.duckdb"
            other_db = root / "other" / "warehouse.duckdb"
            other_db.parent.mkdir()
            registry = root / "registry"
            warehouse(db)
            promote_query(warehouse=db, snapshot_id="snapshot_query_test", sql="SELECT * FROM landing.values_table", registry_root=registry, query_id="snapshot_bound", version="v1", confirmed_by="user@example")
            warehouse(other_db, snapshot_id="snapshot_other")
            result = run_saved_query(warehouse=other_db, snapshot_id="snapshot_other", registry_root=registry, query_id="snapshot_bound", version="v1", parameters=None, run_id="run_query_test", output_root=root, max_rows=10, max_result_bytes=10000)
            self.assertEqual(result["snapshot_id"], "snapshot_other")

    def test_retired_saved_query_id_and_version_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "warehouse.duckdb"
            registry = root / "registry"
            warehouse(db)
            retired = [("dashboard_actuals", f"v{n}") for n in range(9, 15)]
            retired.append(("attributed_passive_reported_cash", "v1"))
            for query_id, version in retired:
                with self.subTest(query_id=query_id, version=version):
                    target = registry / query_id / version
                    target.mkdir(parents=True)
                    sql = b"SELECT 1\n"
                    (target / "query.sql").write_bytes(sql)
                    (target / "manifest.json").write_text(json.dumps({
                        "query_id": query_id, "version": version,
                        "sql_path": "query.sql", "sha256": hashlib.sha256(sql).hexdigest(),
                    }))
                    with self.assertRaises(QueryError) as error:
                        run_saved_query(warehouse=db, snapshot_id="snapshot_query_test", registry_root=registry, query_id=query_id, version=version, parameters=None, run_id="run_query_test", output_root=root, max_rows=10, max_result_bytes=10000)
                    self.assertEqual(error.exception.code, "SAVED_QUERY_RETIRED")
                    with self.assertRaises(QueryError) as error:
                        promote_query(warehouse=db, snapshot_id="snapshot_query_test", sql="SELECT 1", registry_root=registry, query_id=query_id, version=version, confirmed_by="user")
                    self.assertEqual(error.exception.code, "SAVED_QUERY_RETIRED")
            for query_id, version in [("dashboard_actuals", "v15"), ("other_query", "v9")]:
                promote_query(warehouse=db, snapshot_id="snapshot_query_test", sql="SELECT 1", registry_root=registry, query_id=query_id, version=version, confirmed_by="user")
                result = run_saved_query(warehouse=db, snapshot_id="snapshot_query_test", registry_root=registry, query_id=query_id, version=version, parameters=None, run_id="run_query_test", output_root=root, max_rows=10, max_result_bytes=10000)
                self.assertEqual(result["status"], "passed")

    def test_select_string_literal_with_denied_word_is_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "warehouse.duckdb"
            warehouse(db)
            result = execute_query(warehouse=db, snapshot_id="snapshot_query_test", sql="SELECT 'copy' AS word", run_id="run_query_test", output_root=root)
            self.assertEqual(result["result"]["rows"], [["copy"]])


if __name__ == "__main__":
    unittest.main()
