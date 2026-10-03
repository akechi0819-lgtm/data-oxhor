"""Merge a rolling BI export window with prior landing history outside the window.

Orders (工单): unique key ``ID``. Outside-window rows come from the previous
landing where ``分配时间`` (Excel serial or date-like) converts to a date ``< start``.
Near-window rows come from the fresh export xlsx in full. On ID conflict, near-window
rows win.

Cash (现金): do **not** invent a hard unique key for upsert — landing may contain
fully duplicate business rows. Outside-window = prior landing rows whose
``业务日期`` converts to a date ``< start`` (duplicates kept). Near-window = the
fresh export xlsx in full. Result = outside ∪ near (near replaces the whole window).
Suggested soft key for humans/docs only (not enforced):
工单ID + 业务日期 + 学员编号 + 现金收入 + 业务类型 (not strictly unique).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from dateutil.relativedelta import relativedelta

# Landing / ingest metadata columns stripped before writing Input xlsx.
_META_EXACT = {
    "source_id",
    "source_sha256",
    "source_filename",
    "sheet_name",
    "source_row_number",
    "ingest_batch_id",
    "snapshot_id",
}

_EXCEL_EPOCH = date(1899, 12, 30)


def rolling_start_date(today: date | None = None) -> str:
    """Return ISO start date = today minus 6 calendar months."""
    day = today or date.today()
    return (day - relativedelta(months=6)).isoformat()


def excel_serial_to_date(value: Any) -> date | None:
    """Convert Excel serial / datetime / ISO-ish string to ``date``; else None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        try:
            return _EXCEL_EPOCH + timedelta(days=int(value))
        except (OverflowError, ValueError):
            return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    try:
        as_float = float(text)
        if abs(as_float) < 1e7:
            return _EXCEL_EPOCH + timedelta(days=int(as_float))
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _is_meta_column(name: str) -> bool:
    if name in _META_EXACT:
        return True
    return name.startswith("source_") or name.startswith("ingest_")


def strip_meta_columns(columns: Iterable[str]) -> list[str]:
    return [c for c in columns if not _is_meta_column(c)]


def resolve_prior_landing_dir(workspace: Path) -> Path | None:
    """Locate the configured current Snapshot landing, or return None before first sync."""
    import json

    from workspace_modeling.bridge_alignment.workspace import current_snapshot_root

    try:
        snapshot_root = current_snapshot_root(workspace.resolve())
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"cannot resolve current BI Snapshot: {exc}") from exc
    if snapshot_root is None:
        return None

    manifest_path = snapshot_root / "snapshot_manifest.json"
    landing = snapshot_root / "landing"
    if not manifest_path.is_file():
        raise RuntimeError(f"current Snapshot manifest is missing: {manifest_path}")
    if not landing.is_dir():
        raise RuntimeError(f"current Snapshot landing directory is missing: {landing}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"current Snapshot manifest is invalid: {manifest_path}: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("snapshot_id") != snapshot_root.name:
        raise RuntimeError(f"current Snapshot manifest identity is invalid: {manifest_path}")
    if not isinstance(manifest.get("sources"), list) or not isinstance(manifest.get("artifacts"), list):
        raise RuntimeError(f"current Snapshot manifest is incomplete: {manifest_path}")
    return landing


def find_landing_parquet(landing_dir: Path, source_id: str) -> Path:
    """Find the source's sole manifest-declared landing artifact by exact table name."""
    import json

    manifest_path = landing_dir.parent / "snapshot_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"current Snapshot manifest is unavailable: {manifest_path}: {exc}") from exc

    sources = manifest.get("sources", []) if isinstance(manifest, dict) else []
    matches = [source for source in sources if isinstance(source, dict) and source.get("source_id") == source_id]
    if len(matches) != 1:
        raise RuntimeError(f"current Snapshot must contain exactly one {source_id} source")
    sheets = matches[0].get("sheets", [])
    tables = [
        sheet.get("target_table")
        for sheet in sheets
        if isinstance(sheet, dict) and isinstance(sheet.get("target_table"), str)
    ]
    if len(tables) != 1 or not tables[0] or Path(tables[0]).name != tables[0]:
        raise RuntimeError(f"current Snapshot {source_id} must declare exactly one landing table")

    relative_path = f"landing/{tables[0]}.parquet"
    artifacts = manifest.get("artifacts", [])
    if sum(
        1 for artifact in artifacts
        if isinstance(artifact, dict) and artifact.get("path") == relative_path
    ) != 1:
        raise RuntimeError(f"current Snapshot manifest does not declare {relative_path}")
    parquet = landing_dir / f"{tables[0]}.parquet"
    if not parquet.is_file():
        raise RuntimeError(f"current Snapshot landing artifact is missing: {parquet}")
    return parquet


def _read_parquet_rows(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    import duckdb

    con = duckdb.connect()
    rel = con.execute(f"SELECT * FROM read_parquet('{path.as_posix()}')")
    columns = [d[0] for d in rel.description]
    rows = [dict(zip(columns, row)) for row in rel.fetchall()]
    return columns, rows


def _read_xlsx_rows(path: Path) -> tuple[str, list[str], list[dict[str, Any]]]:
    import openpyxl

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet_name = workbook.sheetnames[0]
        sheet = workbook[sheet_name]
        iterator = sheet.iter_rows(values_only=True)
        header_row = next(iterator, None)
        if not header_row:
            return sheet_name, [], []
        columns = [str(c).strip() if c is not None else f"column_{i}" for i, c in enumerate(header_row)]
        rows: list[dict[str, Any]] = []
        for values in iterator:
            if values is None or all(v is None or str(v).strip() == "" for v in values):
                continue
            row = {columns[i]: values[i] if i < len(values) else None for i in range(len(columns))}
            rows.append(row)
        return sheet_name, columns, rows
    finally:
        workbook.close()


def _write_xlsx(path: Path, columns: list[str], rows: list[dict[str, Any]], sheet_name: str) -> None:
    """Write xlsx using the BI export sheet title so landing table names stay stable.

    Ingest maps non-ASCII sheet titles to ``sheet_<sha12>``; Bridge/dashboard SQL
    hardcode ``br_work_orders__sheet_1f0596db9f25`` / ``br_cash__sheet_39b8dee2e4b3``
    from titles ``工单明细导出用表`` / ``现金明细表``.
    """
    import openpyxl

    path.parent.mkdir(parents=True, exist_ok=True)
    title = (sheet_name or "").strip() or "Sheet1"
    workbook = openpyxl.Workbook(write_only=True)
    sheet = workbook.create_sheet(title)
    sheet.append(columns)
    for row in rows:
        sheet.append([row.get(c) for c in columns])
    workbook.save(path)
    workbook.close()


def _business_columns(prior_cols: list[str], export_cols: list[str]) -> list[str]:
    prior_biz = strip_meta_columns(prior_cols)
    export_biz = strip_meta_columns(export_cols)
    if prior_biz:
        ordered = list(prior_biz)
        seen = set(ordered)
        for c in export_biz:
            if c not in seen:
                ordered.append(c)
                seen.add(c)
        return ordered
    return list(export_biz)


def merge_orders(
    *,
    export_xlsx: Path,
    prior_parquet: Path | None,
    start: date,
) -> tuple[str, list[str], list[dict[str, Any]], dict[str, int]]:
    sheet_name, export_cols, export_rows = _read_xlsx_rows(export_xlsx)
    prior_cols: list[str] = []
    prior_rows: list[dict[str, Any]] = []
    if prior_parquet is not None:
        prior_cols, prior_rows = _read_parquet_rows(prior_parquet)

    columns = _business_columns(prior_cols, export_cols)
    outside: list[dict[str, Any]] = []
    for row in prior_rows:
        assigned = excel_serial_to_date(row.get("分配时间"))
        if assigned is not None and assigned < start:
            outside.append({c: row.get(c) for c in columns})

    near = [{c: row.get(c) for c in columns} for row in export_rows]
    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def _id_key(row: dict[str, Any]) -> str | None:
        raw = row.get("ID")
        if raw is None:
            return None
        text = str(raw).strip()
        return text or None

    for row in outside:
        key = _id_key(row)
        if key is None:
            # Keep rows without ID at front with synthetic keys to preserve history.
            synth = f"__outside_noid_{len(order)}"
            by_id[synth] = row
            order.append(synth)
            continue
        if key not in by_id:
            order.append(key)
        by_id[key] = row

    for row in near:
        key = _id_key(row)
        if key is None:
            synth = f"__near_noid_{len(order)}"
            by_id[synth] = row
            order.append(synth)
            continue
        if key not in by_id:
            order.append(key)
        by_id[key] = row  # near wins

    merged = [by_id[k] for k in order]
    stats = {
        "prior_rows": len(prior_rows),
        "export_rows": len(export_rows),
        "outside_rows": len(outside),
        "merged_rows": len(merged),
    }
    return sheet_name, columns, merged, stats


def merge_cash(
    *,
    export_xlsx: Path,
    prior_parquet: Path | None,
    start: date,
) -> tuple[str, list[str], list[dict[str, Any]], dict[str, int]]:
    # Soft key (documented only): 工单ID+业务日期+学员编号+现金收入+业务类型 — not unique.
    sheet_name, export_cols, export_rows = _read_xlsx_rows(export_xlsx)
    prior_cols: list[str] = []
    prior_rows: list[dict[str, Any]] = []
    if prior_parquet is not None:
        prior_cols, prior_rows = _read_parquet_rows(prior_parquet)

    columns = _business_columns(prior_cols, export_cols)
    outside: list[dict[str, Any]] = []
    for row in prior_rows:
        biz = excel_serial_to_date(row.get("业务日期"))
        if biz is not None and biz < start:
            outside.append({c: row.get(c) for c in columns})

    near = [{c: row.get(c) for c in columns} for row in export_rows]
    # Window replace: keep all outside rows (incl. duplicates) then append entire near window.
    merged = outside + near
    stats = {
        "prior_rows": len(prior_rows),
        "export_rows": len(export_rows),
        "outside_rows": len(outside),
        "merged_rows": len(merged),
    }
    return sheet_name, columns, merged, stats


def merge_exports_with_prior(
    *,
    workspace: Path,
    orders_xlsx: Path,
    cash_xlsx: Path,
    start_date: str,
    output_dir: Path,
) -> dict[str, Any]:
    """Build merged Input xlsx for orders+cash; return paths and stats."""
    start = date.fromisoformat(start_date)
    landing = resolve_prior_landing_dir(workspace)
    orders_parquet = find_landing_parquet(landing, "br_work_orders") if landing else None
    cash_parquet = find_landing_parquet(landing, "br_cash") if landing else None

    output_dir.mkdir(parents=True, exist_ok=True)
    orders_out = output_dir / "工单表_merged.xlsx"
    cash_out = output_dir / "现金表_merged.xlsx"

    o_sheet, o_cols, o_rows, o_stats = merge_orders(
        export_xlsx=orders_xlsx, prior_parquet=orders_parquet, start=start
    )
    c_sheet, c_cols, c_rows, c_stats = merge_cash(
        export_xlsx=cash_xlsx, prior_parquet=cash_parquet, start=start
    )
    _write_xlsx(orders_out, o_cols, o_rows, o_sheet)
    _write_xlsx(cash_out, c_cols, c_rows, c_sheet)

    return {
        "orders_path": orders_out,
        "cash_path": cash_out,
        "prior_landing": str(landing) if landing else None,
        "orders_prior_parquet": str(orders_parquet) if orders_parquet else None,
        "cash_prior_parquet": str(cash_parquet) if cash_parquet else None,
        "export_orders_rows": o_stats["export_rows"],
        "export_cash_rows": c_stats["export_rows"],
        "merged_orders_rows": o_stats["merged_rows"],
        "merged_cash_rows": c_stats["merged_rows"],
        "prior_orders_rows": o_stats["prior_rows"],
        "prior_cash_rows": c_stats["prior_rows"],
        "outside_orders_rows": o_stats["outside_rows"],
        "outside_cash_rows": c_stats["outside_rows"],
        "start_date": start_date,
    }


__all__ = [
    "rolling_start_date",
    "excel_serial_to_date",
    "resolve_prior_landing_dir",
    "find_landing_parquet",
    "merge_orders",
    "merge_cash",
    "merge_exports_with_prior",
    "strip_meta_columns",
]
