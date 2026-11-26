"""Independent local warehouse for parsed advertising expense sources."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
from typing import Any

from dashboard_product.management.advertising_sources import MANUAL_ACCOUNT_DAILY, REPORTED_PLATFORM_DAILY
from dashboard_product.management.tencent_sources import TENCENT_MANUAL


SCHEMA = "expenses"


def refresh_from_manifest(connection, manifest, import_id):
    """A fee input failure keeps the last committed expenses and is explicit.

    Business normalization and notification compilation are separate callers;
    neither depends on this refresh succeeding.
    """
    install(connection)
    try:
        costs = parse_manifest(manifest, candidate=False)
        result = replace_sources(connection, costs, import_id)
    except Exception as exc:
        # This is the explicitly independent fee boundary: parser/import errors
        # (including malformed SEM workbooks) must not block new business data.
        # The caller records and displays FAILED; no amount is filled with zero.
        return {'status':'failed','error_type':type(exc).__name__,'error':str(exc),
                'retained_rows':connection.execute('SELECT count(*) FROM expenses.expense_rows').fetchone()[0]}
    return {'status':'updated', **result}


def install(connection) -> None:
    """Create the derived expense tables and source-grain views."""
    connection.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    connection.execute(f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.expense_rows (
            row_key VARCHAR PRIMARY KEY,
            natural_key VARCHAR NOT NULL,
            source_key VARCHAR NOT NULL,
            source_id VARCHAR NOT NULL,
            import_id VARCHAR NOT NULL,
            source_row INTEGER NOT NULL,
            source_sha256 VARCHAR,
            grain VARCHAR NOT NULL,
            business_line VARCHAR,
            business_group VARCHAR,
            platform VARCHAR NOT NULL,
            account_id VARCHAR,
            product_scope VARCHAR,
            source_sheet VARCHAR,
            project_id VARCHAR,
            placement_type VARCHAR,
            marketing_scene VARCHAR,
            company VARCHAR,
            start_date DATE NOT NULL,
            end_date DATE NOT NULL,
            amount DECIMAL(24,2),
            amount_status VARCHAR NOT NULL
        )
    """)
    connection.execute(f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.expense_sources (
            summary_key VARCHAR PRIMARY KEY,
            import_id VARCHAR NOT NULL,
            source_key VARCHAR NOT NULL,
            source_id VARCHAR NOT NULL,
            grain VARCHAR NOT NULL,
            business_line VARCHAR,
            business_group VARCHAR,
            platform VARCHAR NOT NULL,
            account_id VARCHAR,
            product_scope VARCHAR,
            source_sheet VARCHAR,
            source_path VARCHAR,
            source_sha256 VARCHAR,
            start_date DATE,
            end_date DATE,
            row_count BIGINT NOT NULL,
            missing_amount_count BIGINT NOT NULL,
            coverage_state VARCHAR,
            summary_json VARCHAR NOT NULL
        )
    """)
    connection.execute(f"""
        CREATE OR REPLACE VIEW {SCHEMA}.daily_spend AS
        SELECT start_date AS spend_date, source_key, source_id, import_id,
               business_line, business_group, platform, account_id,
               product_scope, source_sheet, project_id, placement_type,
               marketing_scene,
               count(*) AS row_count,
               count(amount) AS reported_amount_count,
               count(*) FILTER (WHERE amount IS NULL) AS missing_amount_count,
               sum(amount) AS spend
        FROM {SCHEMA}.expense_rows
        WHERE grain = 'daily' AND start_date = end_date
        GROUP BY ALL
    """)
    connection.execute(f"""
        CREATE OR REPLACE VIEW {SCHEMA}.updated_dates AS
        SELECT start_date AS updated_date, source_key, source_id, import_id,
               grain, business_line, business_group, platform,
               account_id, product_scope, source_sheet, project_id,
               placement_type, marketing_scene,
               count(*) AS row_count,
               count(*) FILTER (WHERE amount IS NULL) AS missing_amount_count
        FROM {SCHEMA}.expense_rows
        WHERE grain = 'daily' AND start_date = end_date
        GROUP BY ALL
    """)


def parse_manifest(path: str | Path, *, candidate: bool = True,
                   business_scope_confirmation: dict | None = None) -> dict[str, Any]:
    """Parse a fee manifest using the existing authority and source parsers.

    Ocean's stable project key is present in the original export but not in the
    common parsed row. It is recovered by the already-validated source row
    number. The source body itself is never returned or stored in the warehouse.
    """
    manifest_path = Path(path).resolve(strict=True)
    if candidate:
        from dashboard_product.management.candidate_sources import load_candidate_sources
        costs = load_candidate_sources(
            manifest_path, business_scope_confirmation=business_scope_confirmation)
    else:
        from dashboard_product.management.advertising_sources import load_sources
        costs = load_sources(manifest_path)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    entries = manifest["sources"]
    entry_by_id = {entry["source_id"]: entry for entry in entries}
    tables: dict[str, tuple[dict[str, int], list[tuple[Any, ...]]]] = {}
    for entry in entries:
        if entry.get("kind") not in {"ocean_daily", "xhs_daily"}:
            continue
        from dashboard_product.management.advertising_sources import _read_rows
        raw_path = Path(entry["path"])
        raw_path = raw_path if raw_path.is_absolute() else manifest_path.parent / raw_path
        table, _ = _read_rows(raw_path.read_bytes(), raw_path)
        if not table:
            raise ValueError(f"费用来源为空: {entry['source_id']}")
        headers = {str(value).strip(): index for index, value in enumerate(table[0])
                   if value is not None and str(value).strip()}
        tables[entry["source_id"]] = (headers, table)

    for row in costs["rows"]:
        source_id = row["source_id"]
        entry = entry_by_id.get(source_id)
        if entry is None:
            matches = [candidate_entry for candidate_id, candidate_entry in entry_by_id.items()
                       if source_id.startswith(candidate_id + ":")]
            if len(matches) == 1:
                entry = matches[0]
        if entry is None:
            continue
        kind = entry.get("kind")
        if kind not in {"ocean_daily", "xhs_daily"}:
            continue
        headers, table = tables[entry["source_id"]]
        row_number = row["source_row"]
        if type(row_number) is not int or row_number < 2 or row_number > len(table):
            raise ValueError(f"费用来源行号无效: {source_id}/{row_number}")
        cells = table[row_number - 1]

        def cell(name: str):
            index = headers.get(name)
            return None if index is None or index >= len(cells) else cells[index]

        if kind == "ocean_daily":
            from dashboard_product.management.advertising_sources import _daily_duplicate_key
            values = {name: cell(name) for name in ("项目ID", "日期", "投放类型", "营销场景")}
            key = _daily_duplicate_key(values, row["start_date"], Path(entry["path"]), row_number)
            row["project_id"], row["placement_type"], row["marketing_scene"] = key[0], key[2], key[3]
            row["account_id"] = _ocean_account(entry)
        else:
            if not row.get("account_id"):
                account_column = next((name for name in (
                    "广告账户ID", "账户ID", "账号ID", "投放ID", "账户编号", "账号编号"
                ) if name in headers), None)
                if account_column is None:
                    raise ValueError(f"小红书日报缺少稳定账户键: {source_id}")
                row["account_id"] = _identity_text(cell(account_column))
            if not row.get("account_id"):
                raise ValueError(f"小红书日报账户键为空: {source_id}/{row_number}")

    for source in costs["sources"]:
        source_id = source["source_id"]
        entry = entry_by_id.get(source_id)
        if entry is None:
            matches = [candidate_entry for candidate_id, candidate_entry in entry_by_id.items()
                       if source_id.startswith(candidate_id + ":")]
            if len(matches) == 1:
                entry = matches[0]
        if entry is not None:
            source["source_kind"] = entry.get("kind")
            if entry.get("kind") == "ocean_daily":
                source["account_id"] = _ocean_account(entry)
            if entry.get("kind") in {"xhs_mcc_daily", "tencent_native_csv", "sem_daily"}:
                source["requested_start_date"] = entry.get("start_date")
                source["requested_end_date"] = entry.get("end_date")
    return costs


def _ocean_account(entry):
    """Reuse the collector's confirmed account mapping, rejecting ambiguity."""
    from dashboard_product.management.advertising_sources import OCEAN_ACCOUNTS
    if entry.get('account_id'):
        return str(entry['account_id'])
    matches=[a[0] for a in OCEAN_ACCOUNTS if a[1]==entry.get('business_line') and a[2]==entry.get('business_group')]
    if len(matches)>1:
        matches=[a for a in matches if a in entry['source_id']]
    if len(matches)!=1:
        raise ValueError('巨量来源缺少唯一已确认账户身份')
    return matches[0]


def _platform_day(row):
    platform = "腾讯广告" if row["platform"] == "腾讯" else row["platform"]
    return row["business_line"], row["business_group"], platform, row["start_date"]


def replace_sources(connection, costs: dict[str, Any], import_id: str) -> dict[str, int]:
    """Validate then atomically replace rows covered by this parsed batch.

    Rows are keyed by platform-native business identity. Source summaries with
    a complete date window replace that stable identity's covered dates;
    incomplete windows only replace exact natural row keys.
    """
    if not isinstance(import_id, str) or not import_id.strip():
        raise ValueError("import_id must be a non-empty string")
    rows, summaries, scopes = _prepare(costs, import_id.strip())
    install(connection)
    connection.execute("BEGIN TRANSACTION")
    try:
        period_rows = [row for row in rows if row["product_scope"] == TENCENT_MANUAL and row["grain"] == "period"]
        reported_rows = [row for row in rows if row["product_scope"] == REPORTED_PLATFORM_DAILY and row["amount"] is not None]
        for period in period_rows:
            for reported in reported_rows:
                if (period["business_line"] == reported["business_line"]
                        and period["business_group"] == reported["business_group"]
                        and reported["platform"] in {"腾讯广告", "腾讯"}
                        and period["start_date"] <= reported["start_date"] <= period["end_date"]):
                    raise ValueError("群报单日费用与期间累计费用重叠，需核对期间明细")
        for row in rows:
            if row["source_id"].startswith("manual:") and row["product_scope"] != REPORTED_PLATFORM_DAILY:
                conflict = connection.execute(
                    f"SELECT 1 FROM {SCHEMA}.expense_rows WHERE business_line=? AND business_group=? "
                    "AND platform=? AND start_date<=? AND end_date>=? AND source_key<>? LIMIT 1",
                    [row["business_line"], row["business_group"], row["platform"],
                     row["end_date"], row["start_date"], row["source_key"]]).fetchone()
                if conflict:
                    raise ValueError("手工费用与已有同组同平台同日明细冲突，需要确认覆盖口径")
        retained = []
        for row in rows:
            if row["product_scope"] == REPORTED_PLATFORM_DAILY and row["amount"] is None:
                existing = connection.execute(
                    f"SELECT 1 FROM {SCHEMA}.expense_rows WHERE business_line=? AND business_group=? "
                    "AND CASE WHEN platform='腾讯' THEN '腾讯广告' ELSE platform END=? "
                    "AND start_date=? AND grain='daily' AND amount IS NOT NULL LIMIT 1",
                    list(_platform_day(row))).fetchone()
                if existing:
                    continue
            if row["product_scope"] == REPORTED_PLATFORM_DAILY and row["amount"] is not None:
                overlap = connection.execute(
                    f"SELECT 1 FROM {SCHEMA}.expense_rows WHERE business_line=? AND business_group=? "
                    "AND CASE WHEN platform='腾讯' THEN '腾讯广告' ELSE platform END=? "
                    "AND grain='period' AND start_date<=? AND end_date>=? AND amount IS NOT NULL LIMIT 1",
                    [*_platform_day(row), row["start_date"]]).fetchone()
                if overlap:
                    raise ValueError("群报单日费用与已有期间累计费用重叠，需核对期间明细")
            if row["product_scope"] == TENCENT_MANUAL and row["grain"] == "period":
                overlap = connection.execute(
                    f"SELECT 1 FROM {SCHEMA}.expense_rows WHERE business_line=? AND business_group=? "
                    "AND CASE WHEN platform='腾讯' THEN '腾讯广告' ELSE platform END=? "
                    "AND grain='daily' AND product_scope=? AND start_date BETWEEN ? AND ? "
                    "AND amount IS NOT NULL LIMIT 1",
                    [row["business_line"], row["business_group"], "腾讯广告", REPORTED_PLATFORM_DAILY,
                     row["start_date"], row["end_date"]]).fetchone()
                if overlap:
                    raise ValueError("期间累计费用与已有群报单日费用重叠，需核对期间明细")
            retained.append(row)
        rows = retained
        manual_days = {(row["source_key"], row["start_date"]) for row in rows
                       if row["product_scope"] in MANUAL_ACCOUNT_DAILY}
        manual_tencent_days = {(row["account_id"], row["start_date"]) for row in rows
                               if row["product_scope"] == TENCENT_MANUAL and row["grain"] == "daily"}
        manual_kinds = sorted([*MANUAL_ACCOUNT_DAILY, TENCENT_MANUAL, REPORTED_PLATFORM_DAILY])
        reported_days = {_platform_day(row) for row in rows
                         if row["product_scope"] == REPORTED_PLATFORM_DAILY and row["amount"] is not None}
        protected_platform_days = reported_days | set(connection.execute(
            f"SELECT business_line,business_group,platform,start_date FROM {SCHEMA}.expense_rows "
            "WHERE product_scope=? AND amount IS NOT NULL",
            [REPORTED_PLATFORM_DAILY]).fetchall())
        protected_days = set(connection.execute(
            f"SELECT source_key,start_date FROM {SCHEMA}.expense_rows WHERE product_scope IN ?",
            [sorted(MANUAL_ACCOUNT_DAILY)]).fetchall()) | manual_days
        protected_tencent_days = set(connection.execute(
            f"SELECT account_id,start_date FROM {SCHEMA}.expense_rows WHERE product_scope=? AND grain='daily'",
            [TENCENT_MANUAL]).fetchall()) | manual_tencent_days
        rows = [row for row in rows if row["product_scope"] in manual_kinds or (
            (row["source_key"], row["start_date"]) not in protected_days
            and (row["platform"] not in {"腾讯广告", "腾讯"}
                 or (row["account_id"], row["start_date"]) not in protected_tencent_days))]
        rows = [row for row in rows if row["grain"] != "daily"
                or row["product_scope"] == REPORTED_PLATFORM_DAILY
                or _platform_day(row) not in protected_platform_days]
        for source_key, grain, start, end in sorted(scopes):
            if grain == "period":
                connection.execute(
                    f"DELETE FROM {SCHEMA}.expense_rows WHERE source_key=? AND grain='period' AND start_date=? AND end_date=?",
                    [source_key, start, end])
            else:
                connection.execute(
                    f"DELETE FROM {SCHEMA}.expense_rows WHERE source_key=? AND grain='daily' "
                    "AND start_date BETWEEN ? AND ? AND COALESCE(product_scope, '') NOT IN ?",
                    [source_key, start, end, manual_kinds])
        if manual_days:
            connection.executemany(
                f"DELETE FROM {SCHEMA}.expense_rows WHERE source_key=? AND grain='daily' AND start_date=?",
                sorted(manual_days))
        if manual_tencent_days:
            connection.executemany(
                f"DELETE FROM {SCHEMA}.expense_rows WHERE account_id=? AND start_date=? AND grain='daily' "
                "AND platform IN ('腾讯广告', '腾讯')",
                sorted(manual_tencent_days))
        if reported_days:
            connection.executemany(
                f"DELETE FROM {SCHEMA}.expense_rows WHERE business_line=? AND business_group=? "
                "AND CASE WHEN platform='腾讯' THEN '腾讯广告' ELSE platform END=? "
                "AND start_date=? AND grain='daily'",
                sorted(reported_days))
        for row in rows:
            connection.execute(f"DELETE FROM {SCHEMA}.expense_rows WHERE row_key=?", [row["row_key"]])
        if rows:
            columns = tuple(rows[0])
            names = ",".join(columns)
            placeholders = ",".join("?" for _ in columns)
            connection.executemany(
                f"INSERT INTO {SCHEMA}.expense_rows ({names}) VALUES ({placeholders})",
                [tuple(row[column] for column in columns) for row in rows])
        for summary in summaries:
            connection.execute(
                f"DELETE FROM {SCHEMA}.expense_sources WHERE summary_key=?",
                [summary["summary_key"]])
        if summaries:
            columns = tuple(summaries[0])
            names = ",".join(columns)
            placeholders = ",".join("?" for _ in columns)
            connection.executemany(
                f"INSERT INTO {SCHEMA}.expense_sources ({names}) VALUES ({placeholders})",
                [tuple(item[column] for column in columns) for item in summaries])
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    return {"rows": len(rows), "sources": len(summaries)}


def _prepare(costs: dict[str, Any], import_id: str):
    if not isinstance(costs, dict) or not isinstance(costs.get("rows"), list) or not isinstance(costs.get("sources"), list):
        raise ValueError("costs must contain parsed rows[] and sources[]")
    source_by_id: dict[str, list[dict[str, Any]]] = {}
    source_keys = set()
    for source in costs["sources"]:
        if not isinstance(source, dict) or not isinstance(source.get("source_id"), str):
            raise ValueError("parsed source metadata is invalid")
        platform = _required_text(source.get("platform"), "source platform")
        identity = (source["source_id"], platform)
        if identity in source_keys:
            raise ValueError(f"duplicate parsed source metadata: {identity[0]}/{identity[1]}")
        source_keys.add(identity)
        source_by_id.setdefault(source["source_id"], []).append(source)

    rows = []
    scopes: set[tuple[str, str, date, date]] = set()
    rows_by_source: dict[str, list[dict[str, Any]]] = {}
    seen = set()
    for row in costs["rows"]:
        if not isinstance(row, dict):
            raise ValueError("parsed expense row is invalid")
        source_id = _required_text(row.get("source_id"), "source_id")
        source_candidates = source_by_id.get(source_id, [])
        row_platform = _optional_text(row.get("platform"))
        if row_platform is not None:
            matching = [item for item in source_candidates if item.get("platform") == row_platform]
        else:
            matching = source_candidates
        if len(matching) != 1:
            raise ValueError(f"parsed source metadata missing: {source_id}")
        source = matching[0]
        source_row = row.get("source_row")
        if type(source_row) is not int or source_row < 1:
            raise ValueError(f"source_row must be a positive integer: {source_id}")
        grain = _required_text(source.get("grain", "daily"), "grain")
        line = row.get("business_line", source.get("business_line"))
        group = row.get("business_group", source.get("business_group"))
        platform = _required_text(row.get("platform", source.get("platform")), "platform")
        start = _date(row.get("start_date"), "start_date")
        end = _date(row.get("end_date"), "end_date")
        if start > end:
            raise ValueError(f"expense row date window is reversed: {source_id}/{source_row}")
        amount = _amount(row.get("amount"), source_id, source_row)
        account_id = _optional_identity(row.get("account_id"))
        product_scope = _optional_text(row.get("product_scope"))
        source_sheet = _optional_text(row.get("source_sheet")) or _optional_text(source.get("source_sheet"))
        project_id = _optional_identity(row.get("project_id"))
        placement_type = _optional_text(row.get("placement_type")) or _optional_text(row.get("投放类型"))
        marketing_scene = _optional_text(row.get("marketing_scene")) or _optional_text(row.get("营销场景"))
        company = _optional_text(row.get("company")) or _optional_text(source.get("company"))
        source_kind = source.get("source_kind")

        if source_kind == REPORTED_PLATFORM_DAILY:
            source_key = _summary_source_key(source)
            natural_parts = (source_kind, line, group, platform, start.isoformat())
            product_scope = source_kind
        elif source_kind == "manual_daily":
            if grain != "daily" or start != end or not line or not group:
                raise ValueError("手工费用必须明确业务组和单日")
            source_key = _stable_key("manual", line, group, platform)
            natural_parts = ("manual", line, group, platform, start.isoformat())
        elif source_kind in MANUAL_ACCOUNT_DAILY:
            if platform != MANUAL_ACCOUNT_DAILY[source_kind] or not account_id or account_id != source.get("account_id") or start != end or amount is None:
                raise ValueError(f"账户日报缺少有效账户日费用: {source_id}/{source_row}")
            product_scope = source_kind
            account_key = "xhs" if platform == "小红书" else "ocean_account"
            source_key = _stable_key(account_key, account_id)
            natural_parts = (source_kind, account_id, start.isoformat())
        elif platform == "小红书":
            if not account_id:
                raise ValueError(f"小红书行缺少account_id: {source_id}/{source_row}")
            source_key = _stable_key("xhs", account_id)
            natural_parts = ("xhs", account_id, start.isoformat())
        elif platform in {"腾讯广告", "腾讯"}:
            if source_kind == TENCENT_MANUAL:
                product_scope = TENCENT_MANUAL
                source_key = _stable_key("tencent_manual", account_id, group, grain)
                natural_parts = ("tencent_manual", account_id, group, start.isoformat(), end.isoformat())
            elif not account_id or not product_scope:
                raise ValueError(f"腾讯行缺少account_id/product_scope: {source_id}/{source_row}")
            else:
                source_key = _stable_key("tencent", account_id, product_scope)
                natural_parts = ("tencent", account_id, product_scope, start.isoformat())
        elif source_sheet is not None:
            source_key = _stable_key("sem", source_sheet)
            natural_parts = ("sem", source_sheet, start.isoformat())
        elif project_id is not None:
            if not placement_type or not marketing_scene:
                raise ValueError(f"巨量行缺少投放类型/营销场景: {source_id}/{source_row}")
            source_key = _stable_key("ocean_account", account_id) if account_id else _stable_key("ocean", project_id)
            natural_parts = ("ocean", project_id, start.isoformat(), placement_type, marketing_scene)
        elif grain == "period" or start != end:
            source_key = _stable_key("period", company, line, platform)
            channel = _optional_text(row.get("raw_channel"))
            natural_parts = ("period", company, line, group, platform,
                             start.isoformat(), end.isoformat(), channel)
        else:
            raise ValueError(f"daily expense row has no stable business key: {source_id}/{source_row}")

        natural_key = json.dumps(natural_parts, ensure_ascii=False, separators=(",", ":"))
        row_key = hashlib.sha256(natural_key.encode("utf-8")).hexdigest()
        if row_key in seen:
            raise ValueError(f"duplicate expense natural key: {natural_key}")
        seen.add(row_key)
        status = _optional_text(row.get("amount_status"))
        if status is None:
            status = "missing_amount" if amount is None else ("reported_zero" if amount == 0 else "reported_value")
        record = {
            "row_key": row_key, "natural_key": natural_key, "source_key": source_key,
            "source_sha256": _optional_text(source.get('sha256')),
            "source_id": source_id, "import_id": import_id, "source_row": source_row,
            "grain": grain, "business_line": _optional_text(line), "business_group": _optional_text(group),
            "platform": platform, "account_id": account_id, "product_scope": product_scope,
            "source_sheet": source_sheet, "project_id": project_id,
            "placement_type": placement_type, "marketing_scene": marketing_scene,
            "company": company, "start_date": start, "end_date": end,
            "amount": amount, "amount_status": status,
        }
        rows.append(record)
        rows_by_source.setdefault((source_id, platform), []).append(record)

    summaries = []
    summary_keys = set()
    for source_id, source_list in source_by_id.items():
        for source in source_list:
            source_rows = rows_by_source.get((source_id, source["platform"]), [])
            row_source_keys = sorted({row["source_key"] for row in source_rows})
            window = _coverage_window(source)
            grain = _required_text(source.get("grain", "daily"), "grain")
            if window is not None:
                for row_source_key in row_source_keys or [_summary_source_key(source)]:
                    start, end = window
                    scopes.add((row_source_key, "period" if grain == "period" else "daily", start, end))
            identity_source={**source,
                'account_id':source.get('account_id') or _single_dimension(source_rows,'account_id'),
                'product_scope':source.get('product_scope') or _single_dimension(source_rows,'product_scope')}
            key = _summary_source_key(identity_source)
            summary_start = _optional_date(source.get("start_date"))
            summary_end = _optional_date(source.get("end_date"))
            summary_material = [key]
            if source.get("source_kind") in MANUAL_ACCOUNT_DAILY:
                summary_material.append(source["source_kind"])
            summary_key = hashlib.sha256(json.dumps(summary_material, ensure_ascii=False,
                separators=(",", ":")).encode("utf-8")).hexdigest()
            if summary_key in summary_keys:
                raise ValueError(f"duplicate expense source summary: {source_id}/{key}")
            summary_keys.add(summary_key)
            safe_summary = {name: value for name, value in source.items()
                            if name not in {"resolved_path", "raw"} and not name.startswith("raw_")}
            safe_summary["source_key"] = key
            dimensions = sorted({json.dumps({
                name: row[name] for name in (
                    "account_id", "product_scope", "source_sheet", "project_id",
                    "placement_type", "marketing_scene") if row[name] is not None
            }, ensure_ascii=False, sort_keys=True) for row in source_rows})
            if dimensions:
                safe_summary["business_key_dimensions"] = [json.loads(value) for value in dimensions]
            missing = sum(row["amount"] is None for row in source_rows)
            summaries.append({
                "summary_key": summary_key, "import_id": import_id, "source_key": key,
                "source_id": source_id, "grain": grain,
                "business_line": _optional_text(source.get("business_line")),
                "business_group": _optional_text(source.get("business_group")),
                "platform": _required_text(source.get("platform"), "source platform"),
                "account_id": _optional_identity(source.get("account_id")) or _single_dimension(source_rows, "account_id"),
                "product_scope": _optional_text(source.get("product_scope")) or _single_dimension(source_rows, "product_scope"),
                "source_sheet": _optional_text(source.get("source_sheet")) or _single_dimension(source_rows, "source_sheet"),
                "source_path": _optional_text(source.get("path")),
                "source_sha256": _optional_text(source.get("sha256")),
                "start_date": summary_start, "end_date": summary_end,
                "row_count": len(source_rows), "missing_amount_count": missing,
                "coverage_state": _optional_text(source.get("coverage_state")),
                "summary_json": json.dumps(safe_summary, ensure_ascii=False, sort_keys=True,
                                            separators=(",", ":"), default=str),
            })
    return rows, summaries, scopes


def _summary_source_key(source: dict[str, Any]) -> str:
    platform = _required_text(source.get("platform"), "source platform")
    account_id = _optional_identity(source.get("account_id"))
    product_scope = _optional_text(source.get("product_scope"))
    sheet = _optional_text(source.get("source_sheet"))
    line = _optional_text(source.get("business_line"))
    company = _optional_text(source.get("company"))
    if source.get("source_kind") == "manual_daily":
        return _stable_key("manual", line, _required_text(source.get("business_group"), "business_group"), platform)
    if source.get("source_kind") == REPORTED_PLATFORM_DAILY:
        return _stable_key(REPORTED_PLATFORM_DAILY, line, source.get("business_group"), platform)
    if source.get("source_kind") == TENCENT_MANUAL:
        return _stable_key("tencent_manual", account_id, source.get("business_group"), source.get("grain"))
    if platform == "小红书" and account_id:
        return _stable_key("xhs", account_id)
    if platform in {"腾讯广告", "腾讯"} and account_id and product_scope:
        return _stable_key("tencent", account_id, product_scope)
    if sheet:
        return _stable_key("sem", sheet)
    if platform=='抖音' and account_id:
        return _stable_key('ocean_account',account_id)
    if source.get("grain") == "period":
        return _stable_key("period", company, line, platform)
    if platform=='抖音':
        return _stable_key('ocean_source',source['source_id'])
    return _stable_key("source", line, platform)


def _coverage_window(source: dict[str, Any]) -> tuple[date, date] | None:
    # A requested range/min-max is not proof that an account export is complete.
    # The verified capture caller may explicitly authorize range replacement;
    # otherwise replace only the natural keys actually supplied.
    if source.get('grain')!='period' and source.get('replacement_window_complete') is not True:
        return None
    start = source.get("requested_start_date")
    end = source.get("requested_end_date")
    selected = source.get("selected_window")
    if (start is None or end is None) and isinstance(selected, (list, tuple)) and len(selected) == 2:
        start, end = selected
    if (start is None or end is None) and source.get('grain')=='period':
        start, end = source.get("start_date"), source.get("end_date")
    if start is None or end is None:
        return None
    parsed_start, parsed_end = _date(start, "source start_date"), _date(end, "source end_date")
    if parsed_start > parsed_end:
        raise ValueError(f"source date window is reversed: {source.get('source_id')}")
    return parsed_start, parsed_end


def _stable_key(*parts: Any) -> str:
    value = json.dumps(parts, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _date(value: Any, label: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an ISO date") from exc


def _optional_date(value: Any) -> date | None:
    return None if value is None else _date(value, "source date")


def _amount(value: Any, source_id: str, source_row: int) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"expense amount is not numeric: {source_id}/{source_row}")
    try:
        result = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (ValueError, TypeError, ArithmeticError) as exc:
        raise ValueError(f"expense amount is not numeric: {source_id}/{source_row}") from exc
    if not result.is_finite():
        raise ValueError(f"expense amount is not finite: {source_id}/{source_row}")
    return result


def _single_dimension(rows: list[dict[str, Any]], name: str) -> str | None:
    values = {row[name] for row in rows if row[name] is not None}
    return next(iter(values)) if len(values) == 1 else None


def _required_text(value: Any, label: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"{label} is required")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _identity_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return _optional_text(value)


def _optional_identity(value: Any) -> str | None:
    return _identity_text(value)
