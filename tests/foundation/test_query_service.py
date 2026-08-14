from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import duckdb

from data_foundation.query.service import QueryError, describe_warehouse, execute_query, promote_query, run_saved_query


def warehouse(path: Path) -> None:
    with duckdb.connect(str(path)) as connection:
        for schema in ("ingest", "clean", "quality", "semantic", "queries", "private"):
            connection.execute(f"CREATE SCHEMA {schema}")
        connection.execute("CREATE TABLE ingest.sources(source_id VARCHAR, snapshot_id VARCHAR)")
        connection.execute("INSERT INTO ingest.sources VALUES ('fixture', 'snapshot_query_test')")
        connection.execute("CREATE TABLE clean.values_table(category VARCHAR, amount INTEGER)")
        connection.execute("INSERT INTO clean.values_table VALUES ('a',1),('a',2),('b',3)")
        connection.execute("CREATE TABLE quality.issues(issue_code VARCHAR, source_id VARCHAR, sheet_name VARCHAR, source_row_number BIGINT)")
        connection.execute("INSERT INTO quality.issues VALUES ('TEST','fixture','Sheet1',1)")
        connection.execute("CREATE TABLE private.secret(value INTEGER)")
        connection.execute("INSERT INTO private.secret VALUES (7)")


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
            queries = [
                "SELECT * FROM clean.values_table ORDER BY category, amount",
                "WITH selected AS (SELECT * FROM clean.values_table) SELECT category, sum(amount) total FROM selected GROUP BY category ORDER BY category",
                "SELECT category, amount, row_number() OVER (PARTITION BY category ORDER BY amount) AS row_rank FROM clean.values_table",
                "SELECT a.category, a.amount, b.amount other FROM clean.values_table a JOIN clean.values_table b USING(category)",
            ]
            for sql in queries:
                with self.subTest(sql=sql):
                    result = execute_query(warehouse=db, snapshot_id="snapshot_query_test", sql=sql, run_id="run_query_test", output_root=root)
                    self.assertEqual(result["status"], "passed")

    def test_rejects_writes_external_access_and_multiple_statements(self):
        denied = [
            "CREATE TABLE clean.bad(a int)",
            "INSERT INTO clean.values_table VALUES ('x', 1)",
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
                self.assertEqual(connection.execute("SELECT count(*) FROM clean.values_table").fetchone()[0], 3)
            with self.assertRaises(QueryError) as invalid_run:
                execute_query(warehouse=db, snapshot_id="snapshot_query_test", sql="SELECT 1", run_id="../escape", output_root=root)
            self.assertEqual(invalid_run.exception.code, "RUN_ID_INVALID")

    def test_row_byte_and_artifact_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "warehouse.duckdb"
            warehouse(db)
            with self.assertRaises(QueryError) as row_error:
                execute_query(warehouse=db, snapshot_id="snapshot_query_test", sql="SELECT * FROM clean.values_table", run_id="run_query_test", output_root=root, max_rows=2)
            self.assertEqual(row_error.exception.code, "QUERY_LIMIT_EXCEEDED")
            with self.assertRaises(QueryError) as byte_error:
                execute_query(warehouse=db, snapshot_id="snapshot_query_test", sql="SELECT repeat('x', 1000)", run_id="run_query_test", output_root=root, max_result_bytes=100)
            self.assertEqual(byte_error.exception.code, "QUERY_LIMIT_EXCEEDED")
            result = execute_query(warehouse=db, snapshot_id="snapshot_query_test", sql="SELECT repeat('x', 1000)", run_id="run_query_test", output_root=root, inline_bytes=10)
            self.assertIsNone(result["result"])
            self.assertTrue((root / "run_query_test" / result["artifact"]["path"]).is_file())
            self.assertTrue((root / "run_query_test/artifact_manifest.jsonl").is_file())

    def test_removes_large_result_when_artifact_manifest_append_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "warehouse.duckdb"
            warehouse(db)
            artifact_manifest = root / "run_query_test" / "artifact_manifest.jsonl"
            original_open = Path.open

            def fail_manifest_append(path, *args, **kwargs):
                mode = args[0] if args else kwargs.get("mode", "r")
                if path == artifact_manifest and "a" in mode:
                    raise OSError("append failed")
                return original_open(path, *args, **kwargs)

            with mock.patch("pathlib.Path.open", autospec=True, side_effect=fail_manifest_append):
                with self.assertRaises(OSError):
                    execute_query(
                        warehouse=db,
                        snapshot_id="snapshot_query_test",
                        sql="SELECT repeat('x', 1000)",
                        run_id="run_query_test",
                        output_root=root,
                        inline_bytes=10,
                    )
            result_dir = root / "run_query_test" / "data" / "query_results"
            self.assertEqual(list(result_dir.glob("*.json")), [])

    def test_promote_requires_confirmation_is_versioned_and_parameterized(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "warehouse.duckdb"
            registry = root / "registry"
            warehouse(db)
            before = hashlib.sha256(db.read_bytes()).hexdigest()
            sql = "SELECT * FROM clean.values_table WHERE category = $category ORDER BY amount"
            with self.assertRaises(QueryError):
                promote_query(warehouse=db, snapshot_id="snapshot_query_test", sql=sql, registry_root=registry, query_id="category_values", version="v1", confirmed_by="")
            promoted = promote_query(warehouse=db, snapshot_id="snapshot_query_test", sql=sql, registry_root=registry, query_id="category_values", version="v1", confirmed_by="user@example")
            self.assertEqual(promoted["status"], "passed")
            self.assertTrue((registry / "category_values/v1/query.sql").is_file())
            with self.assertRaises(QueryError) as duplicate:
                promote_query(warehouse=db, snapshot_id="snapshot_query_test", sql=sql, registry_root=registry, query_id="category_values", version="v1", confirmed_by="user@example")
            self.assertEqual(duplicate.exception.code, "QUERY_VERSION_EXISTS")
            result = run_saved_query(warehouse=db, snapshot_id="snapshot_query_test", registry_root=registry, query_id="category_values", version="v1", parameters={"category": "a"}, run_id="run_query_test", output_root=root, max_rows=10, max_result_bytes=10000)
            self.assertEqual(result["row_count"], 2)
            self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(), before)
            manifest = json.loads((registry / "category_values/v1/manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["sha256"], hashlib.sha256((registry / "category_values/v1/query.sql").read_bytes()).hexdigest())

    def test_saved_query_rejects_a_different_current_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "warehouse.duckdb"
            registry = root / "registry"
            warehouse(db)
            promote_query(warehouse=db, snapshot_id="snapshot_query_test", sql="SELECT * FROM clean.values_table", registry_root=registry, query_id="snapshot_bound", version="v1", confirmed_by="user@example")
            with self.assertRaises(QueryError) as mismatch:
                run_saved_query(warehouse=db, snapshot_id="snapshot_other", registry_root=registry, query_id="snapshot_bound", version="v1", parameters=None, run_id="run_query_test", output_root=root, max_rows=10, max_result_bytes=10000)
            self.assertEqual(mismatch.exception.code, "SNAPSHOT_MISMATCH")

    def test_select_string_literal_with_denied_word_is_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "warehouse.duckdb"
            warehouse(db)
            result = execute_query(warehouse=db, snapshot_id="snapshot_query_test", sql="SELECT 'copy' AS word", run_id="run_query_test", output_root=root)
            self.assertEqual(result["result"]["rows"], [["copy"]])


if __name__ == "__main__":
    unittest.main()
