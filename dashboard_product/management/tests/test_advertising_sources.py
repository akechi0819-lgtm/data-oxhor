import hashlib
import json
import tempfile
import unittest
import zipfile
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

from openpyxl import Workbook

from dashboard_product.management.advertising_sources import (
    load_sources,
)
from dashboard_product.management.platforms import canonical_platform


def manifest_source(path, *, source_id="cost-1", kind="xhs_daily",
                    business_line="training", business_group="高中",
                    platform="小红书", sha256=None, company=None):
    item = {
        "source_id": source_id,
        "path": str(path),
        "kind": kind,
        "business_line": business_line,
        "business_group": business_group,
    }
    if platform is not None:
        item["platform"] = platform
    if sha256 is not None:
        item["sha256"] = sha256
    if company is not None:
        item["company"] = company
    return item


def write_manifest(folder, sources, network_period_differences=None):
    path = Path(folder) / "cost_manifest.json"
    manifest = {"sources": sources}
    if network_period_differences is not None:
        manifest["network_period_differences"] = network_period_differences
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return path


def make_workbook(path, rows):
    book = Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    book.save(path)
    book.close()


def make_network_workbook(path, start_date, end_date, channels, *, company="天津"):
    rows = [
        ["网络渠道费用"],
        [start_date, end_date, company],
        ["公司", "渠道中类", "总推广费用"],
        *[[row_company, channel, amount] for channel, amount, row_company in channels],
    ]
    make_workbook(path, rows)


def network_source(path, source_id):
    return manifest_source(
        path, source_id=source_id, kind="network_weekly", platform=None,
        business_line="abroad", business_group="留学整体", company="天津",
    )


def period_difference(cumulative_source_id="network-cumulative", current_source_id="network-october"):
    return {
        "source_id": "network-september",
        "cumulative_source_id": cumulative_source_id,
        "current_source_id": current_source_id,
        "start_date": "2026-09-01",
        "end_date": "2026-09-30",
        "missing_current_channel_policy": "zero_for_complete_source",
    }


def set_stale_sheet_dimension(path):
    with zipfile.ZipFile(path) as source:
        entries = [(item, source.read(item.filename)) for item in source.infolist()]
    rewritten = []
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    for item, content in entries:
        if item.filename == "xl/worksheets/sheet1.xml":
            root = ET.fromstring(content)
            dimension = root.find(f"{namespace}dimension")
            if dimension is not None:
                dimension.set("ref", "A1:A1")
            content = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        rewritten.append((item, content))
    replacement = Path(path).with_suffix(".rewritten.xlsx")
    with zipfile.ZipFile(replacement, "w", zipfile.ZIP_DEFLATED) as target:
        for item, content in rewritten:
            target.writestr(item, content)
    replacement.replace(path)


class AdvertisingSourcesTests(unittest.TestCase):
    def test_native_project_report_replaces_both_months_without_dropping_other_platform(self):
        with tempfile.TemporaryDirectory() as folder:
            cumulative, october, native = [Path(folder) / name for name in ("cumulative.xlsx", "october.xlsx", "native.xlsx")]
            make_network_workbook(cumulative, "2026-09-01", "2026-10-11",
                                  [("抖音", 100, "天津"), ("百度", 50, "天津")])
            make_network_workbook(october, "2026-10-01", "2026-10-11",
                                  [("抖音", 40, "天津"), ("百度", 20, "天津")])
            make_workbook(native, [("项目ID", "日期", "投放类型", "营销场景", "消耗(元)"),
                                   ("p1", "2026-09-01", "通投", "短视频", 10),
                                   ("p1", "2026-10-01", "通投", "短视频", 20)])
            current = network_source(october, "network-october")
            current["exclude_platforms"] = ["抖音"]
            difference = period_difference()
            difference["exclude_platforms"] = ["抖音"]
            costs = load_sources(write_manifest(folder,
                [network_source(cumulative, "network-cumulative"), current,
                 manifest_source(native, source_id="native", kind="ocean_daily", business_line="abroad",
                                 business_group="留学整体", platform="抖音")], [difference]))
            self.assertEqual(sum(r["amount"] for r in costs["rows"] if r["platform"] == "抖音"), 30)
            self.assertEqual(sum(r["amount"] for r in costs["rows"] if r["platform"] == "百度"), 50)
            self.assertTrue(all(s["source_id"] == "native" for s in costs["sources"] if s["platform"] == "抖音"))

    def test_native_replacement_excludes_old_october_platform_but_preserves_september(self):
        with tempfile.TemporaryDirectory() as folder:
            cumulative = Path(folder) / "cumulative.xlsx"
            october = Path(folder) / "october.xlsx"
            make_network_workbook(cumulative, "2026-09-01", "2026-10-11",
                                  [("百度", 100, "天津"), ("微信", 50, "天津")])
            make_network_workbook(october, "2026-10-01", "2026-10-11",
                                  [("百度", 40, "天津"), ("微信", 20, "天津")])
            current = network_source(october, "network-october")
            current["exclude_platforms"] = ["百度"]
            costs = load_sources(write_manifest(folder,
                [network_source(cumulative, "network-cumulative"), current], [period_difference()]))
            self.assertFalse(any(r["source_id"] == "network-october" and r["platform"] == "百度" for r in costs["rows"]))
            september = next(r for r in costs["rows"] if r["source_id"] == "network-september" and r["platform"] == "百度")
            self.assertEqual(september["amount"], 60)
            self.assertTrue(any(r["source_id"] == "network-october" and r["platform"] == "微信" for r in costs["rows"]))

    def test_missing_manifest_is_an_unconfigured_business_state(self):
        self.assertEqual(load_sources(None), {"rows": [], "sources": [], "configured": False})

    def test_xhs_summary_is_reconciliation_only_and_zero_differs_from_blank(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / "xhs.csv"
            source.write_text(
                "时间,消费\n2026-10-03,0\n2026-10-04,\n2026-10-05,12.5\n合计,12.5\n",
                encoding="utf-8-sig",
            )
            original = source.read_bytes()
            manifest = write_manifest(folder, [manifest_source(source)])

            result = load_sources(manifest)

            self.assertTrue(result["configured"])
            self.assertEqual([row["source_row"] for row in result["rows"]], [2, 3, 4])
            self.assertEqual([row["amount"] for row in result["rows"]], [0.0, None, 12.5])
            self.assertEqual(result["rows"][0]["start_date"], "2026-10-03")
            self.assertEqual(result["rows"][1]["end_date"], "2026-10-04")
            self.assertTrue(all(row["business_group"] == "高中" for row in result["rows"]))
            self.assertEqual(result["sources"][0]["grain"], "daily")
            self.assertEqual(source.read_bytes(), original)

    def test_ocean_control_row_is_not_counted_and_daily_duplicate_key_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / "ocean.xlsx"
            make_workbook(source, [
                ["日期", "消耗(元)", "项目ID", "投放类型", "营销场景"],
                ["合计", 0, None, None, None],
                ["2026-10-10", 0, "p1", "信息流", "招生"],
                ["2026-10-11", None, "p2", "信息流", "招生"],
            ])
            manifest = write_manifest(folder, [manifest_source(
                source, kind="ocean_daily", platform="抖音", business_group="留学预备",
            )])

            result = load_sources(manifest)

            self.assertEqual(len(result["rows"]), 2)
            self.assertEqual([row["amount"] for row in result["rows"]], [0.0, None])
            self.assertEqual([row["source_row"] for row in result["rows"]], [3, 4])
            self.assertEqual(result["rows"][0]["business_group"], "留学预备")

            duplicate = folder / "ocean_duplicate.xlsx"
            make_workbook(duplicate, [
                ["日期", "消耗(元)", "项目ID", "投放类型", "营销场景"],
                ["2026-10-10", 0, "p1", "信息流", "招生"],
                ["2026-10-10", 2, "p1", "信息流", "招生"],
            ])
            duplicate_manifest = write_manifest(folder, [manifest_source(
                duplicate, kind="ocean_daily", platform="抖音",
            )])
            with self.assertRaisesRegex(ValueError, "重复项目日期投放键"):
                load_sources(duplicate_manifest)

    def test_manual_ocean_declared_summary_delta_and_certified_through_date(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / "ocean.xlsx"
            make_workbook(source, [
                ["日期", "消耗(元)", "营销场景", "投放类型"],
                [None, 29.97, None, None],
                ["2026-11-24", 10, "短视频", "通投"],
                ["2026-11-25", 20, "短视频", "通投"],
            ])
            entry = manifest_source(source, kind="ocean_account_daily", platform="抖音",
                                    sha256=hashlib.sha256(source.read_bytes()).hexdigest())
            entry.update(account_id="12345", reported_detail_delta="0.03", through_date="2026-11-24")

            result = load_sources(write_manifest(folder, [entry]))

            self.assertEqual([(row["start_date"], row["amount"]) for row in result["rows"]],
                             [("2026-11-24", 10.0)])
            metadata = result["sources"][0]
            self.assertEqual(metadata["reported_detail_delta"], "0.03")
            self.assertEqual((metadata["start_date"], metadata["end_date"]),
                             ("2026-11-24", "2026-11-24"))

            undeclared = {key: value for key, value in entry.items() if key != "reported_detail_delta"}
            with self.assertRaisesRegex(ValueError, "账户日报明细与合计不符"):
                load_sources(write_manifest(folder, [undeclared]))

    def test_xlsx_payload_with_csv_extension_uses_read_only_workbook_reader(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / "export.csv"
            make_workbook(source, [
                ["时间", "消费"],
                ["2026-10-03", 0],
                ["合计", 0],
            ])
            original = source.read_bytes()
            manifest = write_manifest(folder, [manifest_source(source)])

            result = load_sources(manifest)

            self.assertEqual(len(result["rows"]), 1)
            self.assertEqual(result["rows"][0]["amount"], 0.0)
            self.assertEqual(source.read_bytes(), original)

    def test_identical_bytes_at_distinct_paths_are_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / "xhs.csv"
            copy = folder / "copy.csv"
            source.write_text("时间,消费\n2026-10-03,10\n", encoding="utf-8")
            copy.write_bytes(source.read_bytes())
            with self.assertRaisesRegex(ValueError, "相同sha256"):
                load_sources(write_manifest(folder, [
                    manifest_source(source, source_id="xhs-a"),
                    manifest_source(copy, source_id="xhs-b"),
                ]))

    def test_network_weekly_keeps_period_rows_and_platform_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / "network.xlsx"
            make_workbook(source, [
                ["网络渠道费用"],
                ["2026-10-03", "2026-10-09"],
                ["渠道中类", "总推广费用"],
                ["小红书KOS品专", 100],
                ["今日头条", 50],
                ["腾讯广告", 20],
                ["腾讯地图", 21],
                ["灵蹊三方来源", 5],
            ])
            set_stale_sheet_dimension(source)
            original = source.read_bytes()
            manifest = write_manifest(folder, [manifest_source(
                source, kind="network_weekly", platform=None,
                business_line="abroad", business_group="留学整体",
            )])

            result = load_sources(manifest)

            self.assertEqual(len(result["rows"]), 5)
            self.assertEqual(
                [row["platform"] for row in result["rows"]],
                ["小红书", "抖音", "腾讯广告", "腾讯地图", "其他线上来源"],
            )
            self.assertTrue(all(row["start_date"] == "2026-10-03" for row in result["rows"]))
            self.assertTrue(all(row["end_date"] == "2026-10-09" for row in result["rows"]))
            self.assertEqual([row["amount"] for row in result["rows"]], [100.0, 50.0, 20.0, 21.0, 5.0])
            self.assertEqual({source["grain"] for source in result["sources"]}, {"period"})
            self.assertEqual(len(result["sources"]), 5)
            self.assertTrue(all(source["business_group"] == "留学整体" for source in result["sources"]))
            self.assertEqual(source.read_bytes(), original)

    def test_network_rows_use_the_shared_platform_taxonomy(self):
        expected = {
            "抖音广告": "抖音",
            "今日头条": "抖音",
            "KOS品专": "小红书",
            "知了好学": "百度",
            "大众点评": "美团/大众点评",
            "视频号": "微信",
            "腾讯广告": "腾讯广告",
            "腾讯地图": "腾讯地图",
            "官网小程序": "官网/自有入口",
            "乐语咨询": "电话/在线咨询",
            "必应搜索": "必应",
            "灵蹊三方来源": "其他线上来源",
            "腾讯广告+腾讯地图": "其他线上来源",
        }
        for label, canonical in expected.items():
            with self.subTest(label=label):
                self.assertEqual(canonical_platform(label), canonical)

    def test_network_cumulative_minus_monthly_preserves_platform_totals_and_period_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            cumulative = folder / "cumulative.xlsx"
            current = folder / "current.xlsx"
            make_network_workbook(cumulative, "2026-09-01", "2026-10-11", [
                ("百度搜索-PC", 1000, "天津"),
                ("百度搜索-移动", 500, "天津"),
                ("小红书", 100, "天津"),
                ("微信视频号", 25, "天津"),
                ("抖音品牌号", 0, "天津"),
            ])
            make_network_workbook(current, "2026-10-01", "2026-10-11", [
                ("百度搜索-PC", 1200, "天津"),
                ("百度搜索-移动", 200, "天津"),
                ("小红书", 10, "天津"),
                ("抖音品牌号", 50, "天津"),
            ])
            cumulative_source = network_source(cumulative, "network-cumulative")
            current_source = network_source(current, "network-october")
            manifest = write_manifest(
                folder,
                [cumulative_source, current_source],
                [period_difference()],
            )

            result = load_sources(manifest)

            rows_by_source = {}
            for source_id in ("network-september", "network-october"):
                rows_by_source[source_id] = {
                    row["raw_channel"]: row for row in result["rows"] if row["source_id"] == source_id
                }
            cumulative_values = {
                "百度搜索-PC": 1000,
                "百度搜索-移动": 500,
                "小红书": 100,
                "微信视频号": 25,
                "抖音品牌号": 0,
            }
            for channel, total in cumulative_values.items():
                september = Decimal(str(rows_by_source["network-september"][channel]["amount"]))
                october = Decimal(str(rows_by_source["network-october"].get(channel, {}).get("amount", 0)))
                self.assertEqual(september + october, Decimal(str(total)), channel)

            platform_totals = {}
            for row in result["rows"]:
                if row["source_id"] == "network-september":
                    platform_totals[row["platform"]] = platform_totals.get(row["platform"], 0) + row["amount"]
            self.assertEqual(platform_totals, {
                "百度": 100,
                "小红书": 90,
                "微信": 25,
                "抖音": -50,
            })
            missing_row = rows_by_source["network-september"]["微信视频号"]
            self.assertTrue(missing_row["derivation"]["missing_current_channel_zero_filled"])
            self.assertIsNone(missing_row["derivation"]["current_source_row"])
            self.assertEqual(missing_row["derivation"]["current_amount"], "0")

            self.assertEqual(
                {row["source_id"] for row in result["rows"]},
                {"network-september", "network-october"},
            )
            self.assertEqual(
                {(source["source_id"], source["grain"], source["start_date"], source["end_date"])
                 for source in result["sources"]},
                {
                    ("network-september", "period", "2026-09-01", "2026-09-30"),
                    ("network-october", "period", "2026-10-01", "2026-10-11"),
                },
            )
            self.assertNotIn("network-cumulative", {row["source_id"] for row in result["rows"]})
            derived_source = next(source for source in result["sources"]
                                  if source["source_id"] == "network-september")
            self.assertEqual(derived_source["derivation"]["method"], "cumulative_minus_current")
            self.assertEqual(derived_source["derivation"]["match_key"], "渠道中类原始值")
            self.assertEqual(
                {item["source_id"] for item in derived_source["derivation"]["input_sources"]},
                {"network-cumulative", "network-october"},
            )
            self.assertTrue(all(item["sha256"] for item in derived_source["derivation"]["input_sources"]))

    def test_network_difference_blocks_missing_cumulative_channels_blank_amounts_and_company_conflicts(self):
        cases = [
            (
                "current-only-channel",
                [("百度搜索-PC", 100, "天津")],
                [("百度搜索-PC", 10, "天津"), ("微信搜索", 5, "天津")],
                "本月表出现累计表缺失的原渠道",
            ),
            (
                "cumulative-blank-amount",
                [("百度搜索-PC", None, "天津")],
                [("百度搜索-PC", 10, "天津")],
                "累计表总推广费用为空",
            ),
            (
                "current-blank-amount",
                [("百度搜索-PC", 100, "天津")],
                [("百度搜索-PC", None, "天津")],
                "本月表总推广费用为空",
            ),
            (
                "company-mismatch",
                [("百度搜索-PC", 100, "天津")],
                [("百度搜索-PC", 10, "北京")],
                "公司不符",
            ),
        ]
        for case_name, cumulative_rows, current_rows, message in cases:
            with self.subTest(case=case_name), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                cumulative = folder / "cumulative.xlsx"
                current = folder / "current.xlsx"
                make_network_workbook(cumulative, "2026-09-01", "2026-10-11", cumulative_rows)
                make_network_workbook(current, "2026-10-01", "2026-10-11", current_rows)
                manifest = write_manifest(
                    folder,
                    [network_source(cumulative, "network-cumulative"),
                     network_source(current, "network-october")],
                    [period_difference()],
                )
                with self.assertRaisesRegex(ValueError, message):
                    load_sources(manifest)

    def test_network_difference_rejects_duplicate_raw_channels(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            cumulative = folder / "cumulative.xlsx"
            current = folder / "current.xlsx"
            make_network_workbook(cumulative, "2026-09-01", "2026-10-11", [
                ("百度搜索-PC", 100, "天津"),
            ])
            make_network_workbook(current, "2026-10-01", "2026-10-11", [
                ("百度搜索-PC", 10, "天津"),
                ("百度搜索-PC", 5, "天津"),
            ])
            manifest = write_manifest(
                folder,
                [network_source(cumulative, "network-cumulative"),
                 network_source(current, "network-october")],
                [period_difference()],
            )

            with self.assertRaisesRegex(ValueError, "原始渠道重复"):
                load_sources(manifest)

    def test_same_physical_file_under_two_source_ids_is_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / "xhs.csv"
            source.write_text("时间,消费\n2026-10-03,10\n", encoding="utf-8")
            first = manifest_source(source, source_id="xhs-a")
            second = manifest_source(source, source_id="xhs-b")
            with self.assertRaisesRegex(ValueError, "物理费用文件"):
                load_sources(write_manifest(folder, [first, second]))

    def test_declared_hash_must_match_source_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / "xhs.csv"
            source.write_text("时间,消费\n2026-10-03,10\n", encoding="utf-8")
            wrong_hash = hashlib.sha256(b"different").hexdigest()
            entry = manifest_source(source, sha256=wrong_hash)
            with self.assertRaisesRegex(ValueError, "sha256不匹配"):
                load_sources(write_manifest(folder, [entry]))


if __name__ == "__main__":
    unittest.main()
