from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from analysis_product import s4_ppt_quick
from analysis_product.s4_ppt_preflight import validate_frozen_analysis


def write_json(path: Path, value: dict) -> str:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_frozen_inputs(root: Path) -> tuple[Path, Path, Path]:
    evidence_root = root / "evidence"
    evidence_root.mkdir(exist_ok=True)
    evidence_hash = write_json(evidence_root / "q10.json", {"snapshot_id": "snap_1", "referenced_source_ids": ["br_cash"], "result": {"cash": 10}})
    analysis = root / "analysis_frozen.json"
    write_json(
        analysis,
        {
            "schema_version": "s4_ppt_frozen_analysis.v1",
            "snapshot_id": "snap_1",
            "allowed_sources": ["br_cash"],
            "excluded_sources": ["frontdesk", "teaching"],
            "evidence": [{"path": "q10.json", "sha256": evidence_hash, "source_id": "br_cash"}],
            "key_queries": ["q10.json"],
        },
    )
    markdown = root / "analysis_frozen.md"
    markdown.write_text("# frozen analysis\n", encoding="utf-8")
    return analysis, markdown, evidence_root


def prepare(root: Path, name: str = "daily_cash") -> Path:
    analysis, markdown, evidence_root = make_frozen_inputs(root)
    args = type("Args", (), {
        "project": str(root / name), "analysis": str(analysis), "markdown": str(markdown),
        "evidence_root": str(evidence_root), "format": "ppt169",
    })()
    return Path(s4_ppt_quick.prepare(args)["project"])


class S4PptQuickTests(unittest.TestCase):
    def test_frozen_manifest_requires_identity_and_matching_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            analysis, _, evidence_root = make_frozen_inputs(root)
            checked = validate_frozen_analysis(analysis, evidence_root)
            self.assertEqual(checked["snapshot_id"], "snap_1")
            self.assertEqual(checked["evidence"][0]["source_id"], "br_cash")
            (evidence_root / "q10.json").write_text('{"snapshot_id":"snap_1","changed":true}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                validate_frozen_analysis(analysis, evidence_root)

    def test_frozen_manifest_rejects_legacy_policy_and_snapshot_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            analysis, _, evidence_root = make_frozen_inputs(root)
            value = json.loads(analysis.read_text(encoding="utf-8"))
            value["schema_version"] = "deepseek_main_bridge_analysis_frozen.v2"
            analysis.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsupported frozen analysis schema"):
                validate_frozen_analysis(analysis, evidence_root)
            value["schema_version"] = "s4_ppt_frozen_analysis.v1"
            value["evidence"][0]["source_id"] = "frontdesk"
            analysis.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not allowed"):
                validate_frozen_analysis(analysis, evidence_root)
            value["evidence"][0]["source_id"] = "br_cash"
            evidence_hash = write_json(evidence_root / "q10.json", {"snapshot_id": "another_snapshot", "referenced_source_ids": ["br_cash"]})
            value["evidence"][0]["sha256"] = evidence_hash
            analysis.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "snapshot mismatch"):
                validate_frozen_analysis(analysis, evidence_root)

    def test_prepare_uses_real_upstream_quick_init_and_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = prepare(Path(temp))
            self.assertTrue(project.is_dir())
            self.assertTrue((project / "svg_output").is_dir())
            self.assertTrue((project / "sources" / "quick_manifest.json").is_file())
            self.assertTrue((project / "validation" / "quick_run.json").is_file())
            self.assertFalse((project / "design_spec.md").exists())
            self.assertFalse((project / "notes").exists())
            self.assertFalse((project / "live_preview").exists())
            self.assertFalse((project / "svg_final").exists())
            self.assertEqual(s4_ppt_quick.validate_quick_project(project)["snapshot_id"], "snap_1")

    def test_prepare_keeps_same_name_same_hash_evidence_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            analysis, markdown, evidence_root = make_frozen_inputs(root)
            duplicate_dir = evidence_root / "duplicate"
            duplicate_dir.mkdir()
            duplicate_hash = write_json(duplicate_dir / "q10.json", {"snapshot_id": "snap_1", "referenced_source_ids": ["br_work_order"], "result": {"cash": 10}})
            value = json.loads(analysis.read_text(encoding="utf-8"))
            value["allowed_sources"].append("br_work_order")
            value["evidence"].append({"path": "duplicate/q10.json", "sha256": duplicate_hash, "source_id": "br_work_order"})
            value["key_queries"].append("duplicate/q10.json")
            analysis.write_text(json.dumps(value), encoding="utf-8")
            args = type("Args", (), {
                "project": str(root / "daily_cash"), "analysis": str(analysis), "markdown": str(markdown),
                "evidence_root": str(evidence_root), "format": "ppt169",
            })()
            manifest = s4_ppt_quick.validate_quick_project(Path(s4_ppt_quick.prepare(args)["project"]))
            self.assertEqual(len(manifest["evidence"]), 2)
            self.assertEqual(len({item["path"] for item in manifest["evidence"]}), 2)

    def test_frozen_manifest_rejects_unlisted_key_query(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            analysis, _, evidence_root = make_frozen_inputs(root)
            value = json.loads(analysis.read_text(encoding="utf-8"))
            value["key_queries"] = ["not_imported.json"]
            analysis.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "key_queries"):
                validate_frozen_analysis(analysis, evidence_root)

    def test_frozen_manifest_rejects_missing_or_forged_source_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            analysis, _, evidence_root = make_frozen_inputs(root)
            value = json.loads(analysis.read_text(encoding="utf-8"))
            evidence_hash = write_json(evidence_root / "q10.json", {"snapshot_id": "snap_1", "result": {}})
            value["evidence"][0]["sha256"] = evidence_hash
            analysis.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "provenance missing"):
                validate_frozen_analysis(analysis, evidence_root)
            evidence_hash = write_json(evidence_root / "q10.json", {"snapshot_id": "snap_1", "referenced_source_ids": ["fy27_frontdesk_daily"], "result": {}})
            value["evidence"][0]["sha256"] = evidence_hash
            analysis.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not include declared source"):
                validate_frozen_analysis(analysis, evidence_root)

    def test_quick_project_validation_rejects_tampered_or_unapproved_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = prepare(root)
            (project / "sources" / "q10.json").write_text('{"snapshot_id":"snap_1","changed":true}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "changed or missing"):
                s4_ppt_quick.validate_quick_project(project)
            project = prepare(root, "daily_cash_2")
            (project / "sources" / "unapproved.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unapproved sources"):
                s4_ppt_quick.validate_quick_project(project)
            (project / "sources" / "quick_manifest.json").unlink()
            with self.assertRaisesRegex(ValueError, "missing sources/quick_manifest"):
                s4_ppt_quick.validate_quick_project(project)

    def test_finalize_rejects_default_artifacts_before_running_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "svg_output").mkdir()
            (project / "design_spec.md").write_text("default", encoding="utf-8")
            args = type("Args", (), {"project": str(project), "output": None})()
            with self.assertRaisesRegex(ValueError, "Default artifacts"):
                s4_ppt_quick.finalize(args)

    def test_quick_svg_policy_rejects_images_remote_resources_and_motion(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = prepare(Path(temp))
            svg = project / "svg_output" / "01_cover.svg"
            svg.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.test/image.png"/><animate attributeName="x"/></svg>',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "local static policy"):
                s4_ppt_quick.validate_quick_svg_assets(project)

    def test_finalize_stops_after_one_blocking_final_checker_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = prepare(Path(temp))
            calls: list[list[str]] = []

            def fail_checker(command: list[str], cwd: Path | None = None) -> dict[str, object]:
                calls.append(command)
                raise s4_ppt_quick.CommandError({"command": command, "exit_code": 1, "elapsed_ms": 1}, "blocking SVG error")

            with patch.object(s4_ppt_quick, "run_guard_preflight", return_value=[]), patch.object(s4_ppt_quick, "run", side_effect=fail_checker):
                with self.assertRaisesRegex(s4_ppt_quick.CommandError, "blocking SVG error"):
                    s4_ppt_quick.finalize(type("Args", (), {"project": str(project), "output": None})())
            self.assertEqual(len(calls), 1)
            self.assertIn("svg_quality_checker.py", calls[0][1])
            record = json.loads((project / "validation" / "quick_run.json").read_text(encoding="utf-8"))
            self.assertEqual(record["finalize"]["commands"][-1]["exit_code"], 1)

    def test_finalize_does_not_repeat_prepare_guards(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = prepare(Path(temp))
            (project / "svg_output" / "01_cover.svg").write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"/>',
                encoding="utf-8",
            )
            commands: list[list[str]] = []

            def record(command: list[str], cwd: Path | None = None) -> dict[str, object]:
                commands.append(command)
                return {"command": command, "exit_code": 0, "elapsed_ms": 1}

            with patch.object(s4_ppt_quick, "run_guard_preflight", side_effect=AssertionError("finalize must not repeat guards")), patch.object(s4_ppt_quick, "run", side_effect=record):
                result = s4_ppt_quick.finalize(type("Args", (), {"project": str(project), "output": None})())
            self.assertEqual(result["status"], "exported")
            self.assertEqual(len(commands), 2)
            self.assertIn("svg_quality_checker.py", commands[0][1])
            self.assertIn("svg_to_pptx.py", commands[1][1])


if __name__ == "__main__":
    unittest.main()
