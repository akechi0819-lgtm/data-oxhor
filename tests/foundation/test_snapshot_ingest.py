from __future__ import annotations

import hashlib
import json
import unittest.mock
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import duckdb
from openpyxl import Workbook

from interfaces.data_foundation import ingest_sources


SOURCE_SHEETS = {
    "fy25_frontdesk_daily": ["FY25-汇总"],
    "fy27_frontdesk_daily": ["FY27-汇总", "看板"],
    "current_work_orders": ["工单分析", "新表区域"],
    "archived_work_orders": ["FY24", "FY25", "FY26"],
}


def write_source(path: Path, source_id: str) -> None:
    workbook = Workbook()
    workbook.remove(workbook.active)
    for sheet_name in SOURCE_SHEETS[source_id]:
        sheet = workbook.create_sheet(sheet_name)
        if "frontdesk" in source_id and "汇总" in sheet_name:
            sheet.append(["业务日期", "实缴金额", "业务形式", "备注", None])
            sheet.append([45292, "1,200.10元", " 报班 ", " Ａ ", "空表头列值"])
            sheet.append(["bad-date", "bad-money", "报班-预收", None])
            sheet.append([None, None, None, None])
        else:
            date_field = "分配日期" if sheet_name == "FY25" else "分配时间"
            sheet.append(["工单ID", date_field])
            sheet.append([f"{source_id}-{sheet_name}", 45292])
    workbook.save(path)


def fixture(root: Path) -> tuple[Path, list[str]]:
    sources = {}
    bindings = []
    for source_id in SOURCE_SHEETS:
        path = root / f"{source_id}.xlsx"
        write_source(path, source_id)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        sources[source_id] = {"filename": path.name, "sha256": digest}
        bindings.append(f"{source_id}={path}")
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps({"sources": sources, "cases": [{"metric": {"included_business_forms": ["报班", "报班-预收"], "excluded_examples": []}}]}), encoding="utf-8")
    return manifest, bindings


class SnapshotIngestTests(unittest.TestCase):
    def test_snapshot_is_complete_traceable_and_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, bindings = fixture(root)
            output = root / "runs"
            result = ingest_sources(run_id="run_snapshot_test", snapshot_id="snapshot_test_001", output_root=output, manifest_path=manifest, source_values=bindings)
            snapshot = output / "run_snapshot_test/data/snapshots/snapshot_test_001"

            self.assertEqual(result["status"], "passed")
            self.assertTrue((snapshot / "warehouse.duckdb").is_file())
            self.assertEqual(len(list((snapshot / "source_workbooks").rglob("*.xlsx"))), 4)
            self.assertFalse((snapshot / "raw_structure").exists())
            self.assertFalse((snapshot / "_work").exists())
            self.assertEqual(len(list((snapshot / "landing").glob("*.parquet"))), 8)
            document = json.loads((snapshot / "snapshot_manifest.json").read_text(encoding="utf-8"))
            self.assertNotIn(str(root), json.dumps(document))
            fy25 = next(sheet for source in document["sources"] if source["source_id"] == "fy25_frontdesk_daily" for sheet in source["sheets"] if sheet["name"] == "FY25-汇总")
            self.assertEqual((fy25["physical_node_rows"], fy25["meaningful_rows"], fy25["max_source_row"], fy25["landing_rows"]), (4, 3, 4, 3))

            with duckdb.connect(str(snapshot / "warehouse.duckdb"), read_only=True) as connection:
                schemas = {row[0] for row in connection.execute("SELECT schema_name FROM information_schema.schemata").fetchall()}
                self.assertTrue({"ingest", "landing", "quality", "queries"}.issubset(schemas))
                self.assertNotIn("semantic", schemas)
                self.assertNotIn("clean", schemas)
                tables = dict(connection.execute("SELECT source_id || '/' || sheet_name, target_table FROM ingest.sheets").fetchall())
                fy25_table = tables["fy25_frontdesk_daily/FY25-汇总"]
                fy27_table = tables["fy27_frontdesk_daily/FY27-汇总"]
                totals = connection.execute('''
                    SELECT fiscal_year, sum(amount) FROM (
                        SELECT 'FY25' fiscal_year, TRY_CAST(regexp_replace(column_2, '[,￥¥元[:space:]]', '', 'g') AS DECIMAL(38, 6)) amount FROM landing."''' + fy25_table + '''" WHERE source_row_number > 1 AND trim(column_3) IN ('报班', '报班-预收')
                        UNION ALL
                        SELECT 'FY27' fiscal_year, TRY_CAST(regexp_replace(column_2, '[,￥¥元[:space:]]', '', 'g') AS DECIMAL(38, 6)) amount FROM landing."''' + fy27_table + '''" WHERE source_row_number > 1 AND trim(column_3) IN ('报班', '报班-预收')
                    ) GROUP BY fiscal_year ORDER BY fiscal_year
                ''').fetchall()
                self.assertEqual(totals, [("FY25", Decimal("1200.100000")), ("FY27", Decimal("1200.100000"))])
                landing_types = dict(connection.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='landing' AND table_name=?", [fy25_table]).fetchall())
                self.assertEqual(landing_types["column_1"], "VARCHAR")
                self.assertEqual(landing_types["column_2"], "VARCHAR")
                self.assertEqual(landing_types["column_5"], "VARCHAR")
                self.assertEqual(connection.execute(f'SELECT column_5 FROM landing."{fy25_table}" WHERE source_row_number=2').fetchone()[0], "空表头列值")
                preserved = connection.execute(
                    f'SELECT column_3, column_4 FROM landing."{fy25_table}" WHERE source_row_number=2'
                ).fetchone()
                self.assertEqual(preserved, (" 报班 ", " Ａ "))

            second = ingest_sources(run_id="run_snapshot_test", snapshot_id="snapshot_test_001", output_root=output, manifest_path=manifest, source_values=bindings)
            self.assertEqual(second["status"], "failed")
            self.assertEqual(second["errors"][0]["code"], "SNAPSHOT_EXISTS")
            artifact_lines = (output / "run_snapshot_test/artifact_manifest.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertTrue(artifact_lines)
            self.assertTrue(all(str(root) not in line for line in artifact_lines))

    def test_failed_publish_leaves_no_snapshot_or_temporary_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, bindings = fixture(root)
            document = json.loads(manifest.read_text(encoding="utf-8"))
            document["sources"]["fy25_frontdesk_daily"]["sha256"] = "0" * 64
            manifest.write_text(json.dumps(document), encoding="utf-8")
            output = root / "runs"
            result = ingest_sources(run_id="run_snapshot_fail", snapshot_id="snapshot_test_fail", output_root=output, manifest_path=manifest, source_values=bindings)

            snapshots = output / "run_snapshot_fail/data/snapshots"
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["errors"][0]["code"], "HASH_MISMATCH")
            self.assertFalse((snapshots / "snapshot_test_fail").exists())
            self.assertEqual(list(snapshots.glob(".*.tmp-*")), [])

    def test_artifact_manifest_failure_removes_published_snapshot_and_rolls_back_append(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, bindings = fixture(root)
            output = root / "runs"
            artifact_manifest = output / "run_snapshot_artifact_fail/artifact_manifest.jsonl"
            artifact_manifest.parent.mkdir(parents=True)
            artifact_manifest.write_text('{"prior":true}\n', encoding="utf-8")
            original = artifact_manifest.read_bytes()
            original_open = Path.open
            with unittest.mock.patch("pathlib.Path.open", autospec=True) as open_path:
                def fail_append(path, *args, **kwargs):
                    mode = args[0] if args else kwargs.get("mode", "r")
                    if path == artifact_manifest and "a" in mode:
                        raise OSError("append failed")
                    return original_open(path, *args, **kwargs)
                open_path.side_effect = fail_append
                result = ingest_sources(run_id="run_snapshot_artifact_fail", snapshot_id="snapshot_artifact_fail", output_root=output, manifest_path=manifest, source_values=bindings)
            self.assertEqual(result["status"], "failed")
            self.assertFalse((output / "run_snapshot_artifact_fail/data/snapshots/snapshot_artifact_fail").exists())
            self.assertEqual(artifact_manifest.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
