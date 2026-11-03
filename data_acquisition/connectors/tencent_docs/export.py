"""Export a Tencent Docs workbook through MCP and save a verified XLSX locally."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import posixpath
import re
import subprocess
import tempfile
import time
from typing import Any
from urllib.parse import urlsplit
import uuid
import zipfile
import zlib
from xml.etree import ElementTree

from data_acquisition.connectors.tencent_docs.mcp import (
    TencentDocsMCPClient,
    TencentDocsMCPError,
)

COS_HOST = "docs-import-export-1251316161.cos.ap-guangzhou.myqcloud.com"
TASK_STATE_NAME = "export-task.json"
TASK_STATE_SCHEMA = "tencent_docs_export_task.v1"
_SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class DownloadReceipt:
    path: Path
    sha256: str
    size_bytes: int
    task_id: str


def _positive_seconds(value: object, field: str) -> float:
    try:
        seconds = float(value)
        valid = math.isfinite(seconds) and seconds > 0
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError(f"{field} must be a positive finite number")
    return seconds


def _call_tool(client: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = client.call_tool(name, arguments)
    if not isinstance(result, dict):
        raise TencentDocsMCPError(f"mcp_tool_response_invalid:{name}")
    if result.get("isError") or result.get("error"):
        raise TencentDocsMCPError(f"mcp_tool_reported_error:{name}")
    if "structuredContent" in result:
        result = result["structuredContent"]
    if not isinstance(result, dict):
        raise TencentDocsMCPError(f"mcp_tool_structured_content_missing:{name}")
    if result.get("error"):
        raise TencentDocsMCPError(f"mcp_tool_reported_error:{name}")
    return result


def _task_identifier(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise TencentDocsMCPError("export_task_id_missing")
    identifier = str(value).strip()
    if not identifier or any(ord(char) < 32 for char in identifier):
        raise TencentDocsMCPError("export_task_id_invalid")
    return identifier


def _write_task_state(path: Path, state: dict[str, Any]) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=".export-task-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(state, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def _read_task_state(path: Path, *, file_id: str, output_dir: Path) -> tuple[str, dict[str, Any] | None]:
    if not path.exists():
        return "new", None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise TencentDocsMCPError("export_task_state_invalid") from None
    if not isinstance(state, dict) or state.get("schema_version") != TASK_STATE_SCHEMA:
        raise TencentDocsMCPError("export_task_state_invalid")
    if state.get("file_id") != file_id:
        raise TencentDocsMCPError("export_task_state_file_mismatch")
    status = state.get("status")
    if status == "submitting":
        return "submitting", None
    if status not in {"pending", "downloaded"}:
        raise TencentDocsMCPError("export_task_state_status_invalid")
    task_id = _task_identifier(state.get("task_id"))
    if status == "downloaded":
        filename = state.get("filename")
        if not isinstance(filename, str) or not filename or Path(filename).name != filename:
            raise TencentDocsMCPError("export_artifact_path_invalid")
        path = output_dir / filename
        if not path.is_file():
            raise TencentDocsMCPError("export_artifact_missing")
        digest, size = _file_digest(path)
        if digest != state.get("sha256") or size != state.get("size_bytes"):
            raise TencentDocsMCPError("export_artifact_hash_changed")
        _validate_xlsx(path)
        return "downloaded", {
            "path": path,
            "sha256": digest,
            "size_bytes": size,
            "task_id": task_id,
        }
    return "pending", {"task_id": task_id}


def _safe_filename(task_id: str) -> str:
    safe_task_id = _SAFE_FILENAME_RE.sub("_", task_id).strip("._-")[:32] or "task"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"tencent_docs_{safe_task_id}_{timestamp}_{uuid.uuid4().hex[:10]}.xlsx"


def _validated_file_url(value: object) -> str:
    if not isinstance(value, str) or not value or any(ord(char) < 32 for char in value):
        raise TencentDocsMCPError("export_file_url_invalid")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        raise TencentDocsMCPError("export_file_url_invalid") from None
    if (parts.scheme != "https" or parts.hostname != COS_HOST
            or parts.username is not None or parts.password is not None
            or port not in (None, 443) or not parts.path or parts.fragment):
        raise TencentDocsMCPError("export_file_url_host_rejected")
    if any(ord(char) > 126 for char in value):
        raise TencentDocsMCPError("export_file_url_invalid")
    return value


def _download_cos(file_url: str, destination: Path, timeout_sec: float) -> None:
    # The signed URL is sent only in curl's stdin config, never in argv or receipts.
    curl_config = f"url = {json.dumps(file_url)}\n"
    try:
        response = subprocess.run(
            ["/usr/bin/curl", "-sS", "--max-time", str(timeout_sec), "--output", str(destination),
             "--write-out", "\n__HTTP__%{http_code}", "--config", "-"],
            input=curl_config,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_sec + 5,
        )
    except subprocess.TimeoutExpired:
        raise TencentDocsMCPError("export_download_timeout") from None
    except OSError:
        raise TencentDocsMCPError("export_curl_unavailable") from None
    if response.returncode:
        raise TencentDocsMCPError("export_download_transport_error")
    _, marker, status_text = response.stdout.rpartition("\n__HTTP__")
    if not marker:
        raise TencentDocsMCPError("export_download_response_invalid")
    try:
        status = int(status_text)
    except ValueError:
        raise TencentDocsMCPError("export_download_response_invalid") from None
    if 300 <= status < 400:
        raise TencentDocsMCPError("export_download_redirect_refused")
    if not 200 <= status < 300:
        raise TencentDocsMCPError(f"export_download_http_error:{status}")


def _file_digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
    except OSError:
        raise TencentDocsMCPError("export_artifact_unreadable") from None
    return digest.hexdigest(), size


def _validate_xlsx(path: Path) -> None:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            if archive.testzip() is not None:
                raise TencentDocsMCPError("export_xlsx_zip_crc_invalid")
            names = set(archive.namelist())
            required = {"[Content_Types].xml", "xl/workbook.xml", "xl/_rels/workbook.xml.rels"}
            if not required.issubset(names):
                raise TencentDocsMCPError("export_xlsx_required_parts_missing")
            content_types = ElementTree.fromstring(archive.read("[Content_Types].xml"))
            workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
            relationships = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            overrides = {
                item.attrib.get("PartName"): item.attrib.get("ContentType")
                for item in content_types.findall("{*}Override")
            }
            if "/xl/workbook.xml" not in overrides:
                raise TencentDocsMCPError("export_xlsx_workbook_content_type_missing")
            rel_map = {
                item.attrib.get("Id"): item.attrib
                for item in relationships.findall(f"{{{_PKG_REL_NS}}}Relationship")
            }
            sheets = workbook.findall(f".//{{{_SHEET_NS}}}sheet")
            if not sheets:
                raise TencentDocsMCPError("export_xlsx_has_no_sheets")
            for sheet in sheets:
                relation_id = sheet.attrib.get(f"{{{_DOC_REL_NS}}}id")
                relation = rel_map.get(relation_id)
                if (not relation or relation.get("TargetMode") == "External"
                        or not relation.get("Type", "").endswith("/worksheet")):
                    raise TencentDocsMCPError("export_xlsx_worksheet_relationship_invalid")
                target = relation.get("Target", "")
                worksheet_path = (target.lstrip("/") if target.startswith("/")
                                  else posixpath.normpath(posixpath.join("xl", target)))
                if worksheet_path not in names or f"/{worksheet_path}" not in overrides:
                    raise TencentDocsMCPError("export_xlsx_worksheet_missing")
                worksheet = ElementTree.fromstring(archive.read(worksheet_path))
                if worksheet.tag != f"{{{_SHEET_NS}}}worksheet":
                    raise TencentDocsMCPError("export_xlsx_worksheet_invalid")
    except TencentDocsMCPError:
        raise
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError, KeyError, zlib.error, RuntimeError):
        raise TencentDocsMCPError("export_xlsx_invalid") from None


def _completed_task_state(file_id: str, task_id: str, receipt: DownloadReceipt) -> dict[str, Any]:
    return {
        "schema_version": TASK_STATE_SCHEMA,
        "file_id": file_id,
        "task_id": task_id,
        "status": "downloaded",
        "filename": receipt.path.name,
        "sha256": receipt.sha256,
        "size_bytes": receipt.size_bytes,
    }


def download_tencent_doc_xlsx(
    *,
    file_id: str,
    token_file: str | Path,
    output_dir: str | Path,
    client: Any = None,
    timeout_sec: float = 240,
    poll_interval_sec: float = 5,
) -> DownloadReceipt:
    """Export one Tencent Docs file through MCP and verify its local XLSX."""
    if not isinstance(file_id, str) or not file_id.strip() or any(ord(char) < 32 for char in file_id):
        raise ValueError("file_id must be a non-empty document identifier")
    timeout = _positive_seconds(timeout_sec, "timeout_sec")
    poll_interval = _positive_seconds(poll_interval_sec, "poll_interval_sec")
    selected_output_dir = Path(output_dir).expanduser().resolve()
    try:
        selected_output_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise TencentDocsMCPError("export_output_directory_unavailable") from None
    state_path = selected_output_dir / TASK_STATE_NAME
    state_kind, state = _read_task_state(state_path, file_id=file_id, output_dir=selected_output_dir)
    if state_kind == "downloaded":
        return DownloadReceipt(**state)
    if state_kind == "submitting":
        raise TencentDocsMCPError("export_submission_unknown")

    active_client = client if client is not None else TencentDocsMCPClient(token_file)
    if state_kind == "new":
        _write_task_state(state_path, {
            "schema_version": TASK_STATE_SCHEMA,
            "file_id": file_id,
            "status": "submitting",
        })
        task = _call_tool(active_client, "manage.export_file", {"file_id": file_id})
        task_id = _task_identifier(task.get("task_id"))
        _write_task_state(state_path, {
            "schema_version": TASK_STATE_SCHEMA,
            "file_id": file_id,
            "task_id": task_id,
            "status": "pending",
        })
    else:
        task_id = state["task_id"]

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        progress_state = _call_tool(active_client, "manage.export_progress", {"task_id": task_id})
        progress = progress_state.get("progress")
        if isinstance(progress, bool) or not isinstance(progress, (int, float)) or not math.isfinite(progress):
            raise TencentDocsMCPError("export_progress_invalid")
        if progress >= 100:
            file_url = _validated_file_url(progress_state.get("file_url"))
            temporary_fd, temporary_name = tempfile.mkstemp(
                prefix=".tencent-docs-export-", suffix=".part", dir=selected_output_dir,
            )
            os.close(temporary_fd)
            temporary_path = Path(temporary_name)
            final_path = selected_output_dir / _safe_filename(task_id)
            try:
                _download_cos(file_url, temporary_path, timeout)
                _validate_xlsx(temporary_path)
                digest, size = _file_digest(temporary_path)
                try:
                    os.link(temporary_path, final_path)
                except FileExistsError:
                    raise TencentDocsMCPError("export_output_filename_collision") from None
                except OSError:
                    raise TencentDocsMCPError("export_output_finalize_failed") from None
                receipt = DownloadReceipt(final_path, digest, size, task_id)
                _write_task_state(state_path, _completed_task_state(file_id, task_id, receipt))
                return receipt
            finally:
                temporary_path.unlink(missing_ok=True)
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(poll_interval, remaining))
    raise TencentDocsMCPError("export_task_timeout")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file-id", required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        receipt = download_tencent_doc_xlsx(
            file_id=args.file_id,
            token_file=args.token_file,
            output_dir=args.output_dir,
        )
    except (OSError, ValueError, TencentDocsMCPError) as error:
        code = error.code if isinstance(error, TencentDocsMCPError) else f"invalid_input:{type(error).__name__}"
        print(json.dumps({"status": "failed", "error": code}, ensure_ascii=False))
        return 1
    print(json.dumps({
        "status": "downloaded",
        "path": str(receipt.path),
        "sha256": receipt.sha256,
        "size_bytes": receipt.size_bytes,
        "task_id": receipt.task_id,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
