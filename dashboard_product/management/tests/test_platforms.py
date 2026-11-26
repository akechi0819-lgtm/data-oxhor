import unittest

from dashboard_product.management.platforms import (
    OTHER,
    canonical_platform,
    classify_business_fact,
)


class CanonicalPlatformTests(unittest.TestCase):
    def test_supported_strong_brands_and_explicit_aliases(self):
        expected = {
            "闲鱼": "闲鱼",
            "分公司微信公众号": "微信",
            "视频号直播": "微信",
            "公众号": "微信",
            "官微": "微信",
            "抖音信息流": "抖音",
            "今日头条": "抖音",
            "巨量飞鱼": "抖音",
            "知了好学": "百度",
            "百度搜索": "百度",
            "必应品专": "必应",
            "小红书KOS品专": "小红书",
            "美团": "美团/大众点评",
            "大众点评": "美团/大众点评",
            "大众": "美团/大众点评",
            "高德地图": "高德",
            "腾讯地图": "腾讯地图",
            "腾讯广告": "腾讯广告",
            "知乎": "知乎",
            "B站": "B站",
            "哔哩哔哩": "B站",
            "搜狗搜索": "搜狗",
        }
        for label, platform in expected.items():
            with self.subTest(label=label):
                self.assertEqual(canonical_platform(label), platform)

    def test_strong_brand_wins_over_consultation_and_owned_entry_terms(self):
        self.assertEqual(canonical_platform("微信搜索乐语"), "微信")
        self.assertEqual(canonical_platform("百度搜索乐语"), "百度")
        self.assertEqual(canonical_platform("必应品专乐语"), "必应")
        self.assertEqual(canonical_platform("微信小程序"), "微信")
        self.assertEqual(canonical_platform("腾讯广告微信公众号"), "微信")

    def test_phone_consultation_overrides_owned_entry_tool_labels(self):
        for label in ("PC官网乐语", "移动端官网乐语", "新东方APP乐语"):
            with self.subTest(label=label):
                self.assertEqual(canonical_platform(label), "电话/在线咨询")
        self.assertEqual(canonical_platform("合作项目乐语"), "电话/在线咨询")
        self.assertEqual(canonical_platform("微信合作项目乐语"), "微信")

    def test_conflicting_brands_and_unknown_labels_do_not_guess(self):
        self.assertEqual(canonical_platform("小红书+微信"), OTHER)
        self.assertEqual(canonical_platform("腾讯广告+腾讯地图"), OTHER)
        self.assertEqual(canonical_platform("灵蹊"), OTHER)
        self.assertEqual(canonical_platform("未识别推广渠道"), OTHER)

    def test_explicit_nonbrand_source_categories(self):
        expected = {
            "个人代理": "个人渠道",
            "虚拟人": "个人渠道",
            "社群自媒体": "个人渠道",
            "合作项目": "合作推荐",
            "对公渠道": "合作推荐",
            "新东方学校推荐": "合作推荐",
            "大学事业部": "合作推荐",
            "综合展": "市场活动",
            "高中讲座": "市场活动",
            "市场活动": "市场活动",
            "乐语咨询": "电话/在线咨询",
            "400电话": "电话/在线咨询",
            "在线咨询": "电话/在线咨询",
            "官网": "官网/自有入口",
            "小程序": "官网/自有入口",
            "APP": "官网/自有入口",
            "微服务": "官网/自有入口",
            "总部电商": "总部电商",
            "SSC": OTHER,
        }
        for label, platform in expected.items():
            with self.subTest(label=label):
                self.assertEqual(canonical_platform(label), platform)


class ClassifyBusinessFactTests(unittest.TestCase):
    def test_abroad_recovers_parent_platform_after_generic_third_channel(self):
        result = classify_business_fact({
            "business_line": "abroad",
            "metric": "orders",
            "third_channel": "虚拟人",
            "raw_second_channel": "分公司微信公众号",
            "second_channel": "个人渠道",
            "first_channel": "市场活动",
            "work_order_id": "ORDER-PRIVATE-1",
            "customer_name": "示例客户",
            "campaign_name": "百度推广活动",
            "resource_description": "抖音转化描述",
        })

        self.assertEqual(result["platform"], "微信")
        self.assertIn("abroad.raw_second_channel", result["basis"])
        self.assertEqual(result["raw_labels"], [
            "虚拟人", "分公司微信公众号", "个人渠道", "市场活动",
        ])
        self.assertEqual(len(result), 3)
        self.assertTrue(all(isinstance(label, str) for label in result["raw_labels"]))
        self.assertNotIn("示例客户", result["raw_labels"])
        self.assertNotIn("ORDER-PRIVATE-1", result["raw_labels"])
        self.assertNotIn("百度推广活动", result["raw_labels"])
        self.assertNotIn("抖音转化描述", result["raw_labels"])

    def test_abroad_specific_third_channel_wins_over_parent_category(self):
        result = classify_business_fact({
            "business_line": "abroad",
            "metric": "orders",
            "third_channel": "闲鱼",
            "raw_second_channel": "个人渠道",
            "second_channel": "合作推荐",
            "first_channel": "市场活动",
        })
        self.assertEqual(result["platform"], "闲鱼")
        self.assertIn("abroad.third_channel", result["basis"])

    def test_abroad_brand_beats_generic_category_and_same_level_conflict_is_explicit(self):
        recovered = classify_business_fact({
            "business_line": "abroad",
            "metric": "orders",
            "third_channel": "虚拟人",
            "raw_second_channel": "百度搜索",
            "second_channel": "个人渠道",
        })
        self.assertEqual(recovered["platform"], "百度")

        conflict = classify_business_fact({
            "business_line": "abroad",
            "metric": "orders",
            "third_channel": "小红书/微信",
            "raw_second_channel": "百度",
        })
        self.assertEqual(conflict["platform"], OTHER)
        self.assertIn("conflicting_platform_brands", conflict["basis"])

    def test_abroad_source_record_second_channel_stays_below_raw_second_channel(self):
        result = classify_business_fact({
            "business_line": "abroad",
            "metric": "orders",
            "third_channel": "虚拟人",
            "raw_second_channel": "个人渠道",
            "second_channel": "合作推荐",
            "source_record": {"二级渠道": "分公司微信公众号"},
        })
        self.assertEqual(result["platform"], "微信")
        self.assertIn("abroad.second_channel", result["basis"])

    def test_training_order_uses_explicit_source_record_channel_fields(self):
        result = classify_business_fact({
            "business_line": "training",
            "metric": "orders",
            "source_record": {
                "咨询方式三级渠道": "闲鱼",
                "活动名称": "微信活动",
                "资源描述": "百度线索",
                "客户ID": "ORDER-PRIVATE-2",
            },
            "second_channel": "微信",
            "first_channel": "抖音",
            "campaign_name": "小红书推广",
        })
        self.assertEqual(result["platform"], "闲鱼")
        self.assertIn("training.source_record", result["basis"])
        self.assertEqual(result["raw_labels"], ["闲鱼", "微信", "抖音"])

    def test_training_order_generic_source_record_does_not_hide_normalized_brand(self):
        result = classify_business_fact({
            "business_line": "training",
            "metric": "orders",
            "source_record": {
                "三级渠道": "虚拟人",
                "活动名称": "百度活动",
                "资源描述": "小红书咨询",
            },
            "second_channel": "分公司微信公众号",
            "first_channel": "个人渠道",
        })
        self.assertEqual(result["platform"], "微信")
        self.assertIn("training.order.second_channel", result["basis"])
        self.assertNotIn("百度活动", result["raw_labels"])
        self.assertNotIn("小红书咨询", result["raw_labels"])

    def test_training_cash_uses_its_own_source_brand_first(self):
        result = classify_business_fact({
            "business_line": "training",
            "metric": "cash",
            "work_order_id": "ORDER-PRIVATE-3",
            "source_record": {
                "渠道": "小红书",
                "活动名称": "微信活动",
                "资源描述": "百度咨询",
            },
            "second_channel": "微信",
            "first_channel": "抖音",
        }, {"ORDER-PRIVATE-3": ["百度"]})
        self.assertEqual(result["platform"], "小红书")
        self.assertIn("training.source_record", result["basis"])
        self.assertEqual(result["raw_labels"], ["小红书", "微信", "抖音"])

    def test_training_source_record_brand_conflict_within_channel_layer_is_explicit(self):
        result = classify_business_fact({
            "business_line": "training",
            "metric": "orders",
            "source_record": {"渠道": "小红书", "渠道名称": "微信公众号"},
            "second_channel": "百度",
        })
        self.assertEqual(result["platform"], OTHER)
        self.assertIn("conflicting_platform_brands", result["basis"])

    def test_training_raw_channel_field_precedes_source_record_second_and_normalized_second(self):
        result = classify_business_fact({
            "business_line": "training",
            "metric": "orders",
            "source_record": {"渠道": "虚拟人", "二级渠道": "市场活动"},
            "second_channel": "市场活动",
            "first_channel": "合作推荐",
        })
        self.assertEqual(result["platform"], "个人渠道")
        self.assertIn("training.source_record.channel", result["basis"])

    def test_more_specific_phone_category_survives_lower_composite_category(self):
        result = classify_business_fact({
            "business_line": "abroad",
            "metric": "orders",
            "third_channel": "电话",
            "raw_second_channel": "合作项目乐语",
            "second_channel": "合作推荐",
        })
        self.assertEqual(result["platform"], "电话/在线咨询")
        self.assertIn("abroad.third_channel", result["basis"])

    def test_training_cash_enriches_only_generic_second_channel_from_linked_order(self):
        examples = (
            ("灵蹊", ["分公司微信公众号"], "微信"),
            ("腾讯广告", ["微信搜索乐语"], "微信"),
            ("三方平台", ["百度"], "百度"),
            ("小表单", ["必应"], "必应"),
            ("暂无归属", ["闲鱼"], "闲鱼"),
            ("渠道待确认", ["小红书"], "小红书"),
            ("", ["高德"], "高德"),
        )
        for second, linked_labels, expected in examples:
            with self.subTest(second=second, expected=expected):
                result = classify_business_fact({
                    "business_line": "training",
                    "metric": "cash",
                    "work_order_id": "ORDER-1",
                    "second_channel": second,
                }, {"ORDER-1": linked_labels})
                self.assertEqual(result["platform"], expected)
                self.assertIn("training.cash.order_labels", result["basis"])
                self.assertIn(linked_labels[0], result["raw_labels"])

    def test_training_cash_keeps_explicit_nonplatform_cooperation_out_of_linked_brand(self):
        linked = {"ORDER-2": ["分公司微信公众号"]}
        for second in ("前途推荐", "合作推荐"):
            with self.subTest(second=second):
                result = classify_business_fact({
                    "business_line": "training",
                    "metric": "cash",
                    "work_order_id": "ORDER-2",
                    "second_channel": second,
                }, linked)
                self.assertEqual(result["platform"], "合作推荐")
                self.assertNotIn("training.cash.order_labels", result["basis"])
                self.assertNotIn("分公司微信公众号", result["raw_labels"])

        source_record_result = classify_business_fact({
            "business_line": "training",
            "metric": "cash",
            "work_order_id": "ORDER-2",
            "source_record": {"渠道": "合作推荐"},
            "second_channel": "暂无归属",
        }, linked)
        self.assertEqual(source_record_result["platform"], "合作推荐")
        self.assertNotIn("training.cash.order_labels", source_record_result["basis"])

    def test_training_cash_explicit_normalized_brand_is_not_replaced_by_linked_brand(self):
        result = classify_business_fact({
            "business_line": "training",
            "metric": "cash",
            "work_order_id": "ORDER-3",
            "second_channel": "百度",
        }, {"ORDER-3": ["微信"]})
        self.assertEqual(result["platform"], "百度")
        self.assertNotIn("training.cash.order_labels", result["basis"])
        self.assertNotIn("微信", result["raw_labels"])

    def test_cash_tencent_ad_type_stays_distinct_without_linked_brand(self):
        result = classify_business_fact({
            "business_line": "training", "metric": "cash", "second_channel": "腾讯广告",
        })
        self.assertEqual(result["platform"], "腾讯广告")

    def test_fees_and_facts_share_the_same_channel_mapping_and_one_bucket(self):
        label = "分公司微信公众号"
        business = classify_business_fact({
            "business_line": "abroad", "metric": "orders",
            "third_channel": "虚拟人", "raw_second_channel": label,
        })
        self.assertEqual(canonical_platform(label), business["platform"])
        self.assertIsInstance(business["platform"], str)

    def test_unknown_source_stays_other_and_ignores_campaign_and_description_text(self):
        result = classify_business_fact({
            "business_line": "training",
            "metric": "orders",
            "work_order_id": "ID-PRIVATE-4",
            "second_channel": "灵蹊",
            "campaign_name": "微信推广活动",
            "resource_description": "百度小红书咨询",
            "source_record": {
                "活动名称": "抖音投放",
                "资源描述": "闲鱼流量",
                "客户姓名": "不应进入渠道标签",
                "工单ID": "ID-PRIVATE-4",
            },
        })
        self.assertEqual(result["platform"], OTHER)
        self.assertNotIn("campaign_name", result["raw_labels"])
        self.assertNotIn("微信推广活动", result["raw_labels"])
        self.assertNotIn("百度小红书咨询", result["raw_labels"])
        self.assertNotIn("不应进入渠道标签", result["raw_labels"])
        self.assertNotIn("ID-PRIVATE-4", result["raw_labels"])


if __name__ == "__main__":
    unittest.main()
