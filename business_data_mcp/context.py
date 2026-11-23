"""Read explicitly provisioned, business-approved context documents."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .query import BusinessDataMCPError

SOURCES = {
    "bridge": {
        "file": "bridge.json",
        "name": "已确认 Company Bridge",
        "scope": "语培字段与公司确认规则；留学旧 BI 归因规则只适用于工单归因及明确标注的历史复算。",
    },
    "dashboard": {
        "file": "dashboard.md",
        "name": "看板现行业务口径",
        "scope": "经营、人员、留学及费用的看板口径；仅凭 MCP 已开放的五张明细表不能完整复算所有指标。",
    },
    "study_scorecard": {
        "file": "study_scorecard.md",
        "name": "留学官方记分卡及适用限制",
        "scope": "仅覆盖记分卡列明的留学线上、线下指标和财年；覆盖范围内优先于数仓，未覆盖指标使用受控查询。",
    },
}


def describe_business_context() -> dict[str, Any]:
    return {"schema_version": "business_data_mcp.v1", "status": "passed", "sources": [
        {"source_id": key, "name": item["name"], "scope": item["scope"]}
        for key, item in SOURCES.items()
    ], "limitation": "当前 query_data 仅开放 describe_data 所列五张明细表；费用、人员等依赖不在五张明细表内；优先通过 read_dashboard_data 查询正式看板结果，缺少依赖时不得声称复现看板。"}


def read_business_context(root: Path | None, source_id: str) -> dict[str, Any]:
    if source_id not in SOURCES:
        raise BusinessDataMCPError("CONTEXT_NOT_FOUND", "Unknown context source.")
    if root is None:
        raise BusinessDataMCPError("CONTEXT_UNAVAILABLE", "Business context is not configured.")
    source = SOURCES[source_id]
    try:
        raw = (root / source["file"]).read_text(encoding="utf-8")
        if source_id == "bridge":
            bridge = json.loads(raw)
            if bridge.get("schema_version") != "company_bridge.v1":
                raise ValueError("Invalid Bridge")
            # Never promote unconfirmed mappings to company facts.
            content = {key: value for key, value in bridge.items() if key != "unresolved"}
            for key, value in content.items():
                if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
                    content[key] = [item for item in value if item.get("status") == "confirmed"]
        else:
            content = raw
        if not content:
            raise ValueError("Empty source")
    except (OSError, UnicodeError, ValueError, AttributeError) as exc:
        raise BusinessDataMCPError("CONTEXT_UNAVAILABLE", "Business context is unavailable.") from exc
    manifest_path = root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BusinessDataMCPError("CONTEXT_UNAVAILABLE", "Business context manifest is unavailable.") from exc
    return {"schema_version": "business_data_mcp.v1", "status": "passed", "source_id": source_id,
            "name": source["name"], "scope": source["scope"], "bundle": manifest, "content": content}


def read_release_business_context(current_path: Path, root: Path | None, source_id: str) -> dict[str, Any]:
    """Read context from the active release, or an explicitly deployed matching legacy bundle."""
    from data_platform.sql_release_query import SqlWarehouseRelease
    from .query import resolve_current

    if source_id not in SOURCES:
        raise BusinessDataMCPError("CONTEXT_NOT_FOUND", "Unknown context source.")
    release = resolve_current(current_path)
    if not isinstance(release, SqlWarehouseRelease):
        raise BusinessDataMCPError("CONTEXT_UNAVAILABLE", "A SQL release is required.")
    expected = release.manifest.get("semantics", {}).get("Work/Bridge/reference.json")
    if not isinstance(expected, str):
        raise BusinessDataMCPError("CONTEXT_UNAVAILABLE", "Release Bridge identity is unavailable.")
    bundle = release.manifest.get("business_context")
    if bundle is None:
        result = read_business_context(root, source_id)
        bundle_manifest = result.get("bundle")
        if not isinstance(bundle_manifest, dict) or bundle_manifest.get("source_sha256", {}).get("bridge") != expected:
            raise BusinessDataMCPError("CONTEXT_UNAVAILABLE", "Context Bridge does not match release.")
        result["release"] = release.release
        return result
    if (not isinstance(bundle, dict) or not isinstance(bundle.get("manifest"), dict)
            or bundle["manifest"].get("source_sha256", {}).get("bridge") != expected
            or not bundle.get(source_id)):
        raise BusinessDataMCPError("CONTEXT_UNAVAILABLE", "Release business context is invalid.")
    source = SOURCES[source_id]
    return {"schema_version": "business_data_mcp.v1", "status": "passed", "source_id": source_id,
            "name": source["name"], "scope": source["scope"], "bundle": bundle["manifest"],
            "content": bundle[source_id], "release": release.release}
