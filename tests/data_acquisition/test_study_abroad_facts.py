"""Synthetic controlled-query tests for isolated study-abroad management facts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from data_acquisition.jobs.work_order_cleaning import WorkOrderReference
from dashboard_product.management.study_abroad_facts import load_study_abroad_facts


COMPANY_ID = "company_study_facts_test"
SNAPSHOT_ID = "snapshot_study_facts_test_20261008"
RUN_ID = "run_study_facts_test_20261008"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_workspace(root: Path) -> dict[str, Path | bytes]:
    root = root.resolve()
    workspace_config = root / "Work/workspace.json"
    workspace_config.parent.mkdir(parents=True)
    workspace_config_bytes = json.dumps({"company_id": COMPANY_ID}, ensure_ascii=False).encode("utf-8")
    workspace_config.write_bytes(workspace_config_bytes)

    run_root = root / "Work/StudyAbroad/Runs/source-run"
    input_root = run_root / "input"
    input_root.mkdir(parents=True)
    raw_source = input_root / "original.xlsx"
    prepared_source = input_root / "study_abroad_market.xlsx"
    people_roster = input_root / "people.json"
    abroad_roster = input_root / "abroad_people.json"
    raw_source.write_bytes(b"synthetic original workbook")
    prepared_source.write_bytes(b"synthetic normalized workbook")
    people_roster.write_text("{}", encoding="utf-8")
    abroad_roster.write_text("{}", encoding="utf-8")

    repository_root = Path(__file__).resolve().parents[2]
    normalizer = repository_root / "data_acquisition/jobs/build_study_abroad_warehouse.py"
    reader = repository_root / "workspace_modeling/operations/study_abroad_source.py"
    lineage = {
        "schema_version": "study_abroad_warehouse.v1",
        "company_id": COMPANY_ID,
        "run_id": "source-run",
        "snapshot_id": SNAPSHOT_ID,
        "through_date": "2026-09-30",
        "source_hashes": {
            "source": _sha(raw_source),
            "people": _sha(people_roster),
            "abroad_people": _sha(abroad_roster),
            "normalizer": _sha(normalizer),
            "reader": _sha(reader),
        },
        "origin_file": "input/original.xlsx",
        "prepared_file": "input/study_abroad_market.xlsx",
        "roster_files": {"people": "input/people.json", "abroad_people": "input/abroad_people.json"},
    }
    lineage_path = run_root / "source_lineage.json"
    lineage_path.write_text(json.dumps(lineage, ensure_ascii=False), encoding="utf-8")

    snapshot_root = run_root / "data/snapshots" / SNAPSHOT_ID
    snapshot_root.mkdir(parents=True)
    warehouse = snapshot_root / "warehouse.duckdb"
    warehouse.touch()
    manifest = {
        "schema_version": "warehouse_snapshot.v2",
        "run_id": "source-run",
        "snapshot_id": SNAPSHOT_ID,
        "sources": [{
            "source_id": "study_abroad_market",
            "filename": prepared_source.name,
            "sha256": _sha(prepared_source),
            "sheets": [],
        }],
        "artifacts": [],
    }
    snapshot_manifest = snapshot_root / "snapshot_manifest.json"
    snapshot_manifest.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    pointer = {
        "schema_version": "study_abroad_warehouse.v1",
        "company_id": COMPANY_ID,
        "run_id": "source-run",
        "snapshot_id": SNAPSHOT_ID,
        "through_date": "2026-09-30",
        "source_sha256": _sha(raw_source),
        "warehouse": warehouse.relative_to(root).as_posix(),
        "source_lineage": lineage_path.relative_to(root).as_posix(),
        "used_snapshot_ids": [SNAPSHOT_ID],
    }
    pointer_path = root / "Work/StudyAbroad/current.json"
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    pointer_path.write_text(json.dumps(pointer, ensure_ascii=False), encoding="utf-8")
    pointer_bytes = pointer_path.read_bytes()

    bridge_path = root / "Work/Bridge/reference.json"
    bridge_path.parent.mkdir(parents=True)
    bridge_path.write_text(json.dumps(_bridge(), ensure_ascii=False), encoding="utf-8")
    reference_path = root / "Input/Reference/留学-FY26-资源表.xlsx"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_bytes(b"synthetic channel reference")
    decisions_path = root / "config/study_abroad_channel_decisions.json"
    decisions_path.parent.mkdir(parents=True)
    decisions_path.write_text("{}", encoding="utf-8")
    return {
        "workspace": root,
        "workspace_config": workspace_config,
        "workspace_config_bytes": workspace_config_bytes,
        "pointer": pointer_path,
        "pointer_bytes": pointer_bytes,
        "lineage": lineage_path,
        "raw_source": raw_source,
        "prepared_source": prepared_source,
        "people_roster": people_roster,
        "abroad_roster": abroad_roster,
        "bridge": bridge_path,
        "reference": reference_path,
        "decisions": decisions_path,
        "snapshot_manifest": snapshot_manifest,
    }


def _bridge():
    rules = {
        "online_root_alias": {"rule": "online_root_alias", "source_values": ["线上运营", "网络"], "normalized_l1": "网络资源"},
        "newmedia_other_ssc": {"rule": "newmedia_other_ssc", "source_value": "新媒体-其他", "l1": "新媒体", "l2": "SSC"},
        "newdongfang_l2_department": {"rule": "newdongfang_l2_department", "known_departments": ["大客服", "大学事业部", "国外考试部"]},
        "channel_partnership_l2": {"rule": "channel_partnership_l2", "maps": {"分公司个人代理": "个人渠道", "分公司对公合作": "对公渠道（三方）", "留学监理网": "对公渠道（三方）", "异业合作": "其他"}},
        "campaign_personal_agent_cross": {"rule": "campaign_personal_agent_cross", "source_path": "市场活动-高校", "source_value": "个人代理", "l1": "渠道合作", "l2": "个人渠道"},
        "campaign_l2_overlay": {"rule": "campaign_l2_overlay", "direct": {"高校活动": "高校活动", "中学活动": "中学活动", "地推": "地推", "市场活动": "高校活动"}, "collapse_to_综合展": ["信息收集", "条线专展", "部门展", "F活动邀约"]},
        "offline_other_roots_not_in_dashboard": {"rule": "offline_other_roots_not_in_dashboard", "maps": {"校代": {"l1": "其他", "l2": "线下校代"}, "合作": {"l1": "其他", "l2": "大学事业部合作"}}},
    }
    return {
        "schema_version": "company_bridge.v1",
        "bridge_id": "bridge_study_facts_test",
        "bridge_version": "1.7.0",
        "company_id": COMPANY_ID,
        "normalization_rules": [
            {"target_id": "acquisition.channel", "status": "confirmed", "parameters": value}
            for value in rules.values()
        ],
        "overrides": [],
    }


def _decisions():
    return {
        "company_id": COMPANY_ID,
        "candidates": [{
            "candidate_type": "override",
            "status": "confirmed",
            "proposed_mapping_or_rule": {
                "key": "unresolved_market_activity_by_work_order_grade",
                "value": {
                    "normalized_l1": "市场活动",
                    "maps": {"高校活动": "高校活动", "中学活动": "中学活动"},
                },
            },
        }],
    }


def _fact_row(*, fact_type, fact_id, business_line, event_date, segment_id,
              resource_id, owner, first_channel="网络资源", second_channel="店铺类",
              third_channel="美团点评", source_sha256, **extra):
    row = {
        "fact_type": fact_type, "fact_id": fact_id, "business_line": business_line,
        "event_date": event_date, "owner": owner, "source_owner": owner,
        "source_group": "", "market_group": "", "segment_id": segment_id,
        "team_eligible": segment_id in {"study_abroad_online", "study_abroad_offline"},
        "market_eligible": True, "personal_eligible": True,
        "roster_group": "大学", "roster_status": "active",
        "resource_id": resource_id, "contract_id": None, "customer_key": None,
        "gross_amount": None, "resource_status": "正常", "contract_status": None,
        "country": "日本", "stage": "意向本科", "first_channel": first_channel,
        "second_channel": second_channel, "third_channel": third_channel,
        "channel_source": "synthetic", "campaign": "合成活动",
        "origin_sha256": source_sha256, "origin_filename": "original.xlsx",
        "origin_sheet": "资源" if fact_type == "resource" else "留学签约",
        "origin_row_number": 2, "resource_count": 1 if fact_type == "resource" else 0,
        "personal_resource_count": 1 if fact_type == "resource" else 0,
        "gross_signing_amount": 0, "positive_signature": False,
    }
    row.update(extra)
    return row


class StudyAbroadFactsTests(unittest.TestCase):
    def test_independent_source_facts_keep_supplemental_amounts_and_grade_channels(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = _make_workspace(Path(directory))
            source_sha = json.loads(paths["lineage"].read_text(encoding="utf-8"))["source_hashes"]["source"]
            rows = [
                _fact_row(
                    fact_type="resource", fact_id="resources:online-1", business_line="study_abroad",
                    event_date="2026-06-03", segment_id="study_abroad_online", resource_id="online-1",
                    owner="线上甲", source_sha256=source_sha,
                ),
                _fact_row(
                    fact_type="resource", fact_id="resources:market-1", business_line="study_abroad",
                    event_date="2026-06-28", segment_id="study_abroad_offline", resource_id="197265843",
                    owner="线下甲", first_channel="市场活动", second_channel="会销/讲座",
                    third_channel="会销/讲座", source_sha256=source_sha, resource_status="删除",
                ),
                _fact_row(
                    fact_type="resource", fact_id="resources:market-online", business_line="study_abroad",
                    event_date="2026-06-29", segment_id="study_abroad_online", resource_id="2001",
                    owner="线上乙", first_channel="市场活动", second_channel="会销/讲座",
                    third_channel="会销/讲座", source_sha256=source_sha,
                ),
                _fact_row(
                    fact_type="resource", fact_id="resources:ssc", business_line="study_abroad",
                    event_date="2026-07-01", segment_id="ssc", resource_id="ssc-1", owner="SSC甲",
                    first_channel="新媒体", second_channel="其他", third_channel="其他",
                    source_sha256=source_sha,
                ),
                _fact_row(
                    fact_type="resource", fact_id="resources:international", business_line="study_abroad",
                    event_date="2026-07-02", segment_id="international_market", resource_id="intl-1",
                    owner="国际甲", first_channel="官方合作高校", second_channel="官方合作高校",
                    third_channel="推广", source_sha256=source_sha,
                ),
                _fact_row(
                    fact_type="signature", fact_id="contracts:positive", business_line="study_abroad",
                    event_date="2026-07-03", segment_id="study_abroad_offline", resource_id="197265843",
                    owner="线下甲", first_channel="市场活动", second_channel="高校", third_channel="高校活动",
                    source_sha256=source_sha, contract_id="C-1", customer_key="study_abroad:U-1",
                    gross_signing_amount="150.00", gross_amount="150.00", positive_signature=True,
                    contract_status="删除", origin_sheet="留学签约", origin_row_number=3,
                ),
                _fact_row(
                    fact_type="signature", fact_id="languages:sha:4", business_line="small_language",
                    event_date="2026-07-04", segment_id="study_abroad_online", resource_id="lang-1",
                    owner="线上乙", source_sha256=source_sha, contract_id=None,
                    customer_key="small_language:S-1", gross_signing_amount="80.50",
                    gross_amount="80.50", positive_signature=True, origin_sheet="小语种签约",
                    origin_row_number=4,
                ),
                _fact_row(
                    fact_type="signature", fact_id="contracts:negative", business_line="study_abroad",
                    event_date="2026-07-05", segment_id="unassigned", resource_id="unknown-1",
                    owner="未映射", first_channel="搜索推广", second_channel="百度搜索",
                    third_channel="百度搜索-PC", source_sha256=source_sha, contract_id="C-2",
                    customer_key="study_abroad:U-2", gross_signing_amount="0.00",
                    gross_amount="-20.00", positive_signature=False, contract_status="正常",
                    origin_row_number=5,
                ),
                _fact_row(
                    fact_type="signature", fact_id="contracts:unmapped", business_line="study_abroad",
                    event_date="2026-08-01", segment_id="unassigned", resource_id="unknown-2",
                    owner="未映射", first_channel="新渠道", second_channel="新来源",
                    third_channel="新信号", source_sha256=source_sha, contract_id="C-3",
                    customer_key="study_abroad:U-3", gross_signing_amount="25.00",
                    gross_amount="25.00", positive_signature=True, origin_row_number=6,
                ),
            ]
            query_data = {"columns": list(rows[0]), "rows": [[row.get(k) for k in rows[0]] for row in rows]}
            snapshot_manifest_bytes = (paths["snapshot_manifest"]).read_bytes()
            response = {
                "schema_version": "controlled_query_result.v2", "status": "passed",
                "run_id": RUN_ID, "snapshot_id": SNAPSHOT_ID,
                "receipt": {"evidence_id": "evidence_source_facts"},
            }
            receipt = {
                "run_id": RUN_ID, "snapshot_id": SNAPSHOT_ID,
                "referenced_source_ids": ["study_abroad_market"],
                "referenced_relations": [
                    "landing.study_abroad_market__contracts",
                    "landing.study_abroad_market__languages",
                    "landing.study_abroad_market__resources",
                ],
                "snapshot_ref": {"manifest_sha256": hashlib.sha256(snapshot_manifest_bytes).hexdigest()},
            }
            grade_response = {
                "schema_version": "controlled_query_result.v2", "status": "passed",
                "run_id": RUN_ID, "snapshot_id": "snapshot_bi_grade_test",
            }
            grade_resolution = {
                "197265843": {"status": "resolved", "second_channel": "中学活动", "work_order_ids": ["W-1"]},
                "2001": {"status": "resolved", "second_channel": "高校活动", "work_order_ids": ["W-2"]},
            }
            reference = WorkOrderReference(
                {}, {("网络资源-店铺类", "美团点评"): "大众"},
                {"日本": "亚洲条线"}, {}, {},
            )
            grade_calls = {}

            def grade_lookup(**kwargs):
                grade_calls.update(kwargs)
                return {
                    "resolution": grade_resolution,
                    "query_response": grade_response,
                    "bi_snapshot_id": grade_response["snapshot_id"],
                    "bi_workspace_sha256": _sha(paths["workspace_config"]),
                }

            with (
                patch("dashboard_product.management.study_abroad_facts.DECISIONS_PATH", paths["decisions"]),
                patch("dashboard_product.management.study_abroad_facts.load_decisions", return_value=_decisions()),
                patch("dashboard_product.management.study_abroad_facts.load_work_order_reference", return_value=reference),
                patch("dashboard_product.management.study_abroad_facts.query_sample", return_value=response) as query,
                patch("dashboard_product.management.study_abroad_facts.read_query_result", return_value=query_data),
                patch("dashboard_product.management.study_abroad_facts.resolve_file", return_value=Path(directory) / "receipt.json"),
                patch("dashboard_product.management.study_abroad_facts.verify_receipt", return_value=(receipt, query_data)),
                patch("dashboard_product.management.study_abroad_facts.load_grade_evidence", side_effect=grade_lookup),
            ):
                result = load_study_abroad_facts(
                    workspace=paths["workspace"], snapshot_id=SNAPSHOT_ID,
                    run_id=RUN_ID, as_of_date="2026-10-01",
                )

            query.assert_called_once_with(
                workspace=paths["workspace"], snapshot_id=SNAPSHOT_ID, run_id=RUN_ID,
                start_date="2026-06-01", end_date="2026-10-01", query_name="facts",
            )
            self.assertEqual(grade_calls["resource_ids"], ["197265843", "2001"])
            self.assertEqual(grade_calls["run_id"], RUN_ID)
            self.assertEqual(grade_calls["expected_company_id"], COMPANY_ID)
            self.assertEqual(len(result["query_receipts"]), 2)
            self.assertEqual(result["coverage"], {
                "snapshot_id": SNAPSHOT_ID,
                "source_sha256": source_sha,
                "start_date": "2026-06-01",
                "through_date": "2026-09-30",
                "no_yoy": True,
                "cross_system_customers": "not_aligned",
            })
            facts = {fact["fact_id"]: fact for fact in result["facts"]}
            self.assertEqual(facts["abroad-source:resources:online-1"]["first_channel"], "网络资源")
            self.assertEqual(facts["abroad-source:resources:online-1"]["second_channel"], "大众")
            self.assertEqual(facts["abroad-source:resources:online-1"]["team_id"], "online_platform")
            market = facts["abroad-source:resources:market-1"]
            self.assertEqual(market["second_channel"], "中学活动")
            self.assertEqual(market["team_id"], "offline_market")
            self.assertTrue(market["offline_channel_eligible"])
            self.assertFalse(market["counts_toward_completion"])
            self.assertEqual(facts["abroad-source:resources:market-online"]["second_channel"], "高校活动")
            self.assertEqual(facts["abroad-source:resources:market-online"]["acquisition_mode"], "online")
            ssc = facts["abroad-source:resources:ssc"]
            self.assertEqual(ssc["second_channel"], "SSC")
            self.assertIsNone(ssc["team_id"])
            self.assertEqual(facts["abroad-source:resources:international"]["owners"], [])
            self.assertIsNone(facts["abroad-source:resources:international"]["team_id"])
            self.assertEqual(facts["abroad-source:contracts:positive"]["metric"], "cash")
            self.assertTrue(facts["abroad-source:contracts:positive"]["counts_toward_completion"])
            self.assertEqual(facts["abroad-source:contracts:positive"]["work_order_id"], None)
            self.assertEqual(facts["abroad-source:contracts:positive"]["student_id"], "study_abroad:U-1")
            self.assertEqual(facts["abroad-source:languages:sha:4"]["source_product"], "small_language")
            self.assertNotIn("abroad-source:contracts:negative", facts)
            self.assertEqual(facts["abroad-source:contracts:unmapped"]["value"], 25.0)
            self.assertEqual(facts["abroad-source:contracts:unmapped"]["second_channel"], "渠道待确认")
            self.assertEqual(result["diagnostics"]["nonpositive_signatures_excluded"], 1)
            self.assertIn(paths["raw_source"], result["source_paths"])
            self.assertIn(paths["prepared_source"], result["source_paths"])
            self.assertIn(paths["people_roster"], result["source_paths"])
            self.assertEqual(paths["workspace_config"].read_bytes(), paths["workspace_config_bytes"])
            self.assertEqual(paths["pointer"].read_bytes(), paths["pointer_bytes"])


if __name__ == "__main__":
    unittest.main()
