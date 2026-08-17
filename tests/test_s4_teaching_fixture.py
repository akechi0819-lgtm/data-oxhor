from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import duckdb

from interfaces.data_foundation import ingest_sources, inspect_sources
from tests.fixtures.s4_teaching_fixture import build_s4_teaching_fixture


class S4TeachingFixtureTests(unittest.TestCase):
    def test_fixture_is_reproducible_and_lands_without_business_templates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, bindings = build_s4_teaching_fixture(root)
            inspected = inspect_sources(
                run_id="run_s4_fixture_inspect",
                manifest_path=manifest,
                source_values=bindings,
            )
            self.assertEqual(inspected["schema_version"], "data_foundation_inspection.v2")
            self.assertEqual(
                {source["source_id"] for source in inspected["sources"]},
                {"schedule_main", "schedule_study_abroad", "teacher_priority"},
            )

            output = root / "runs"
            result = ingest_sources(
                run_id="run_s4_fixture_ingest",
                snapshot_id="snapshot_s4_fixture",
                output_root=output,
                manifest_path=manifest,
                source_values=bindings,
            )
            self.assertEqual(result["status"], "passed")
            snapshot = output / "run_s4_fixture_ingest/data/snapshots/snapshot_s4_fixture"
            self.assertTrue((snapshot / "warehouse.duckdb").is_file())
            self.assertEqual(json.loads((snapshot / "snapshot_manifest.json").read_text())["snapshot_id"], "snapshot_s4_fixture")

            with duckdb.connect(str(snapshot / "warehouse.duckdb"), read_only=True) as connection:
                tables = dict(connection.execute("SELECT sheet_name, target_table FROM ingest.sheets").fetchall())
                schedule_table = tables["排课记录"]
                study_abroad_table = tables["留学预备排课"]
                rows = connection.execute(
                    f'SELECT column_1, column_2, column_5 FROM landing."{schedule_table}" WHERE source_row_number >= 4 ORDER BY source_row_number'
                ).fetchall()
                self.assertEqual(rows, [("R001", "教师甲", "2"), ("R002", "教师乙", "1.5"), ("R003", "教师甲", "2")])
                study_abroad_rows = connection.execute(
                    f'SELECT column_1, column_2, column_5 FROM landing."{study_abroad_table}" WHERE source_row_number >= 4 ORDER BY source_row_number'
                ).fetchall()
                self.assertEqual(study_abroad_rows, [("A001", "教师丙", "2"), ("A002", "教师甲", "1.5")])
                self.assertNotIn("semantic", {row[0] for row in connection.execute("SELECT schema_name FROM information_schema.schemata").fetchall()})


if __name__ == "__main__":
    unittest.main()
