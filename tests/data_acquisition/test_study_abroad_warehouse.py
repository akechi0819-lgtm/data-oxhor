"""End-to-end checks for the isolated study-abroad sample warehouse."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook

from dashboard_product.management.study_abroad_query import query_sample
from data_acquisition.jobs import build_study_abroad_warehouse
from data_platform.query.evidence import read_query_result


RESOURCE_HEADERS = [
    "资源ID", "分单日期", "市场资源归属人", "市场资源归属组",
    "线下组资源", "市场活动", "咨询类型",
]
CONTRACT_HEADERS = [
    "记录id", "合同编号", "客户ID", "归档月份", "归档日期",
    "市场资源归属人", "市场资源归属组", "签约金额", "91资源市场活动",
]
LANGUAGE_HEADERS = [
    "资源ID", "工单ID", "业务日期", "市场资源归属人", "市场资源归属组",
    "实缴金额", "学员编号", "语种", "新签/续签", "来访类型", "渠道来源", "渠道明细",
]


def _resource(resource_id: str, owner: str, status: str = "正常",
              consultation_type: str = "留学") -> dict[str, object]:
    return {
        "资源ID": resource_id,
        "分单日期": date(2026, 9, 10),
        "市场资源归属人": owner,
        # The real export can contain a lookup formula without a cached value.
        "市场资源归属组": "=#N/A",
        "线下组资源": status,
        "市场活动": "合成活动",
        "咨询类型": consultation_type,
    }


def _contract(
    contract_id: str,
    customer_id: str,
    owner: str,
    amount: int,
    *,
    resource_id: str = "1001",
) -> dict[str, object]:
    return {
        "记录id": resource_id,
        "合同编号": contract_id,
        "客户ID": customer_id,
        "归档月份": "2026-09",
        "归档日期": date(2026, 9, 12),
        "市场资源归属人": owner,
        "市场资源归属组": "=#N/A",
        "签约金额": amount,
        "91资源市场活动": "合成活动",
    }


def _language(
    work_order_id: str,
    student_id: str,
    owner: str,
    amount: int,
    *,
    resource_id: str = "/",
) -> dict[str, object]:
    return {
        "资源ID": resource_id,
        "工单ID": work_order_id,
        "业务日期": date(2026, 9, 15),
        "市场资源归属人": owner,
        "市场资源归属组": "=#N/A",
        "实缴金额": amount,
        "学员编号": student_id,
        "语种": "日语",
        "新签/续签": "新签",
        "来访类型": "线上",
        "渠道来源": "合成来源",
        "渠道明细": "合成渠道",
    }


def _base_records() -> dict[str, list[dict[str, object]]]:
    resources = [
        _resource("1001", "线下甲", "删除"),
        _resource("1002", "线下甲", "回收"),
        _resource("1003", "线下甲", "死单"),
        _resource("1004", "线上甲"),
        _resource("1005", "国际市场"),
        _resource("1006", "网络SSC"),
        _resource("1007", "未配置甲"),
        _resource("1008", ""),
        # An identical source duplicate must not inflate the resource count.
        _resource("1005", "国际市场"),
    ]
    contracts = [
        _contract(f"C-SHARED-{number}", "CUSTOMER-SHARED", "线下甲", 100)
        for number in range(1, 9)
    ]
    # An identical contract duplicate is allowed and is removed by the query.
    contracts.append(dict(contracts[0]))
    contracts.extend([
        # This customer appears in two roster teams and is distinct once at total.
        _contract("C-SHARED-ONLINE", "CUSTOMER-SHARED", "线上甲", 50, resource_id="1004"),
        # International market is present in online_private in the test roster,
        # but belongs only in its own supplemental segment.
        _contract("C-INTL", "CUSTOMER-INTL", "国际市场", 70, resource_id="1005"),
        _contract("C-SSC", "CUSTOMER-SSC", "网络SSC", 80, resource_id="1006"),
        _contract("C-UNKNOWN", "CUSTOMER-UNKNOWN", "未配置甲", 90, resource_id="1007"),
        _contract("C-BLANK", "CUSTOMER-BLANK", "", 500, resource_id="1008"),
        _contract("C-NEGATIVE", "CUSTOMER-NEGATIVE", "线下甲", -40),
        _contract("C-ZERO", "CUSTOMER-ZERO", "线下甲", 0),
    ])
    languages = [
        # Slash resource IDs do not invalidate independently keyed signings.
        _language("L-001", "STUDENT-SHARED", "线下甲", 25),
        _language("L-002", "STUDENT-SHARED", "线上甲", 30),
        _language("L-NEGATIVE", "STUDENT-NEGATIVE", "线下甲", -5),
        _language("L-ZERO", "STUDENT-ZERO", "线下甲", 0),
        _language("L-BLANK", "STUDENT-BLANK", "", 100),
    ]
    return {"资源": resources, "留学签约": contracts, "小语种签约": languages}


def _write_workbook(path: Path, records: dict[str, list[dict[str, object]]]) -> None:
    workbook = Workbook()
    resource_sheet = workbook.active
    resource_sheet.title = "资源"
    for name in ("留学签约", "小语种签约"):
        workbook.create_sheet(name)

    for name, headers in (
        ("资源", RESOURCE_HEADERS),
        ("留学签约", CONTRACT_HEADERS),
        ("小语种签约", LANGUAGE_HEADERS),
    ):
        sheet = workbook[name]
        sheet.append(headers)
        for record in records[name]:
            sheet.append([record.get(header) for header in headers])

    # The source workbook's hidden two-column owner map remains readable even
    # when the visible source-group formula has no cached value.
    mapping = workbook.create_sheet("筛选项")
    mapping.sheet_state = "hidden"
    mapping.auto_filter.ref = "A1:B4"
    mapping.append(["线下甲", "线下组"])
    mapping.append(["线上甲", "线上组"])
    mapping.append(["国际市场", "国际市场"])
    mapping.append(["网络SSC", "SSC"])
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    workbook.close()


def _write_rosters(root: Path) -> tuple[Path, Path]:
    people_path = root / "fixtures" / "people.json"
    abroad_people_path = root / "fixtures" / "abroad_people.json"
    people_path.parent.mkdir(parents=True, exist_ok=True)
    people = {
        "schema_version": "dashboard_people.v1",
        "scope": "current_roster",
        "teams": [
            {
                "team_id": "online_private",
                "display_name": "线上私域",
                "groups": [{"display_name": "大学组", "members": [
                    {"display_name": "线上甲", "status": "active", "business_group": "大学"},
                    {"display_name": "国际市场", "status": "active", "business_group": "大学"},
                ]}],
            },
        ],
    }
    abroad_people = {
        "team_id": "study_abroad_offline",
        "people": [{"display_name": "线下甲", "business_group": "大学"}],
    }
    people_path.write_text(json.dumps(people, ensure_ascii=False), encoding="utf-8")
    abroad_people_path.write_text(json.dumps(abroad_people, ensure_ascii=False), encoding="utf-8")
    return people_path, abroad_people_path


def _hash_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bi_state(workspace: Path) -> tuple[str | None, dict[str, str]]:
    config = workspace / "Work" / "workspace.json"
    config_hash = _hash_bytes(config) if config.is_file() else None
    inputs = workspace / "Input"
    files = {
        path.relative_to(workspace).as_posix(): _hash_bytes(path)
        for path in sorted(inputs.rglob("*")) if path.is_file()
    } if inputs.exists() else {}
    return config_hash, files


def _write_bi_workspace(workspace: Path) -> None:
    config = workspace / "Work" / "workspace.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({
        "schema_version": "workspace.v1",
        "company_id": "company_bi_keep_fixture",
        "current_snapshot_id": "snapshot_bi_keep_fixture",
        "current_warehouse_path": "Work/Runs/snapshot_bi_keep_fixture/warehouse.duckdb",
    }), encoding="utf-8")
    (workspace / "Input" / "Data").mkdir(parents=True, exist_ok=True)
    (workspace / "Input" / "Data" / "keep.txt").write_text("BI sample stays unchanged\n", encoding="utf-8")


class StudyAbroadWarehouseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        _write_bi_workspace(self.workspace)
        self.people_path, self.abroad_people_path = _write_rosters(self.root)
        self.source_file = self.root / "sample" / "study-abroad.xlsx"
        _write_workbook(self.source_file, _base_records())

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _build(self, *, run_id: str = "run_study_abroad_sample",
               snapshot_id: str = "snapshot_study_abroad_sample",
               source_file: Path | None = None) -> dict:
        return build_study_abroad_warehouse.build(
            workspace=self.workspace,
            source_file=source_file or self.source_file,
            run_id=run_id,
            snapshot_id=snapshot_id,
            through_date="2026-09-30",
            people_path=self.people_path,
            abroad_people_path=self.abroad_people_path,
        )

    def _query(self, snapshot_id: str, query_name: str, run_id: str) -> dict:
        response = query_sample(
            workspace=self.workspace,
            snapshot_id=snapshot_id,
            run_id=run_id,
            start_date="2026-06-01",
            end_date="2026-09-30",
            query_name=query_name,
        )
        return read_query_result(
            response,
            output_root=self.workspace / "Output" / "StudyAbroad",
        )

    def _rows(self, data: dict) -> list[dict[str, object]]:
        return [dict(zip(data["columns"], row)) for row in data["rows"]]

    def test_signing_and_paid_amounts_follow_their_sheet_owner_with_a_shared_resource_id(self) -> None:
        records = {
            "资源": [_resource("41001", "网络SSC")],
            "留学签约": [
                _contract("C-OWNER-SPLIT", "CUSTOMER-ABROAD-OWNER", "线下甲", 120,
                          resource_id="41001"),
            ],
            "小语种签约": [
                _language("L-OWNER-SPLIT", "STUDENT-LANGUAGE-OWNER", "线上甲", 80,
                          resource_id="41001"),
            ],
        }
        source = self.root / "sample" / "owner-split.xlsx"
        _write_workbook(source, records)
        built = self._build(
            run_id="run_study_abroad_owner_split",
            snapshot_id="snapshot_study_abroad_owner_split",
            source_file=source,
        )

        response = query_sample(
            workspace=self.workspace,
            snapshot_id=built["snapshot_id"],
            run_id="run_study_abroad_owner_split_query",
            start_date="2026-09-01",
            end_date="2026-10-01",
            query_name="monthly",
        )
        data = read_query_result(
            response,
            output_root=self.workspace / "Output" / "StudyAbroad",
        )
        september = [row for row in self._rows(data) if row.get("month") == "2026-09"]
        total = next(row for row in september
                     if row.get("scope") == "total" and row.get("segment_id") == "total")
        offline = next(row for row in september
                       if row.get("scope") == "team"
                       and row.get("segment_id") == "study_abroad_offline")
        online = next(row for row in september
                      if row.get("scope") == "team"
                      and row.get("segment_id") == "study_abroad_online")
        ssc = next(row for row in september
                   if row.get("scope") == "supplemental"
                   and row.get("segment_id") == "ssc")

        # The resource owner only attributes the resource itself to SSC.
        self.assertEqual(1, total["resource_count"])
        self.assertEqual(1, ssc["resource_count"])
        self.assertEqual(0, offline["resource_count"])
        self.assertEqual(0, online["resource_count"])

        # Both money rows share resource 41001, but each follows its own sheet owner.
        self.assertEqual(Decimal("200.00"), Decimal(str(total["gross_signing_amount"])))
        self.assertEqual(Decimal("120.00"), Decimal(str(offline["gross_signing_amount"])))
        self.assertEqual(Decimal("80.00"), Decimal(str(online["gross_signing_amount"])))
        self.assertEqual(Decimal("0.00"), Decimal(str(ssc["gross_signing_amount"])))
        self.assertEqual(1, offline["study_abroad_signed_customers"])
        self.assertEqual(1, online["small_language_signed_customers"])

    def test_isolated_build_and_monthly_rules_are_queryable_with_evidence(self) -> None:
        bi_before = _bi_state(self.workspace)
        built = self._build()

        warehouse_path = Path(built["warehouse"])
        self.assertTrue(warehouse_path.is_file())
        self.assertTrue(warehouse_path.resolve().is_relative_to(
            (self.workspace / "Work" / "StudyAbroad" / "Runs").resolve()
        ))
        self.assertEqual("snapshot_study_abroad_sample", built["snapshot_id"])
        self.assertEqual(_hash_bytes(self.source_file), built["source_sha256"])
        self.assertTrue((self.workspace / "Work" / "StudyAbroad" / "current.json").is_file())
        self.assertEqual(bi_before, _bi_state(self.workspace))

        data = self._query(
            built["snapshot_id"], "monthly", "run_study_abroad_monthly",
        )
        rows = self._rows(data)
        september = [row for row in rows if row.get("month") == "2026-09"]
        total = next(row for row in september
                     if row.get("scope") == "total" and row.get("segment_id") == "total")
        offline = next(row for row in september
                       if row.get("scope") == "team"
                       and row.get("segment_id") == "study_abroad_offline")
        online = next(row for row in september
                      if row.get("scope") == "team"
                      and row.get("segment_id") == "study_abroad_online")
        international = next(row for row in september
                             if row.get("scope") == "supplemental"
                             and row.get("segment_id") == "international_market")
        ssc = next(row for row in september
                   if row.get("scope") == "supplemental" and row.get("segment_id") == "ssc")
        unassigned = next(row for row in september
                          if row.get("scope") == "supplemental"
                          and row.get("segment_id") == "unassigned")

        # Department counts include deleted records; personal counts exclude only them.
        self.assertEqual(3, offline["resource_count"])
        self.assertEqual(2, offline["personal_resource_count"])
        self.assertEqual(1, online["resource_count"])
        self.assertEqual(1, international["resource_count"])
        self.assertEqual(1, ssc["resource_count"])
        self.assertEqual(1, unassigned["resource_count"])
        self.assertEqual(7, total["resource_count"])
        self.assertEqual(6, total["personal_resource_count"])

        # Eight contracts for one person contribute eight amounts and one customer.
        # The same customer also signs online, so the total remains one customer.
        self.assertEqual(Decimal("1145.00"), Decimal(str(total["gross_signing_amount"])))
        self.assertEqual(4, total["study_abroad_signed_customers"])
        self.assertEqual(1, offline["study_abroad_signed_customers"])
        self.assertEqual(1, online["study_abroad_signed_customers"])
        self.assertEqual(1, international["study_abroad_signed_customers"])
        self.assertEqual(1, ssc["study_abroad_signed_customers"])
        self.assertEqual(1, unassigned["study_abroad_signed_customers"])

        # Slash resource IDs still contribute language amount and learner count;
        # the distinct total across both business systems remains unavailable.
        self.assertEqual(1, total["small_language_signed_customers"])
        self.assertIsNone(total["signed_customer_count"])
        self.assertEqual("cross_system_unaligned", total["signed_customer_count_status"])

        # A missing historical month is absent, rather than a fabricated zero row.
        self.assertNotIn("2026-08", {row.get("month") for row in rows})

    def test_named_queries_all_return_results_that_can_be_read_from_receipts(self) -> None:
        built = self._build()
        for name in ("facts", "monthly", "people", "checks"):
            with self.subTest(query_name=name):
                data = self._query(
                    built["snapshot_id"], name, f"run_study_abroad_{name}",
                )
                self.assertIsInstance(data.get("columns"), list)
                self.assertIsInstance(data.get("rows"), list)

        checks = {
            row["source_kind"]: row
            for row in self._rows(self._query(
                built["snapshot_id"], "checks", "run_study_abroad_check_counts",
            ))
        }
        self.assertEqual(9, checks["resources"]["source_rows"])
        self.assertEqual(16, checks["contracts"]["source_rows"])
        self.assertEqual(5, checks["languages"]["source_rows"])
        self.assertEqual(1, checks["resources"]["blank_owner_rows"])
        self.assertEqual(1, checks["contracts"]["blank_owner_rows"])
        self.assertEqual(1, checks["languages"]["blank_owner_rows"])
        self.assertEqual(1, checks["resources"]["unmapped_owner_rows"])
        self.assertEqual(1, checks["contracts"]["unmapped_owner_rows"])
        self.assertEqual(1, checks["resources"]["deleted_resource_rows"])
        self.assertEqual(1, checks["contracts"]["negative_amount_rows"])
        self.assertEqual(1, checks["contracts"]["zero_amount_rows"])
        self.assertEqual(1, checks["languages"]["negative_amount_rows"])
        self.assertEqual(1, checks["languages"]["zero_amount_rows"])

    def test_reused_snapshot_is_rejected_without_touching_bi_workspace_or_pointer(self) -> None:
        bi_before = _bi_state(self.workspace)
        first = self._build()
        pointer = self.workspace / "Work" / "StudyAbroad" / "current.json"
        pointer_before = pointer.read_bytes()

        with self.assertRaisesRegex(ValueError, "Snapshot|已使用"):
            self._build(run_id="run_study_abroad_duplicate",
                        snapshot_id=first["snapshot_id"])

        self.assertEqual(pointer_before, pointer.read_bytes())
        self.assertEqual(bi_before, _bi_state(self.workspace))

    def test_conflicting_resource_or_contract_key_blocks_publication(self) -> None:
        cases = (
            ("resource", "同一资源|冲突"),
            ("contract", "同一合同|冲突"),
        )
        for index, (kind, message) in enumerate(cases, 1):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory) / "workspace"
                _write_bi_workspace(workspace)
                people_path, abroad_people_path = _write_rosters(Path(directory))
                source = Path(directory) / "sample.xlsx"
                _write_workbook(source, _base_records())
                build_study_abroad_warehouse.build(
                    workspace=workspace,
                    source_file=source,
                    run_id=f"run_study_abroad_prior_{index}",
                    snapshot_id=f"snapshot_study_abroad_prior_{index}",
                    through_date="2026-09-30",
                    people_path=people_path,
                    abroad_people_path=abroad_people_path,
                )
                records = _base_records()
                if kind == "resource":
                    records["资源"].append(_resource("1001", "线下甲", "正常"))
                else:
                    records["留学签约"].append(
                        _contract("C-SHARED-1", "CUSTOMER-OTHER", "线下甲", 999)
                    )
                _write_workbook(source, records)
                pointer = workspace / "Work" / "StudyAbroad" / "current.json"
                pointer_before = pointer.read_bytes()

                with self.assertRaisesRegex(ValueError, message):
                    build_study_abroad_warehouse.build(
                        workspace=workspace,
                        source_file=source,
                        run_id=f"run_study_abroad_conflict_{index}",
                        snapshot_id=f"snapshot_study_abroad_conflict_{index}",
                        through_date="2026-09-30",
                        people_path=people_path,
                        abroad_people_path=abroad_people_path,
                    )

                self.assertEqual(pointer_before, pointer.read_bytes())


if __name__ == "__main__":
    unittest.main()
