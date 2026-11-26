"""Confirmed channel semantics for study-abroad management segments."""
from __future__ import annotations

from collections import Counter
import unittest

from data_acquisition.jobs.work_order_cleaning import WorkOrderReference
from tests.legacy_dashboard.abroad_facts import _make_fact
from tests.legacy_dashboard.abroad_fixture import _fact_row


SOURCE_SHA256 = "a" * 64
REFERENCE = WorkOrderReference({}, {}, {"日本": "亚洲条线"}, {}, {})


def _make(row, channel):
    return _make_fact(row, channel, Counter(), REFERENCE)


class StudyAbroadChannelSegmentTests(unittest.TestCase):
    def test_normalized_network_resources_and_unmatched_platforms_are_online(self):
        cases = [
            ("百度", "网络资源", "搜索推广乐语", "百度搜索乐语-移动",
             ("网络资源", "百度", "matched_existing", "online_reference_exact")),
            ("抖音", "网络资源", "信息流", "抖音",
             ("网络资源", "抖音", "matched_existing", "online_reference_exact")),
            ("头条", "网络资源", "信息流", "今日头条",
             ("网络资源", "头条", "matched_existing", "online_reference_exact")),
            ("美团点评", "网络资源", "店铺类", "美团点评",
             ("网络资源", "大众", "matched_existing", "online_reference_exact")),
            ("其他平台投放", "线上运营", "网络投放", "其他平台投放",
             ("网络资源", None, "unresolved", "online_reference_unmatched")),
            ("知了好学", "线上运营", "本地生活平台", "知了好学",
             ("网络资源", None, "unresolved", "online_reference_unmatched")),
        ]
        for index, (label, raw_first, raw_second, third, channel) in enumerate(cases):
            with self.subTest(channel=label):
                row = _fact_row(
                    fact_type="resource", fact_id=f"resources:platform-{index}",
                    business_line="study_abroad", event_date="2026-10-15",
                    segment_id="study_abroad_offline", resource_id=f"R-{index}",
                    owner="平台事实归属甲", first_channel=raw_first,
                    second_channel=raw_second, third_channel=third,
                    source_sha256=SOURCE_SHA256,
                )

                fact = _make(row, channel)

                self.assertEqual(fact["segment_id"], "study_abroad_online")
                self.assertEqual(fact["team_id"], "online_platform")
                self.assertEqual(fact["acquisition_mode"], "online")
                self.assertFalse(fact["offline_channel_eligible"])
                self.assertEqual(fact["first_channel"], "网络资源")
                self.assertEqual(fact["second_channel"], channel[1] or "渠道待确认")
                self.assertEqual(fact["raw_first_channel"], raw_first)
                self.assertEqual(fact["raw_second_channel"], raw_second)
                self.assertEqual(fact["third_channel"], third)
                self.assertEqual(fact["owners"], ["平台事实归属甲"])
                self.assertEqual(fact["owner"], "平台事实归属甲")
                self.assertEqual(fact["resource_id"], f"R-{index}")
                self.assertTrue(fact["team_eligible"])
                self.assertTrue(fact["market_eligible"])
                self.assertTrue(fact["counts_toward_completion"])

    def test_virtual_human_channel_precedes_ssc_and_platform(self):
        row = _fact_row(
            fact_type="resource", fact_id="resources:virtual-human",
            business_line="study_abroad", event_date="2026-08-12",
            segment_id="study_abroad_offline", resource_id="187536287",
            owner="虚拟人事实归属甲", first_channel="新媒体",
            second_channel="欧亚总部在线", third_channel="虚拟人",
            source_sha256=SOURCE_SHA256,
        )

        fact = _make(row, ("网络资源", "SSC", "matched_existing", "fixture"))

        self.assertEqual(fact["segment_id"], "study_abroad_virtual")
        self.assertEqual(fact["team_id"], "online_private")
        self.assertEqual(fact["acquisition_mode"], "online")
        self.assertFalse(fact["offline_channel_eligible"])
        self.assertEqual(fact["owners"], ["虚拟人事实归属甲"])
        self.assertEqual(fact["owner"], "虚拟人事实归属甲")
        self.assertEqual(fact["raw_first_channel"], "新媒体")
        self.assertEqual(fact["raw_second_channel"], "欧亚总部在线")
        self.assertEqual(fact["third_channel"], "虚拟人")
        self.assertTrue(fact["counts_toward_completion"])

    def test_confirmed_eurasia_headquarters_online_is_ssc(self):
        row = _fact_row(
            fact_type="resource", fact_id="resources:eurasia-ssc",
            business_line="small_language", event_date="2026-10-13",
            segment_id="study_abroad_offline", resource_id="198915904",
            owner="SSC事实归属甲", first_channel="新媒体",
            second_channel="欧亚总部在线", third_channel="知乎-付费",
            source_sha256=SOURCE_SHA256,
        )

        fact = _make(row, ("新媒体", "SSC", "matched_existing", "online_reference_exact"))

        self.assertEqual(fact["segment_id"], "ssc")
        self.assertIsNone(fact["team_id"])
        self.assertEqual(fact["acquisition_mode"], "supplemental")
        self.assertFalse(fact["offline_channel_eligible"])
        self.assertEqual(fact["owners"], ["SSC事实归属甲"])
        self.assertEqual(fact["owner"], "SSC事实归属甲")
        self.assertEqual(fact["first_channel"], "新媒体")
        self.assertEqual(fact["second_channel"], "SSC")
        self.assertTrue(fact["counts_toward_completion"])

    def test_positive_signature_keeps_amount_and_eligibility_after_online_correction(self):
        row = _fact_row(
            fact_type="signature", fact_id="contracts:positive-online",
            business_line="study_abroad", event_date="2026-09-20",
            segment_id="study_abroad_offline", resource_id="R-SIGN",
            owner="签约事实归属乙", first_channel="网络资源",
            second_channel="信息流", third_channel="百度搜索-移动",
            source_sha256=SOURCE_SHA256, contract_id="C-200",
            customer_key="study_abroad:U-200", gross_signing_amount="1250.75",
            positive_signature=True,
        )

        fact = _make(row, ("网络资源", "百度", "matched_existing", "online_reference_exact"))

        self.assertEqual(fact["metric"], "cash")
        self.assertEqual(fact["value"], 1250.75)
        self.assertEqual(fact["segment_id"], "study_abroad_online")
        self.assertEqual(fact["team_id"], "online_platform")
        self.assertEqual(fact["fact_id"], "abroad-source:contracts:positive-online")
        self.assertEqual(fact["resource_id"], "R-SIGN")
        self.assertEqual(fact["contract_id"], "C-200")
        self.assertEqual(fact["customer_key"], "study_abroad:U-200")
        self.assertEqual(fact["owner"], "签约事实归属乙")
        self.assertEqual(fact["owners"], ["签约事实归属乙"])
        self.assertTrue(fact["counts_toward_completion"])

    def test_deleted_resource_completion_flag_survives_online_correction(self):
        row = _fact_row(
            fact_type="resource", fact_id="resources:deleted-online",
            business_line="study_abroad", event_date="2026-10-01",
            segment_id="study_abroad_offline", resource_id="R-DELETED",
            owner="删除资源归属甲", first_channel="网络资源",
            second_channel="搜索推广", third_channel="百度搜索-移动",
            source_sha256=SOURCE_SHA256, resource_status="删除",
        )

        fact = _make(row, ("网络资源", "百度", "matched_existing", "online_reference_exact"))

        self.assertEqual(fact["segment_id"], "study_abroad_online")
        self.assertFalse(fact["counts_toward_completion"])
        self.assertEqual(fact["exclusion_reason"], "resource_status_deleted")

    def test_existing_ssc_international_and_unassigned_segments_stay_isolated(self):
        cases = [
            ("ssc", "新媒体", "欧亚总部在线", "知乎-付费",
             ("网络资源", "百度", "matched_existing", "online_reference_exact")),
            ("international_market", "新媒体", "分公司微信公众号", "虚拟人",
             ("新媒体", "个人渠道", "matched_existing", "online_reference_exact")),
            ("unassigned", "新媒体", "欧亚总部在线", "知乎-付费",
             ("新媒体", "SSC", "matched_existing", "online_reference_exact")),
        ]
        for index, (segment, raw_first, raw_second, third, channel) in enumerate(cases):
            with self.subTest(segment=segment):
                row = _fact_row(
                    fact_type="resource", fact_id=f"resources:isolated-{segment}",
                    business_line="study_abroad", event_date="2026-10-13",
                    segment_id=segment, resource_id=f"R-ISOLATED-{index}",
                    owner="隔离事实归属甲", first_channel=raw_first,
                    second_channel=raw_second, third_channel=third,
                    source_sha256=SOURCE_SHA256,
                )

                fact = _make(row, channel)

                self.assertEqual(fact["segment_id"], segment)
                self.assertIsNone(fact["team_id"])
                self.assertEqual(fact["acquisition_mode"], "supplemental")
                self.assertFalse(fact["offline_channel_eligible"])
                self.assertEqual(fact["owners"], [] if segment == "international_market"
                                 else ["隔离事实归属甲"])
                self.assertTrue(fact["market_eligible"])
                self.assertTrue(fact["counts_toward_completion"])


if __name__ == "__main__":
    unittest.main()
