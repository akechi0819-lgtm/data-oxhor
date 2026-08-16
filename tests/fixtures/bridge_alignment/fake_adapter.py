from __future__ import annotations

from typing import Any


class FakeAdapter:
    def propose(self, model_input: dict[str, Any]) -> dict[str, Any]:
        relation = next(
            item for item in model_input["profile"]["relations"]
            if item["sheet_name"] == "资金流水"
        )
        labels = {
            label["label"]: label["column"]
            for candidate in relation["header_candidates"]
            for label in candidate["labels"]
        }
        relation_name = relation["relation"]
        evidence = [{"locator": f"snapshot/{relation_name}#header", "summary": "资金流水表头与样本行提供字段证据。"}]
        if model_input["profile"]["supplemental_evidence"]:
            evidence.append({"locator": "supplement/字段说明.md", "summary": "补充数据字典说明净额字段包含退款。"})
        date_proposal = {
            "source_id": relation["source_id"],
            "relation": relation_name,
            "field_name": labels["发生时间"],
            "target_type": "dimension",
            "target_id": "time.cash_transaction_date",
            "mapping_role": "confirmed_date_role",
        }
        amount_proposal = {
            "source_id": relation["source_id"],
            "relation": relation_name,
            "field_name": labels["交易净额"],
            "target_type": "concept",
            "target_id": "cash.net_cash",
            "mapping_role": "signed_net_cash",
        }
        return {
            "schema_version": "bridge_alignment_model_candidates.v1",
            "candidates": [
                {
                    "candidate_type": "field_mapping",
                    "proposed_mapping_or_rule": date_proposal,
                    "target": {"target_type": "dimension", "target_id": "time.cash_transaction_date"},
                    "confidence": 0.68,
                    "evidence": evidence,
                    "alternative_explanations": ["也可能是记账日期而非到账日期。"],
                    "must_ask": True,
                    "criticality": "critical",
                    "capability_id": "cash.period_analysis",
                    "question": "资金流水的“发生时间”应作为实际收款日期吗？",
                    "answer_options": [
                        {"option_id": "actual_cash_date", "label": "是，作为实际收款日期", "resulting_status": "confirmed", "proposal": date_proposal},
                        {"option_id": "date_unresolved", "label": "暂不确认日期角色", "resulting_status": "unresolved", "proposal": date_proposal},
                    ],
                },
                {
                    "candidate_type": "field_mapping",
                    "proposed_mapping_or_rule": amount_proposal,
                    "target": {"target_type": "concept", "target_id": "cash.net_cash"},
                    "confidence": 0.72,
                    "evidence": evidence,
                    "alternative_explanations": ["可能只包含收款，不包含退款。"],
                    "must_ask": True,
                    "criticality": "critical",
                    "capability_id": "cash.net_cash",
                    "question": "“交易净额”是否按有符号金额表示净现金，退款为负数？",
                    "answer_options": [
                        {"option_id": "signed_net_cash", "label": "是，保留正负号作为净现金", "resulting_status": "confirmed", "proposal": amount_proposal},
                        {"option_id": "amount_unresolved", "label": "暂不确认金额口径", "resulting_status": "unresolved", "proposal": amount_proposal},
                    ],
                },
            ],
        }
