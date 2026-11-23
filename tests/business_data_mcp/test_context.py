from __future__ import annotations

import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from business_data_mcp.build_context import build, build_bundle
from business_data_mcp.context import describe_business_context, read_business_context, read_release_business_context
from business_data_mcp.query import BusinessDataMCPError


class BusinessContextTests(unittest.TestCase):
    def test_discovery_and_confirmed_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bridge.json").write_text(json.dumps({
                "schema_version": "company_bridge.v1", "bridge_version": "1",
                "field_mappings": [{"status": "confirmed", "field_name": "现金"},
                                   {"status": "proposed", "field_name": "猜测"}],
                "unresolved": [{"status": "unresolved"}],
            }), encoding="utf-8")
            (root / "dashboard.md").write_text("人头口径", encoding="utf-8")
            (root / "study_scorecard.md").write_text("覆盖 FY27；来源差异保留", encoding="utf-8")
            ids = {source["source_id"] for source in describe_business_context()["sources"]}
            self.assertEqual(ids, {"bridge", "dashboard", "study_scorecard"})
            bridge = read_business_context(root, "bridge")["content"]
            self.assertEqual([x["field_name"] for x in bridge["field_mappings"]], ["现金"])
            self.assertNotIn("unresolved", bridge)
            self.assertEqual(read_business_context(root, "dashboard")["content"], "人头口径")
            self.assertIn("FY27", read_business_context(root, "study_scorecard")["content"])

    def test_real_approved_sources_preserve_metric_scope(self):
        project = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = {
                "bridge.json": "customers/shadow_bi_daily/Work/Bridge/reference.json",
                "dashboard.md": "dashboard_product/management/README.md",
                "study_scorecard.md": "customers/shadow_bi_daily/Input/Reference/留学板块-官方记分卡.md",
            }
            for target, source in files.items():
                (root / target).write_text((project / source).read_text(encoding="utf-8"), encoding="utf-8")
            bridge = read_business_context(root, "bridge")["content"]
            self.assertEqual(bridge["bridge_id"], "bridge_bi_operations")
            self.assertTrue(all(item["status"] == "confirmed" for item in bridge["field_mappings"]))
            dashboard = read_business_context(root, "dashboard")["content"]
            self.assertIn("学员编号＋班级编码", dashboard)
            scorecard = read_business_context(root, "study_scorecard")["content"]
            self.assertIn("财年日历边界源表未写明", scorecard)
            self.assertIn("2,679", scorecard)

    def test_bundle_builds_selected_current_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build(root)
            dashboard = read_business_context(root, "dashboard")
            self.assertIn("默认包含全部新老生", dashboard["content"])
            self.assertIn("费用共同覆盖窗口", dashboard["content"])
            self.assertIn("个人工单", dashboard["content"])
            self.assertTrue(dashboard["bundle"]["bridge_version"])
            scorecard = read_business_context(root, "study_scorecard")["content"]
            self.assertNotIn("customers/shadow_bi_daily", scorecard)
            self.assertNotIn("dashboard_product/", scorecard)
            bridge = read_business_context(root, "bridge")["content"]
            original = json.loads((Path(__file__).resolve().parents[2] / "customers/shadow_bi_daily/Work/Bridge/reference.json").read_text())
            for key in ("source_contracts", "field_mappings", "normalization_rules", "overrides"):
                self.assertEqual(len(bridge[key]), sum(item["status"] == "confirmed" for item in original[key]))

    def test_bundle_uses_supplied_workspace(self):
        project = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "Work/Bridge").mkdir(parents=True)
            (workspace / "Input/Reference").mkdir(parents=True)
            bridge = {"schema_version": "company_bridge.v1", "bridge_version": "workspace-version", "field_mappings": [
                {"status": "confirmed", "field_name": "业务字段"}, {"field_name": "未确认字段"}]}
            raw = json.dumps(bridge, ensure_ascii=False)
            (workspace / "Work/Bridge/reference.json").write_text(raw, encoding="utf-8")
            (workspace / "Input/Reference/留学板块-官方记分卡.md").write_text("指定工作区记分卡", encoding="utf-8")
            bundle = build_bundle(project=project, workspace=workspace)
            self.assertEqual(bundle["manifest"]["source_sha256"]["bridge"], hashlib.sha256(raw.encode()).hexdigest())
            self.assertEqual(bundle["study_scorecard"], "指定工作区记分卡")
            self.assertEqual(len(bundle["bridge"]["field_mappings"]), 1)

    def test_release_context_and_legacy_identity(self):
        from data_platform.sql_release_query import SqlWarehouseRelease
        bundle = build_bundle()
        expected = bundle["manifest"]["source_sha256"]["bridge"]
        release = object.__new__(SqlWarehouseRelease)
        object.__setattr__(release, "release", "daily-test")
        manifest = {"semantics": {"Work/Bridge/reference.json": expected}, "business_context": bundle}
        object.__setattr__(release, "manifest", manifest)
        with tempfile.TemporaryDirectory() as tmp, patch("business_data_mcp.query.resolve_current", return_value=release):
            root = Path(tmp)
            # Embedded context takes precedence even without a local bundle.
            result = read_release_business_context(Path("current"), None, "bridge")
            self.assertEqual(result["release"], "daily-test")
            self.assertNotIn("candidate_id", json.dumps(result["content"]))
            self.assertNotIn("customers/", json.dumps(result["content"]))
            build(root)
            del manifest["business_context"]
            self.assertIn("学员编号和班级编码", read_release_business_context(Path("current"), root, "dashboard")["content"])
            manifest["semantics"]["Work/Bridge/reference.json"] = "different"
            with self.assertRaises(BusinessDataMCPError) as mismatch:
                read_release_business_context(Path("current"), root, "dashboard")
            self.assertEqual(mismatch.exception.code, "CONTEXT_UNAVAILABLE")
            manifest["business_context"] = bundle
            with self.assertRaises(BusinessDataMCPError):
                read_release_business_context(Path("current"), root, "bridge")

    def test_missing_and_unknown_do_not_fallback(self):
        with self.assertRaises(BusinessDataMCPError) as missing:
            read_business_context(None, "bridge")
        self.assertEqual(missing.exception.code, "CONTEXT_UNAVAILABLE")
        with self.assertRaises(BusinessDataMCPError) as unknown:
            read_business_context(Path("/"), "../../etc/passwd")
        self.assertEqual(unknown.exception.code, "CONTEXT_NOT_FOUND")
