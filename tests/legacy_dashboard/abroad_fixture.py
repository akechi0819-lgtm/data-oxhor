COMPANY_ID = "company_study_facts_test"

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
