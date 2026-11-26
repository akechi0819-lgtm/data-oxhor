from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal
import unittest

import duckdb

from data_acquisition.jobs.work_order_cleaning import WorkOrderReference
from tests.legacy_dashboard.abroad_facts import _make_fact
from tests.legacy_dashboard.channels import legacy_channel
from dashboard_product.shadow_bi.sql_warehouse.abroad import (
    INPUT_COLUMNS,
    GRADE_INPUT_VIEW,
    _GRADE_TYPES,
    _INPUT_TYPES,
    _inline_view_sql,
    build_abroad_config,
    install_abroad,
)
from tests.legacy_dashboard.abroad_fixture import _bridge, _decisions, _fact_row


SOURCE_SHA = "a" * 64


def _row(*, fact_type="resource", fact_id="resources:1", event_date="2026-10-10",
         segment_id="study_abroad_offline", resource_id="1001", owner="留学甲",
         business_line="study_abroad", **extra):
    return _fact_row(
        fact_type=fact_type, fact_id=fact_id, business_line=business_line,
        event_date=event_date, segment_id=segment_id, resource_id=resource_id,
        owner=owner, source_sha256=SOURCE_SHA, **extra,
    )


def _mapping(row, channel):
    return {
        "raw_first_channel": row["first_channel"],
        "raw_second_channel": row["second_channel"],
        "raw_third_channel": row["third_channel"],
        "first_channel": channel[0],
        "second_channel": channel[1],
        "mapping_status": channel[2],
        "mapping_rule": channel[3],
    }


def _config(mappings=(), **overrides):
    return {
        "channel_mappings": list(mappings),
        "path_channels": [],
        "channel_rules": {},
        "country_lines": {"日本": "亚洲条线"},
        "country_line_fallbacks": {},
        "grade_policy": [],
        **overrides,
    }


def _fetch_facts(connection):
    cursor = connection.execute("SELECT * FROM business.abroad_facts ORDER BY fact_id")
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, values)) for values in cursor.fetchall()]


class StudyAbroadSQLWarehouseTests(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect()
        self.addCleanup(self.con.close)

    def test_fact_view_matches_legacy_output_and_keeps_cash_owner_separate(self):
        resource = _row(
            fact_id="resources:cash-owner", resource_id="ID: 1001.0",
            first_channel="网络资源", second_channel="店铺类", third_channel="美团点评",
            country="意向国家/地区：日本/英国",
        )
        cash = _row(
            fact_type="signature", fact_id="contracts:cash-owner",
            event_date="2026-10-12", segment_id="study_abroad_offline",
            business_line="small_language", resource_id="1001",
            owner="小语种签约甲", source_owner="原始签约归属",
            first_channel="网络资源", second_channel="店铺类", third_channel="美团点评",
            customer_key="languages:student-1", contract_id="C-1",
            gross_signing_amount="100.55", positive_signature=True,
        )
        mapping = ("网络资源", "大众", "matched_existing", "online_reference_exact")
        config = _config([_mapping(resource, mapping), _mapping(cash, mapping)])
        install_abroad(self.con, [resource, cash], config)

        facts = _fetch_facts(self.con)
        self.assertEqual(len(facts), 2)
        expected = {
            _make_fact(resource, mapping, Counter(), WorkOrderReference({}, {}, {"日本": "亚洲条线"}, {}, {}))["fact_id"],
            _make_fact(cash, mapping, Counter(), WorkOrderReference({}, {}, {"日本": "亚洲条线"}, {}, {}))["fact_id"],
        }
        self.assertEqual({fact["fact_id"] for fact in facts}, expected)
        by_id = {fact["fact_id"]: fact for fact in facts}
        for source_row, channel in ((resource, mapping), (cash, mapping)):
            legacy = _make_fact(
                source_row, channel, Counter(),
                WorkOrderReference({}, {}, {"日本": "亚洲条线"}, {}, {}),
            )
            actual = by_id[legacy["fact_id"]]
            for field, value in legacy.items():
                if field == "event_date":
                    value = date.fromisoformat(value)
                elif field == "value":
                    value = float(value)
                    self.assertEqual(float(actual[field]), value)
                    continue
                self.assertEqual(actual[field], value, field)
        self.assertEqual(by_id["abroad-source:contracts:cash-owner"]["owners"], ["小语种签约甲"])
        self.assertEqual(by_id["abroad-source:contracts:cash-owner"]["customer_domain"], "small_language")
        self.assertEqual(by_id["abroad-source:contracts:cash-owner"]["team_id"], "online_platform")
        self.assertEqual(by_id["abroad-source:contracts:cash-owner"]["value"], Decimal("100.55"))

    def test_latest_resource_is_selected_and_exact_duplicate_fact_rows_collapse(self):
        older = _row(
            fact_id="resources:old", event_date="2026-09-01",
            resource_id="9001", owner="旧归属",
        )
        newer = _row(
            fact_id="resources:new", event_date="2026-10-01",
            resource_id="资源 ID: 9001.0", owner="新归属",
            country="国家：日本,英国",
        )
        mapping = ("市场活动", "高校活动", "matched_existing", "market_activity")
        config = _config([_mapping(older, mapping), _mapping(newer, mapping)])

        install_abroad(self.con, [older, newer, dict(newer)], config)

        facts = _fetch_facts(self.con)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["fact_id"], "abroad-source:resources:new")
        self.assertEqual(facts[0]["owner"], "新归属")
        self.assertEqual(facts[0]["resource_id"], "9001")
        self.assertEqual(facts[0]["country"], "日本")
        self.assertEqual(facts[0]["line"], "亚洲条线")

    def test_international_source_owner_is_retained_and_fact_owner_stays_empty(self):
        row = _row(
            fact_id="resources:international", segment_id="international_market",
            owner="活动描述提及的归属", source_owner="确认来源归属",
            market_group="国际市场",
        )
        channel = ("新媒体", "分公司微信公众号", "matched_existing", "fixture")
        install_abroad(self.con, [row], _config([_mapping(row, channel)]))

        fact = _fetch_facts(self.con)[0]

        self.assertEqual(fact["owners"], [])
        self.assertEqual(fact["owner"], "活动描述提及的归属")
        self.assertEqual(fact["source_owner"], "确认来源归属")
        self.assertIsNone(fact["team_id"])
        self.assertEqual(fact["segment_id"], "international_market")

    def test_country_tail_with_contact_data_is_marked_untrusted(self):
        row = _row(country="意向国家：日本 联系邮箱 person@example.com")
        channel = ("网络资源", "大众", "matched_existing", "fixture")
        install_abroad(self.con, [row], _config([_mapping(row, channel)]))

        fact = _fetch_facts(self.con)[0]
        diagnostics = dict(self.con.execute(
            "SELECT diagnostic, value FROM business.abroad_diagnostics"
        ).fetchall())

        self.assertIsNone(fact["country"])
        self.assertIsNone(fact["line"])
        self.assertEqual(diagnostics["country_untrusted"], 1)
        self.assertEqual(diagnostics["country_unresolved"], 1)

    def test_raw_grade_evidence_is_resolved_by_sql_and_conflicts_stay_pending(self):
        resolved = _row(
            fact_id="resources:grade-college", resource_id="1001",
            first_channel="市场活动", second_channel="待补证", third_channel="未知",
        )
        conflict = _row(
            fact_id="resources:grade-conflict", resource_id="1002",
            first_channel="市场活动", second_channel="待补证", third_channel="未知",
        )
        unresolved = ("市场活动", None, "unresolved", "market_activity_unmatched")
        config = _config(
            [_mapping(resolved, unresolved), _mapping(conflict, unresolved)],
            grade_policy=[{
                "normalized_l1": "市场活动",
                "maps": {"高校活动": "高校活动", "中学活动": "中学活动"},
            }],
        )
        grade_rows = [
            {"resource_id": "ID: 1001.0", "alternate_resource_id": None,
             "work_order_id": "wo-1", "grade_attr": "本科", "corrected_grade": None,
             "current_grade": None, "grade_name": None},
            {"resource_id": "1002", "alternate_resource_id": None,
             "work_order_id": "wo-2", "grade_attr": "本科", "corrected_grade": "高二",
             "current_grade": None, "grade_name": None},
        ]

        install_abroad(self.con, [resolved, conflict], config, grade_rows=grade_rows)

        facts = {fact["fact_id"]: fact for fact in _fetch_facts(self.con)}
        college = facts["abroad-source:resources:grade-college"]
        conflict_fact = facts["abroad-source:resources:grade-conflict"]
        self.assertEqual((college["second_channel"], college["channel_mapping_rule"]),
                         ("高校活动", "work_order_grade_school_activity"))
        self.assertEqual(conflict_fact["second_channel"], "渠道待确认")
        self.assertEqual(conflict_fact["channel_mapping_status"], "unresolved")

    def test_prebuilt_input_and_grade_views_are_preserved(self):
        row = _row(
            fact_id="resources:parent-views", resource_id="1003",
            first_channel="市场活动", second_channel="待补证", third_channel="未知",
        )
        raw_channel = ("市场活动", None, "unresolved", "market_activity_unmatched")
        config = _config(
            [_mapping(row, raw_channel)],
            grade_policy=[{"normalized_l1": "市场活动", "maps": {"college": "高校活动"}}],
        )
        grade = [{
            "resource_id": "1003", "alternate_resource_id": None, "work_order_id": "wo-3",
            "grade_attr": "本科", "corrected_grade": None,
            "current_grade": None, "grade_name": None,
        }]
        self.con.execute("CREATE SCHEMA business")
        self.con.execute(_inline_view_sql(
            "business.abroad_source_rows", INPUT_COLUMNS, _INPUT_TYPES, [row], required=True,
        ))
        self.con.execute(_inline_view_sql(
            GRADE_INPUT_VIEW,
            ("resource_id", "alternate_resource_id", "work_order_id", "grade_attr",
             "corrected_grade", "current_grade", "grade_name"),
            _GRADE_TYPES, grade, required=True,
        ))

        install_abroad(self.con, None, config)

        fact = _fetch_facts(self.con)[0]
        self.assertEqual(fact["second_channel"], "高校活动")
        self.assertEqual(fact["channel_mapping_rule"], "work_order_grade_school_activity")

    def test_latest_day_resource_identity_conflict_raises(self):
        first = _row(fact_id="resources:conflict-1", event_date="2026-10-10",
                     resource_id="7001", owner="甲")
        second = _row(fact_id="resources:conflict-2", event_date="2026-10-10",
                      resource_id="7001", owner="乙")

        with self.assertRaisesRegex(ValueError, "最新分单日存在身份冲突"):
            install_abroad(self.con, [first, second], _config())

    def test_duplicate_fact_id_with_conflicting_fields_raises(self):
        first = _row(fact_id="resources:same-id", resource_id="7001", owner="甲")
        second = dict(first, owner="乙")

        with self.assertRaisesRegex(ValueError, "重复fact_id身份冲突"):
            install_abroad(self.con, [first, second], _config())

    def test_static_config_compiles_reference_and_confirmed_bridge_rules(self):
        reference = WorkOrderReference(
            {}, {("网络资源-店铺类", "美团点评"): "大众"},
            {"日本": "亚洲条线"}, {}, {},
        )

        config = build_abroad_config(
            bridge=_bridge(), reference=reference, decisions=_decisions(),
        )

        self.assertIn(
            {"source_path": "网络资源-店铺类", "source_third": "美团点评", "target_channel": "大众"},
            config["path_channels"],
        )
        self.assertEqual(config["grade_policy"][0]["normalized_l1"], "市场活动")
        self.assertEqual(config["country_lines"]["日本"], "亚洲条线")

    def test_sql_channel_rules_match_confirmed_legacy_resolver(self):
        bridge = _bridge()
        decisions = _decisions()
        reference = WorkOrderReference(
            {}, {
                ("网络资源-搜索推广乐语", "百度搜索乐语-PC"): "百度",
                ("网络资源-店铺类", "美团点评"): "大众",
            }, {"日本": "亚洲条线"}, {}, {},
        )
        cases = [
            ("线上运营", "搜索推广乐语", "百度搜索乐语-PC"),
            ("新媒体", "其他", "未知"),
            ("官方合作高校", "", ""),
            ("渠道合作", "大客户渠道", "分公司个人代理"),
            ("市场活动", "高校", "个人代理"),
            ("市场活动", "综合展", "信息收集"),
            ("新东方学校推荐", "大学事业部", "点对点"),
            ("校代", "线下校代", ""),
            ("网络资源", "店铺类", "未知平台"),
        ]
        rows = []
        expected = {}
        for index, raw in enumerate(cases):
            row = _row(fact_id=f"resources:channel-{index}", resource_id=str(8000 + index))
            row.update(first_channel=raw[0], second_channel=raw[1], third_channel=raw[2])
            rows.append(row)
            expected[row["fact_id"]] = legacy_channel(*raw, bridge, reference, decisions=decisions)

        config = build_abroad_config(bridge=bridge, reference=reference, decisions=decisions)
        install_abroad(self.con, rows, config)

        actual = _fetch_facts(self.con)
        self.assertEqual(len(actual), len(cases))
        for fact in actual:
            first, second, status, rule = expected[fact["fact_id"].removeprefix("abroad-source:")]
            self.assertEqual(fact["first_channel"], first or "渠道待确认")
            self.assertEqual(fact["second_channel"], second or "渠道待确认")
            self.assertEqual(fact["channel_mapping_status"], status)
            self.assertEqual(fact["channel_mapping_rule"], rule)


if __name__ == "__main__":
    unittest.main()
