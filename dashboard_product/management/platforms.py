"""统一的平台与来源类别归一；只读取传入的渠道标签，不执行 I/O。"""

from __future__ import annotations

import json
import re
from typing import Any


OTHER = "其他线上来源"

ABROAD_PAID_THIRD_CHANNELS = {
    "腾讯广告": ("微信朋友圈", "微信搜索", "微信搜索乐语", "微信小程序", "微信小程序乐语"),
    "抖音": ("抖音", "抖音本地推", "抖音来客", "抖音来客私信"),
    "小红书": ("小红书", "分公司小红书", "小红书付费", "小红书免费", "小红书私信"),
}
ABROAD_PAID_CHANNEL_SEPARATORS = r"[\s_－-]+"
_ABROAD_PAID_BY_THIRD = {label: platform for platform, labels in ABROAD_PAID_THIRD_CHANNELS.items()
                         for label in labels}

_BRANDS = (
    ("闲鱼", ("闲鱼",)),
    ("微信", ("微信", "视频号", "公众号", "官微")),
    ("抖音", ("抖音", "头条", "巨量飞鱼")),
    ("百度", ("百度", "知了好学")),
    ("必应", ("必应",)),
    ("小红书", ("小红书", "kos品专")),
    ("美团/大众点评", ("美团", "大众点评", "大众")),
    ("高德", ("高德",)),
    ("腾讯地图", ("腾讯地图",)),
    ("腾讯广告", ("腾讯广告",)),
    ("知乎", ("知乎",)),
    ("B站", ("b站", "哔哩哔哩")),
    ("搜狗", ("搜狗",)),
)

_SOURCE_CATEGORIES = (
    ("个人渠道", ("个人渠道", "个人代理", "虚拟人", "社群", "自媒体")),
    ("合作推荐", (
        "合作项目", "合作推荐", "对公渠道", "三方平台", "大客户渠道",
        "前途推荐", "新东方学校推荐", "大学事业部",
    )),
    ("市场活动", (
        "市场活动", "综合展", "部门展", "讲座", "公开课", "说明会",
        "招生会", "咨询会", "宣讲", "校园活动", "展会", "活动",
    )),
    ("电话/在线咨询", ("乐语", "在线咨询", "电话咨询", "咨询热线", "电话", "座机", "400")),
    ("官网/自有入口", ("官网", "自有入口", "小程序", "微服务")),
    ("总部电商", ("总部电商",)),
)

_RECORD_KEYS = {
    "third": frozenset({
        "三级渠道", "咨询方式三级渠道", "咨询三级渠道", "渠道三级",
        "third_channel", "channel_level_3", "channel3",
    }),
    "raw_second": frozenset({
        "原始二级渠道", "二级渠道原始值", "raw_second_channel", "raw_second_channel_label",
    }),
    "channel": frozenset({
        "渠道", "渠道名称", "来源渠道", "来源渠道名称", "咨询渠道", "咨询方式渠道",
        "投放渠道", "channel", "channel_name", "source_channel",
    }),
    "second": frozenset({"二级渠道", "second_channel", "channel_level_2", "channel2"}),
    "consultation": frozenset({"咨询方式", "contact_method", "consultation_method"}),
    "first": frozenset({"一级渠道", "first_channel", "channel_level_1", "channel1"}),
}

_CASH_ENRICHMENT_LABELS = frozenset({
    "", "灵蹊", "腾讯广告", "三方平台", "第三方平台", "小表单",
    "暂无归属", "暂未归属", "渠道待确认", "待确认渠道", "暂无渠道",
    "未确认渠道", "未提供", "其他", "其它", "无", "none", "null",
})


def canonical_platform(label: Any) -> str:
    """把一个渠道标签映射到品牌或明确来源类别；未知标签归到其他线上来源。"""
    labels = _channel_labels(label, "label")
    result = _resolve_layers([("label", labels, True, True)])
    return result["platform"]


def classify_business_fact(
    fact: dict[str, Any], order_labels: dict[str, list[str]] | None = None
) -> dict[str, Any]:
    """依据业务线、事实类型和明确渠道字段，将一条事实归入唯一平台/来源桶。"""
    if not isinstance(fact, dict):
        return {"platform": OTHER, "basis": "invalid_fact", "raw_labels": []}

    line = fact.get("business_line")
    metric = fact.get("metric")
    if (not isinstance(line, str) or line not in {"training", "abroad"}
            or not isinstance(metric, str) or metric not in {"orders", "cash"}):
        return {"platform": OTHER, "basis": "unsupported_fact_scope", "raw_labels": []}
    if line == "abroad":
        layers = _abroad_layers(fact)
    else:
        layers = _training_layers(fact, order_labels)

    result = _resolve_layers(layers)
    if line == "abroad":
        # Both acquisition and contracting carry the original third-level detail here.
        label = re.sub(ABROAD_PAID_CHANNEL_SEPARATORS, "", str(fact.get("third_channel") or ""))
        platform = _ABROAD_PAID_BY_THIRD.get(label)
        if platform:
            result = {"platform": platform, "basis": "confirmed_abroad_third_channel"}
        elif result["platform"] in ABROAD_PAID_THIRD_CHANNELS:
            result = {"platform": OTHER, "basis": "unconfirmed_abroad_paid_channel"}
    raw_labels = []
    seen = set()
    for _, labels, _, _ in layers:
        for item in labels:
            value = item["value"]
            if value not in seen:
                seen.add(value)
                raw_labels.append(value)
    return {"platform": result["platform"], "basis": result["basis"], "raw_labels": raw_labels}


def _abroad_layers(fact: dict[str, Any]) -> list[tuple[str, list[dict[str, str]], bool, bool]]:
    record = _source_record(fact)
    third = _channel_labels(fact.get("third_channel"), "fact.third_channel")
    third += _record_group(record, "third")

    raw_second = _channel_labels(fact.get("raw_second_channel"), "fact.raw_second_channel")
    raw_second += _record_group(record, "raw_second")
    raw_second += _record_group(record, "channel")

    second = _channel_labels(fact.get("second_channel"), "fact.second_channel")
    second += _record_group(record, "second")
    first = _channel_labels(fact.get("first_channel"), "fact.first_channel")
    first += _record_group(record, "first")
    return [
        ("abroad.third_channel", third, True, True),
        ("abroad.raw_second_channel", raw_second, True, True),
        ("abroad.second_channel", second, True, True),
        ("abroad.first_channel", first, True, True),
    ]


def _training_layers(
    fact: dict[str, Any], order_labels: dict[str, list[str]] | None
) -> list[tuple[str, list[dict[str, str]], bool, bool]]:
    is_cash = fact["metric"] == "cash"
    source_layers = _training_source_layers(fact, _source_record(fact))
    second = _channel_labels(fact.get("second_channel"), "fact.second_channel")
    first = _channel_labels(fact.get("first_channel"), "fact.first_channel")

    if not is_cash:
        return source_layers + [
            ("training.order.second_channel", second, True, True),
            ("training.order.first_channel", first, True, True),
        ]

    layers = source_layers + [("training.cash.second_channel", second, True, True)]
    second_value = _first_text(fact.get("second_channel"))
    allow_order_labels = _cash_enrichment_allowed(second_value)
    own_labels = [item for _, labels, _, _ in source_layers for item in labels] + second + first
    protected_cooperation = any(
        "合作推荐" in _source_category_matches(item["value"])
        and _normalize(item["value"]) not in _CASH_ENRICHMENT_LABELS
        for item in own_labels
    )
    if allow_order_labels and not protected_cooperation:
        linked = _linked_order_labels(fact.get("work_order_id"), order_labels)
        layers.append(("training.cash.order_labels", linked, True, False))

    # training cash follows its own source row, then normalized second channel and linked order brands.
    # The normalized first channel can provide an explicit source category, but does not override those brand rules.
    layers.append(("training.cash.first_channel", first, False, True))
    return layers


def _training_source_layers(
    fact: dict[str, Any], record: dict[str, Any]
) -> list[tuple[str, list[dict[str, str]], bool, bool]]:
    return [
        ("training.source_record.third_channel",
         _record_group(record, "third") + _channel_labels(fact.get("third_channel"), "fact.third_channel"), True, True),
        ("training.source_record.channel",
         _record_group(record, "channel") + _channel_labels(fact.get("channel"), "fact.channel"), True, True),
        ("training.source_record.raw_second_channel",
         _record_group(record, "raw_second") + _channel_labels(fact.get("raw_second_channel"), "fact.raw_second_channel"), True, True),
        ("training.source_record.second_channel", _record_group(record, "second"), True, True),
        ("training.source_record.consultation", _record_group(record, "consultation"), True, True),
        ("training.source_record.first_channel", _record_group(record, "first"), True, True),
    ]


def _resolve_layers(
    layers: list[tuple[str, list[dict[str, str]], bool, bool]]
) -> dict[str, str]:
    fallback = None
    tencent_ad_candidate = None
    first_layer_with_labels = None
    for name, labels, include_brands, include_categories in layers:
        if labels and first_layer_with_labels is None:
            first_layer_with_labels = name
        classified = _classify_layer(name, labels, include_brands, include_categories)
        if classified is None:
            continue
        if classified["kind"] == "conflict":
            if "conflicting_platform_brands" in classified["basis"] or fallback is None:
                return classified
            continue
        if classified["kind"] == "brand":
            if classified["platform"] == "腾讯广告":
                if tencent_ad_candidate is None:
                    tencent_ad_candidate = classified
                continue
            # A concrete WeChat label outranks the broader Tencent ad type, including across channel levels.
            return classified
        if fallback is None and classified["kind"] == "category":
            fallback = classified

    if tencent_ad_candidate is not None:
        return tencent_ad_candidate
    if fallback is not None:
        return fallback
    basis = "no_channel_labels" if first_layer_with_labels is None else f"{first_layer_with_labels}:unmatched_channel_label"
    return {"platform": OTHER, "basis": basis, "kind": "other"}


def _classify_layer(
    layer: str, labels: list[dict[str, str]], include_brands: bool, include_categories: bool
) -> dict[str, str] | None:
    if not labels:
        return None

    brand_matches: set[str] = set()
    brand_sources: dict[str, list[str]] = {}
    if include_brands:
        for item in labels:
            for brand in _brand_matches(item["value"]):
                brand_matches.add(brand)
                brand_sources.setdefault(brand, []).append(item["source"])
    if brand_matches:
        if brand_matches == {"腾讯广告", "微信"}:
            return {
                "platform": "微信",
                "basis": f"{layer}:wechat_over_tencent_ads",
                "kind": "brand",
            }
        if len(brand_matches) > 1:
            return {
                "platform": OTHER,
                "basis": f"{layer}:conflicting_platform_brands",
                "kind": "conflict",
            }
        brand = next(iter(brand_matches))
        sources = ",".join(dict.fromkeys(brand_sources[brand]))
        return {"platform": brand, "basis": f"{layer}:brand:{sources}", "kind": "brand"}

    if include_categories:
        categories: set[str] = set()
        for item in labels:
            categories.update(_source_category_matches(item["value"]))
        if "电话/在线咨询" in categories:
            return {"platform": "电话/在线咨询", "basis": f"{layer}:explicit_category", "kind": "category"}
        if len(categories) > 1:
            return {
                "platform": OTHER,
                "basis": f"{layer}:conflicting_source_categories",
                "kind": "conflict",
            }
        if categories:
            category = next(iter(categories))
            return {"platform": category, "basis": f"{layer}:explicit_category", "kind": "category"}
    return None


def _brand_matches(value: str) -> set[str]:
    normalized = _normalize(value)
    return {
        platform
        for platform, aliases in _BRANDS
        if any(_contains_alias(normalized, alias) for alias in aliases)
    }


def _source_category_matches(value: str) -> set[str]:
    normalized = _normalize(value)
    matches = {
        category
        for category, aliases in _SOURCE_CATEGORIES
        if any(_contains_alias(normalized, alias) for alias in aliases)
    }
    if re.search(r"(?<![a-z0-9])app(?![a-z0-9])", normalized):
        matches.add("官网/自有入口")
    return matches


def _contains_alias(normalized: str, alias: str) -> bool:
    if alias == "app":
        return bool(re.search(r"(?<![a-z0-9])app(?![a-z0-9])", normalized))
    return alias.casefold() in normalized


def _source_record(fact: dict[str, Any]) -> dict[str, Any]:
    return _as_record(fact.get("source_record"))


def _as_record(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _record_group(
    record: dict[str, Any], group: str
) -> list[dict[str, str]]:
    keys = {_normalize_key(key) for key in _RECORD_KEYS[group]}
    labels = []
    for key, value in record.items():
        if isinstance(key, str) and _normalize_key(key) in keys:
            labels.extend(_channel_labels(value, f"source_record.{key}"))
    return labels


def _linked_order_labels(work_order_id: Any, order_labels: dict[str, list[str]] | None) -> list[dict[str, str]]:
    if not isinstance(order_labels, dict) or not isinstance(work_order_id, str) or not work_order_id.strip():
        return []
    return _channel_labels(order_labels.get(work_order_id.strip()), "order_labels")


def _cash_enrichment_allowed(second_channel: str) -> bool:
    return _normalize(second_channel) in _CASH_ENRICHMENT_LABELS


def _channel_labels(value: Any, source: str) -> list[dict[str, str]]:
    if isinstance(value, str):
        text = value.strip()
        return [{"value": text, "source": source}] if text else []
    if isinstance(value, list):
        labels = []
        for item in value:
            if isinstance(item, str) and item.strip():
                labels.append({"value": item.strip(), "source": source})
        return labels
    return []


def _first_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _normalize_key(value: str) -> str:
    return re.sub(r"[\s_-]+", "", value).casefold()
