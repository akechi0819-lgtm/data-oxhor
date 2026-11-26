"""Refresh the BI and Tencent study-abroad warehouses as one daily attempt.

Each warehouse publishes independently. The receipt records the pair and the
``current.json`` pointer blocks consumers unless both current pointers agree.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import sys
from typing import Iterator
from zoneinfo import ZoneInfo

from data_acquisition.jobs import rebuild_bi_warehouse, update_tencent_study_abroad, sync_content_work_orders
from data_acquisition.jobs.bi_window_merge import rolling_start_date
from data_platform.snapshots.ingest import SNAPSHOT_ID
from interfaces.data_platform import RUN_ID


DAILY_ROOT = Path("Work/DailyWarehouseRefresh")
CURRENT_FILENAME = "current.json"
LAST_GOOD_FILENAME = "last_good.json"
LOCK_FILENAME = ".refresh.lock"
RECEIPT_SCHEMA = "daily_warehouse_refresh.v1"
SNAPSHOT_DATE_PATTERN = re.compile(r"_(\d{8})(?=_|$)")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _iso_date(value: str, field: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{field} must be an ISO date (YYYY-MM-DD)")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} is not a valid date") from error


def _snapshot_cut_date(snapshot_id: str) -> date | None:
    match = SNAPSHOT_DATE_PATTERN.search(str(snapshot_id or ""))
    if match is None:
        return None
    encoded = match.group(1)
    try:
        return date.fromisoformat(f"{encoded[:4]}-{encoded[4:6]}-{encoded[6:]}")
    except ValueError:
        return None


def _now_shanghai() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is missing or invalid") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


@contextmanager
def _daily_lock(root: Path) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / LOCK_FILENAME
    with lock_path.open("a+b") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("a daily warehouse refresh is already running") from error
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _safe_source_error(source: str, error: Exception) -> str:
    # Dependency messages can contain request URLs or credential material.
    # Preserve the exception class for diagnosis and omit its untrusted text.
    return f"{type(error).__name__}: {source} operation failed; details omitted to protect credentials"


def _result_file_sha256(result: dict, field: str) -> str:
    value = result.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError("source result is missing its captured export")
    path = Path(value)
    if not path.is_file():
        raise ValueError("captured export is missing")
    return _sha256_file(path)


def _study_capture_sha256(result: dict) -> str:
    capture = result.get("capture")
    if not isinstance(capture, dict):
        raise ValueError("source result is missing its capture receipt")
    path_value, declared = capture.get("path"), capture.get("sha256")
    if not isinstance(path_value, str) or not path_value:
        raise ValueError("source result is missing its captured export")
    path = Path(path_value)
    if not path.is_file():
        raise ValueError("captured export is missing")
    actual = _sha256_file(path)
    if not isinstance(declared, str) or not SHA256_PATTERN.fullmatch(declared) or actual != declared:
        raise ValueError("captured export hash does not match")
    return actual


def _workspace_company(workspace: Path) -> tuple[str | None, str | None]:
    config_path = workspace / "Work/workspace.json"
    if not config_path.is_file():
        return None, "BI workspace is not initialized"
    try:
        config = _read_json(config_path, "BI workspace configuration")
    except ValueError:
        return None, "BI workspace is not initialized"
    company_id = config.get("company_id")
    if not isinstance(company_id, str) or not company_id.strip():
        return None, "BI workspace is not initialized"
    return company_id, None


def _source_record(*, run_id: str, snapshot_id: str, cutoff_date: str,
                   company_id: str | None, extra: dict | None = None) -> dict:
    return {
        "status": "failed",
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "company_id": company_id,
        "cutoff_date": cutoff_date,
        "captured_at": None,
        "value_sha256": None,
        **(extra or {}),
    }


def _safe_daily_root(workspace: Path) -> Path:
    root = workspace / DAILY_ROOT
    resolved_workspace = workspace.resolve()
    if root.is_symlink():
        try:
            root.resolve().relative_to(resolved_workspace)
        except ValueError as error:
            raise ValueError("daily warehouse state must stay inside the workspace") from error
    if root.parent.exists() or root.parent.is_symlink():
        try:
            root.parent.resolve().relative_to(resolved_workspace)
        except ValueError as error:
            raise ValueError("daily warehouse state must stay inside the workspace") from error
    root.mkdir(parents=True, exist_ok=True)
    resolved_root = root.resolve()
    try:
        resolved_root.relative_to(resolved_workspace)
    except ValueError as error:
        raise ValueError("daily warehouse state must stay inside the workspace") from error
    return resolved_root


def _verify_bi_coverage(coverage: dict, as_of: date) -> None:
    for label in ("orders", "cash"):
        count = coverage.get(f"{label}_rows")
        if type(count) is not int or count <= 0:
            raise ValueError(f"BI {label} coverage has no rows")
        maximum = _iso_date(coverage.get(f"{label}_max_date"), f"BI {label} max date")
        if maximum < as_of - timedelta(days=1):
            raise ValueError(f"BI {label} coverage does not reach yesterday")


def refresh_daily(*, workspace: Path, as_of_date: str, run_id: str,
                  bi_snapshot_id: str, study_snapshot_id: str,
                  bi_start_date: str | None = None,
                  input_paths: dict[str, Path] | None = None,
                  orders_start_date: str | None = None, orders_end_date: str | None = None) -> dict:
    """Refresh both warehouses for an explicit Asia/Shanghai business date.

    ``as_of_date`` is supplied by the caller. BI uses the existing six-calendar-
    month rolling window by default; Tencent replaces the current month only.
    """
    as_of = _iso_date(as_of_date, "as_of_date")
    if not RUN_ID.fullmatch(run_id):
        raise ValueError("run_id is invalid")
    if not SNAPSHOT_ID.fullmatch(bi_snapshot_id) or not SNAPSHOT_ID.fullmatch(study_snapshot_id):
        raise ValueError("snapshot id is invalid")
    if _snapshot_cut_date(bi_snapshot_id) != as_of:
        raise ValueError("BI snapshot id must contain the as_of_date")
    start = _iso_date(bi_start_date, "bi_start_date") if bi_start_date else date.fromisoformat(
        rolling_start_date(as_of)
    )
    if start > as_of:
        raise ValueError("bi_start_date must be on or before as_of_date")

    if input_paths is not None and set(input_paths) != {'orders', 'cash', 'tencent'}:
        raise ValueError('offline inputs require both BI exports and the full Tencent workbook')
    workspace = Path(workspace).resolve()
    root = _safe_daily_root(workspace)
    run_root = root / "Runs" / run_id
    with _daily_lock(root):
        if run_root.exists() or run_root.is_symlink():
            raise ValueError("daily run_id has already been used")
        run_root.mkdir(parents=True, exist_ok=False)

        company_id, initialization_error = _workspace_company(workspace)
        bi = _source_record(
            run_id=run_id, snapshot_id=bi_snapshot_id, company_id=company_id,
            cutoff_date=as_of.isoformat(), extra={"start_date": start.isoformat()},
        )
        study = _source_record(
            run_id=run_id, snapshot_id=study_snapshot_id, company_id=company_id,
            cutoff_date=as_of.isoformat(), extra={
                "through_date": as_of.isoformat(),
                "refresh_months": [as_of.strftime("%Y-%m")],
            },
        )
        bi["status"] = "running"
        study["status"] = "running"
        receipt = {
            "schema_version": RECEIPT_SCHEMA,
            "run_id": run_id,
            "company_id": company_id,
            "as_of_date": as_of.isoformat(),
            "status": "running",
            "created_at": _now_shanghai(),
            "sources": {"bi": bi, "study_abroad": study},
        }
        receipt_path = run_root / "receipt.json"
        relative_receipt = receipt_path.relative_to(root).as_posix()

        def publish_current(status: str) -> tuple[dict, str]:
            receipt["status"] = status
            _atomic_json(receipt_path, receipt)
            receipt_sha256 = _sha256_file(receipt_path)
            pointer = {
                "schema_version": RECEIPT_SCHEMA,
                "run_id": run_id,
                "company_id": receipt.get("company_id"),
                "as_of_date": as_of.isoformat(),
                "status": status,
                "receipt_path": relative_receipt,
                "receipt_sha256": receipt_sha256,
                "bi_snapshot_id": bi_snapshot_id,
                "study_snapshot_id": study_snapshot_id,
            }
            _atomic_json(root / CURRENT_FILENAME, pointer)
            return pointer, receipt_sha256

        # Make the in-progress attempt authoritative before either warehouse can move.
        publish_current("running")

        if initialization_error:
            bi["status"] = "failed"
            bi["error"] = f"ValueError: {initialization_error}"
        else:
            try:
                result = rebuild_bi_warehouse.rebuild(
                    workspace=workspace,
                    snapshot_id=bi_snapshot_id,
                    start_date=start.isoformat(),
                    end_date=as_of.isoformat(),
                    **({'orders_start_date': orders_start_date, 'orders_end_date': orders_end_date}
                       if orders_start_date is not None else {}),
                    **({'export_paths': {key: input_paths[key] for key in ('orders', 'cash')}} if input_paths else {}),
                )
                if result.get("snapshot_id") != bi_snapshot_id or result.get("status") != "snapshot_ready":
                    raise ValueError("BI rebuild did not publish the requested Snapshot")
                values = {
                    "orders": _result_file_sha256(result, "export_orders"),
                    "cash": _result_file_sha256(result, "export_cash"),
                }
                bi_coverage = {
                    "orders_rows": result["merged_orders_rows"],
                    "cash_rows": result["merged_cash_rows"],
                    "orders_max_date": result["orders_max_assignment_date"],
                    "cash_max_date": result["cash_max_business_date"],
                }
                _verify_bi_coverage(bi_coverage, as_of)
                bi.update({
                    "status": "success",
                    "coverage": bi_coverage,
                    "captured_at": _now_shanghai(),
                    "value_sha256": _canonical_sha256(values),
                    "company_id": company_id,
                    "order_refresh": result.get("order_refresh"),
                    "orders_export": {"path": str(Path(result["export_orders"]).resolve()),
                                      "sha256": values["orders"]},
                })
            except Exception as error:
                bi["status"] = "failed"
                bi["error"] = _safe_source_error("BI", error)

        # This delivery is independent of warehouse acceptance and dashboard release.
        # Catch-up always uses the captured rolling export, never a second BI download.
        if bi["status"] == "success" and (workspace / ".private/content-work-orders.json").is_file():
            try:
                receipt["content_work_orders"] = sync_content_work_orders.sync(
                    workspace=workspace, source_file=Path(result["export_orders"]),
                    as_of_date=as_of.isoformat(), run_id=run_id,
                )
            except Exception as error:
                receipt["content_work_orders"] = {
                    "status": "failed",
                    "error": _safe_source_error("content work orders", error),
                    "receipt_path": str(workspace / "Work/ContentWorkOrders/Runs" / run_id / "receipt.json"),
                }

        try:
            result = update_tencent_study_abroad.update(
                workspace=workspace,
                run_id=run_id,
                snapshot_id=study_snapshot_id,
                through_date=as_of.isoformat(),
                refresh_months=[as_of.strftime("%Y-%m")],
                **({'source_file': input_paths['tencent']} if input_paths else {}),
            )
            if (result.get("run_id") != run_id or result.get("snapshot_id") != study_snapshot_id
                    or result.get("through_date") != as_of.isoformat()):
                raise ValueError("Tencent update did not publish the requested Snapshot and cutoff")
            if result.get("company_id") != company_id:
                raise ValueError("Tencent update company does not match the BI workspace")
            study.update({
                "status": "success",
                "company_id": result.get("company_id"),
                "captured_at": _now_shanghai(),
                "value_sha256": _study_capture_sha256(result),
            })
        except Exception as error:
            study["status"] = "failed"
            study["error"] = _safe_source_error("Tencent study-abroad", error)

        final_company_id, final_init_error = _workspace_company(workspace)
        joint_error = None
        if bi["status"] == "success" and study["status"] == "success":
            joint_error = _current_pair_error(
                workspace,
                company_id=company_id,
                bi_snapshot_id=bi_snapshot_id,
                study_snapshot_id=study_snapshot_id,
                through_date=as_of.isoformat(),
            )
        status = "passed" if (
            not final_init_error and final_company_id == company_id
            and bi["status"] == "success" and study["status"] == "success"
            and joint_error is None
        ) else "failed"
        receipt["company_id"] = final_company_id
        receipt["completed_at"] = _now_shanghai()
        receipt.pop("joint_error", None)
        if joint_error:
            receipt["joint_error"] = joint_error
        if final_company_id != company_id:
            receipt["error"] = "workspace company identity changed during refresh"

        pointer, receipt_sha256 = publish_current(status)
        if status == "passed":
            try:
                verified = assert_daily_ready(
                    workspace, as_of.isoformat(),
                    bi_snapshot_id=bi_snapshot_id,
                    study_snapshot_id=study_snapshot_id,
                )
                if verified.get("run_id") != run_id:
                    raise ValueError("current receipt changed during post-publication verification")
            except Exception as error:
                status = "failed"
                receipt["joint_error"] = (
                    "post-publication current pointer verification failed: "
                    f"{type(error).__name__}"
                )
                pointer, receipt_sha256 = publish_current(status)
            else:
                _atomic_json(root / LAST_GOOD_FILENAME, pointer)
        return {**receipt, "receipt_path": str(receipt_path), "receipt_sha256": receipt_sha256}


def _current_pair_error(workspace: Path, *, company_id: str | None,
                         bi_snapshot_id: str, study_snapshot_id: str,
                         through_date: str) -> str | None:
    if not company_id:
        return "workspace company identity is missing"
    try:
        bi_pointer = _read_json(workspace / "Work/workspace.json", "BI workspace configuration")
        study_pointer = _read_json(workspace / "Work/StudyAbroad/current.json", "study-abroad current pointer")
    except ValueError as error:
        return f"cannot verify current warehouse pointers: {type(error).__name__}"
    if bi_pointer.get("company_id") != company_id:
        return "BI current pointer company does not match this run"
    if bi_pointer.get("current_snapshot_id") != bi_snapshot_id:
        return "BI current Snapshot does not match this run"
    if study_pointer.get("company_id") != company_id:
        return "study-abroad current pointer company does not match this run"
    if study_pointer.get("snapshot_id") != study_snapshot_id:
        return "study-abroad current Snapshot does not match this run"
    if study_pointer.get("through_date") != through_date:
        return "study-abroad current cutoff does not match this run"
    return None


def _resolve_receipt_path(root: Path, reference: str) -> Path:
    if not isinstance(reference, str) or not reference:
        raise ValueError("current daily pointer has no receipt path")
    relative = PurePosixPath(reference)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("current daily receipt path is unsafe")
    candidate = root.joinpath(*relative.parts).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError("current daily receipt path escapes its state directory") from error
    return candidate


def assert_daily_ready(workspace: Path, as_of_date: str, *,
                       bi_snapshot_id: str | None = None,
                       study_snapshot_id: str | None = None) -> dict:
    """Return the verified latest receipt or raise when the pair is not ready."""
    as_of = _iso_date(as_of_date, "as_of_date")
    workspace = Path(workspace).resolve()
    root = workspace / DAILY_ROOT
    if not root.is_dir():
        raise ValueError("daily warehouse refresh state is missing")
    try:
        root.resolve().relative_to(workspace)
    except ValueError as error:
        raise ValueError("daily warehouse state must stay inside the workspace") from error

    current = _read_json(root / CURRENT_FILENAME, "current daily pointer")
    if current.get("schema_version") != RECEIPT_SCHEMA:
        raise ValueError("current daily pointer has an unsupported schema")
    if current.get("status") != "passed":
        raise ValueError("latest daily warehouse attempt did not pass")
    if current.get("as_of_date") != as_of.isoformat():
        raise ValueError("latest daily warehouse attempt is for another date")
    if bi_snapshot_id is not None and current.get("bi_snapshot_id") != bi_snapshot_id:
        raise ValueError("current BI Snapshot does not match the requested id")
    if study_snapshot_id is not None and current.get("study_snapshot_id") != study_snapshot_id:
        raise ValueError("current study-abroad Snapshot does not match the requested id")

    receipt_path = _resolve_receipt_path(root, current.get("receipt_path"))
    expected_hash = current.get("receipt_sha256")
    if not isinstance(expected_hash, str) or not SHA256_PATTERN.fullmatch(expected_hash):
        raise ValueError("current daily pointer has an invalid receipt hash")
    if not receipt_path.is_file() or _sha256_file(receipt_path) != expected_hash:
        raise ValueError("current daily receipt is missing or has changed")
    receipt = _read_json(receipt_path, "current daily receipt")
    if (receipt.get("schema_version") != RECEIPT_SCHEMA or receipt.get("status") != "passed"
            or receipt.get("run_id") != current.get("run_id")
            or receipt.get("as_of_date") != as_of.isoformat()
            or receipt.get("company_id") != current.get("company_id")):
        raise ValueError("current daily receipt identity does not match its pointer")

    workspace_config = _read_json(workspace / "Work/workspace.json", "BI workspace configuration")
    bi_current_id = workspace_config.get("current_snapshot_id")
    study_pointer = _read_json(workspace / "Work/StudyAbroad/current.json", "study-abroad current pointer")
    sources = receipt.get("sources")
    if not isinstance(sources, dict):
        raise ValueError("daily receipt has no source statuses")
    bi, study = sources.get("bi"), sources.get("study_abroad")
    if not isinstance(bi, dict) or not isinstance(study, dict):
        raise ValueError("daily receipt is missing a warehouse source")
    company_id = workspace_config.get("company_id")
    if (not isinstance(company_id, str) or not company_id
            or current.get("company_id") != company_id
            or study_pointer.get("company_id") != company_id):
        raise ValueError("BI, study-abroad, and daily receipt company identities do not match")
    if bi.get("status") != "success" or study.get("status") != "success":
        raise ValueError("both warehouse sources must have succeeded")
    if bi.get("company_id") != company_id or study.get("company_id") != company_id:
        raise ValueError("daily source company identities do not match the workspace")

    for source, source_id, actual_id, label in (
        (bi, current.get("bi_snapshot_id"), bi_current_id, "BI"),
        (study, current.get("study_snapshot_id"), study_pointer.get("snapshot_id"), "study-abroad"),
    ):
        if source.get("snapshot_id") != source_id or source_id != actual_id:
            raise ValueError(f"current {label} Snapshot does not match the successful receipt")
        if source.get("run_id") != receipt.get("run_id"):
            raise ValueError(f"{label} run id does not match the daily receipt")
        if source.get("cutoff_date") != as_of.isoformat():
            raise ValueError(f"{label} cutoff date does not match the daily receipt")
        captured_at = source.get("captured_at")
        if not isinstance(captured_at, str) or not captured_at:
            raise ValueError(f"{label} capture time is missing")
        if not isinstance(source.get("value_sha256"), str) or not SHA256_PATTERN.fullmatch(source["value_sha256"]):
            raise ValueError(f"{label} value hash is invalid")

    if _snapshot_cut_date(bi_current_id or "") != as_of:
        raise ValueError("current BI Snapshot date does not match as_of_date")
    coverage = bi.get("coverage")
    if not isinstance(coverage, dict):
        raise ValueError("daily receipt has no verified BI coverage")
    _verify_bi_coverage(coverage, as_of)
    through_date = _iso_date(study.get("through_date"), "study-abroad through_date")
    if through_date < as_of - timedelta(days=1):
        raise ValueError("study-abroad source does not cover through yesterday")
    if study_pointer.get("through_date") != through_date.isoformat():
        raise ValueError("current study-abroad cutoff does not match the successful receipt")
    if bi_snapshot_id is not None and bi_current_id != bi_snapshot_id:
        raise ValueError("current BI Snapshot does not match the requested id")
    if study_snapshot_id is not None and study_pointer.get("snapshot_id") != study_snapshot_id:
        raise ValueError("current study-abroad Snapshot does not match the requested id")
    return receipt


def _check_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Verify the latest daily warehouse pair")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--bi-snapshot-id")
    parser.add_argument("--study-snapshot-id")
    args = parser.parse_args(argv)
    try:
        receipt = assert_daily_ready(
            args.workspace,
            args.as_of_date,
            bi_snapshot_id=args.bi_snapshot_id,
            study_snapshot_id=args.study_snapshot_id,
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False))
        return 1
    sources = receipt["sources"]
    print(json.dumps({
        "status": "passed",
        "run_id": receipt["run_id"],
        "as_of_date": receipt["as_of_date"],
        "bi_snapshot_id": sources["bi"]["snapshot_id"],
        "study_snapshot_id": sources["study_abroad"]["snapshot_id"],
    }, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "check":
        return _check_main(arguments[1:])

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--bi-snapshot-id", required=True)
    parser.add_argument("--study-snapshot-id", required=True)
    parser.add_argument("--bi-start-date")
    args = parser.parse_args(arguments)
    try:
        result = refresh_daily(**vars(args))
    except (OSError, ValueError, RuntimeError, TimeoutError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps({
        "status": result["status"],
        "run_id": result["run_id"],
        "as_of_date": result["as_of_date"],
        "receipt_path": result["receipt_path"],
        "receipt_sha256": result["receipt_sha256"],
    }, ensure_ascii=False))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
