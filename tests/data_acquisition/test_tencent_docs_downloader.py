from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from urllib.parse import urlsplit
import zipfile
from io import BytesIO

import pytest

from data_acquisition.connectors.tencent_docs import export as export_module
from data_acquisition.connectors.tencent_docs import mcp as mcp_module
from data_acquisition.connectors.tencent_docs.export import (
    COS_HOST,
    DownloadReceipt,
    download_tencent_doc_xlsx,
)
from data_acquisition.connectors.tencent_docs.mcp import (
    MCP_ENDPOINT,
    TencentDocsMCPClient,
    TencentDocsMCPError,
)

FILE_ID = "test-file-id"
TASK_ID = "task-test-01"
SIGNED_URL = f"https://{COS_HOST}/export.xlsx?sign=private-signature"


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeClient:
    def __init__(self, progress, *, task_id=TASK_ID, export_error=None) -> None:
        self.progress = list(progress)
        self.task_id = task_id
        self.export_error = export_error
        self.calls: list[tuple[str, dict]] = []

    def call_tool(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, arguments))
        if name == "manage.export_file":
            if self.export_error is not None:
                if isinstance(self.export_error, Exception):
                    raise self.export_error
                return self.export_error
            return {"task_id": self.task_id}
        if name == "manage.export_progress":
            if not self.progress:
                raise AssertionError("unexpected extra export progress query")
            value = self.progress.pop(0)
            if isinstance(value, Exception):
                raise value
            return value
        raise AssertionError(f"unexpected MCP tool: {name}")


def _xlsx_bytes(*, include_workbook=True, include_sheet=True, include_sheet_entry=True) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            "<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>"
            "<Override PartName='/xl/workbook.xml' "
            "ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'/>"
            "<Override PartName='/xl/worksheets/sheet1.xml' "
            "ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/>"
            "</Types>",
        )
        if include_workbook:
            sheets = "<sheets><sheet name='Sheet1' sheetId='1' r:id='rId1'/></sheets>" if include_sheet else "<sheets/>"
            archive.writestr(
                "xl/workbook.xml",
                "<workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' "
                "xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'>"
                f"{sheets}</workbook>",
            )
            archive.writestr(
                "xl/_rels/workbook.xml.rels",
                "<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"
                "<Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' "
                "Target='worksheets/sheet1.xml'/></Relationships>",
            )
            if include_sheet_entry:
                archive.writestr(
                    "xl/worksheets/sheet1.xml",
                    "<worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><sheetData/></worksheet>",
                )
    return buffer.getvalue()


class CurlDownloadStub:
    def __init__(self, monkeypatch, body: bytes, *, status: int = 200, returncode: int = 0) -> None:
        self.body = body
        self.status = status
        self.returncode = returncode
        self.calls: list[dict] = []
        monkeypatch.setattr(export_module.subprocess, "run", self.run)

    def run(self, args, *, input, text, capture_output, check, timeout):
        self.calls.append({
            "args": list(args), "input": input, "text": text,
            "capture_output": capture_output, "check": check, "timeout": timeout,
        })
        output_path = Path(args[args.index("--output") + 1])
        output_path.write_bytes(self.body)
        return SimpleNamespace(
            returncode=self.returncode,
            stdout=f"\n__HTTP__{self.status}",
            stderr="",
        )


def _progress_done(url: str = SIGNED_URL) -> dict:
    return {"progress": 100, "file_url": url}


def _download(tmp_path: Path, client: FakeClient, *, token_file=None,
              timeout_sec=30, poll_interval_sec=5) -> DownloadReceipt:
    return download_tencent_doc_xlsx(
        file_id=FILE_ID,
        token_file=token_file or (tmp_path / "token.txt"),
        output_dir=tmp_path / "export-run",
        client=client,
        timeout_sec=timeout_sec,
        poll_interval_sec=poll_interval_sec,
    )


def test_mcp_export_polls_and_downloads_verified_xlsx(tmp_path: Path, monkeypatch) -> None:
    xlsx = _xlsx_bytes()
    client = FakeClient([{"progress": 40}, _progress_done()])
    clock = FakeClock()
    monkeypatch.setattr(export_module, "time", clock)
    curl = CurlDownloadStub(monkeypatch, xlsx)

    receipt = _download(tmp_path, client)

    assert receipt == DownloadReceipt(
        path=receipt.path,
        sha256=hashlib.sha256(xlsx).hexdigest(),
        size_bytes=len(xlsx),
        task_id=TASK_ID,
    )
    assert receipt.path.is_file()
    assert zipfile.is_zipfile(receipt.path)
    assert [name for name, _ in client.calls] == [
        "manage.export_file", "manage.export_progress", "manage.export_progress",
    ]
    assert client.calls[0][1] == {"file_id": FILE_ID}
    assert client.calls[1][1] == {"task_id": TASK_ID}
    assert clock.sleeps == [5]
    assert len(curl.calls) == 1
    assert SIGNED_URL not in curl.calls[0]["args"]
    assert SIGNED_URL in curl.calls[0]["input"]
    assert urlsplit(curl.calls[0]["input"].split('url = "', 1)[1].split('"', 1)[0]).hostname == COS_HOST

    state = json.loads((tmp_path / "export-run/export-task.json").read_text(encoding="utf-8"))
    assert state["status"] == "downloaded"
    assert state["task_id"] == TASK_ID
    assert "file_url" not in state
    assert SIGNED_URL not in json.dumps(state)


def test_pending_export_task_resumes_without_resubmitting(tmp_path: Path, monkeypatch) -> None:
    xlsx = _xlsx_bytes()
    client = FakeClient([{"progress": 20}, {"progress": 20}, _progress_done()])
    clock = FakeClock()
    monkeypatch.setattr(export_module, "time", clock)
    curl = CurlDownloadStub(monkeypatch, xlsx)

    with pytest.raises(TencentDocsMCPError, match="export_task_timeout"):
        _download(tmp_path, client, timeout_sec=6)
    state_path = tmp_path / "export-run/export-task.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state == {
        "schema_version": "tencent_docs_export_task.v1",
        "file_id": FILE_ID,
        "task_id": TASK_ID,
        "status": "pending",
    }

    receipt = _download(tmp_path, client)

    assert receipt.task_id == TASK_ID
    assert [name for name, _ in client.calls].count("manage.export_file") == 1
    assert [name for name, _ in client.calls].count("manage.export_progress") == 3
    assert len(curl.calls) == 1


def test_auth_or_business_tool_error_fails_without_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(export_module.subprocess, "run", lambda *args, **kwargs: pytest.fail("no COS download"))
    client = FakeClient([], export_error=TencentDocsMCPError("mcp_http_error:401"))

    with pytest.raises(TencentDocsMCPError, match="mcp_http_error:401"):
        _download(tmp_path, client)

    assert [name for name, _ in client.calls] == ["manage.export_file"]
    state = json.loads((tmp_path / "export-run/export-task.json").read_text(encoding="utf-8"))
    assert state["status"] == "submitting"


def test_unknown_export_submission_is_not_retried_on_same_directory(tmp_path: Path) -> None:
    client = FakeClient([], export_error=TencentDocsMCPError("mcp_transport_error"))

    with pytest.raises(TencentDocsMCPError, match="mcp_transport_error"):
        _download(tmp_path, client)
    with pytest.raises(TencentDocsMCPError, match="export_submission_unknown"):
        _download(tmp_path, client)

    assert [name for name, _ in client.calls].count("manage.export_file") == 1
    state = json.loads((tmp_path / "export-run/export-task.json").read_text(encoding="utf-8"))
    assert state["status"] == "submitting"
    assert "task_id" not in state


def test_mcp_client_uses_token_from_config_stdin_and_decodes_sse(tmp_path: Path, monkeypatch) -> None:
    token_file = tmp_path / "token.txt"
    token_file.write_text("secret-token", encoding="utf-8")
    observations = {}

    def fake_run(args, *, input, text, capture_output, check, timeout):
        observations.update(args=list(args), input=input, timeout=timeout)
        body_path = Path(args[args.index("--data-binary") + 1][1:])
        observations["request"] = json.loads(body_path.read_text(encoding="utf-8"))
        envelope = {"jsonrpc": "2.0", "id": 1, "result": {
            "structuredContent": {"task_id": TASK_ID},
        }}
        return SimpleNamespace(returncode=0, stdout=f"event: message\ndata: {json.dumps(envelope)}\n\n\n__HTTP__200", stderr="")

    monkeypatch.setattr(mcp_module.subprocess, "run", fake_run)
    result = TencentDocsMCPClient(token_file).call_tool("manage.export_file", {"file_id": FILE_ID})

    assert result == {"task_id": TASK_ID}
    assert token_file.read_text(encoding="utf-8") in observations["input"]
    assert "secret-token" not in " ".join(observations["args"])
    assert MCP_ENDPOINT in observations["input"]
    assert observations["request"]["params"] == {
        "name": "manage.export_file", "arguments": {"file_id": FILE_ID},
    }


@pytest.mark.parametrize("body,status,error", [
    (b"upstream unavailable", 200, "mcp_response_not_json_or_sse"),
    (b'{"jsonrpc":"2.0","id":1,"result":{"isError":true}}', 200, "mcp_tool_reported_error"),
    (b'{"jsonrpc":"2.0","id":1,"error":{"code":-32000}}', 200, "mcp_jsonrpc_error"),
    (b"", 401, "mcp_http_error:401"),
])
def test_mcp_client_surfaces_protocol_auth_and_tool_errors_safely(
    tmp_path: Path, monkeypatch, body: bytes, status: int, error: str,
) -> None:
    token_file = tmp_path / "token.txt"
    token_file.write_text("never-print-this-token", encoding="utf-8")

    def fake_run(*args, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=f"{body.decode('utf-8')}\n__HTTP__{status}",
            stderr="",
        )

    monkeypatch.setattr(mcp_module.subprocess, "run", fake_run)
    with pytest.raises(TencentDocsMCPError, match=error) as captured:
        TencentDocsMCPClient(token_file).call_tool("manage.export_file", {"file_id": FILE_ID})

    assert "never-print-this-token" not in str(captured.value)


def test_export_poll_timeout_preserves_pending_task(tmp_path: Path, monkeypatch) -> None:
    clock = FakeClock()
    monkeypatch.setattr(export_module, "time", clock)
    client = FakeClient([{"progress": 20}, {"progress": 40}])

    with pytest.raises(TencentDocsMCPError, match="export_task_timeout"):
        _download(tmp_path, client, timeout_sec=6, poll_interval_sec=5)

    assert clock.sleeps == [5, 1]
    assert json.loads((tmp_path / "export-run/export-task.json").read_text())["status"] == "pending"


def test_rejects_download_url_outside_official_cos_host(tmp_path: Path, monkeypatch) -> None:
    curl = CurlDownloadStub(monkeypatch, _xlsx_bytes())
    client = FakeClient([_progress_done("https://example.invalid/file.xlsx?sign=secret")])

    with pytest.raises(TencentDocsMCPError, match="export_file_url_host_rejected"):
        _download(tmp_path, client)

    assert not curl.calls
    state = json.loads((tmp_path / "export-run/export-task.json").read_text())
    assert state["status"] == "pending"
    assert "secret" not in json.dumps(state)


def test_non_xlsx_response_is_rejected_and_temporary_file_removed(tmp_path: Path, monkeypatch) -> None:
    CurlDownloadStub(monkeypatch, b"not an xlsx document")
    client = FakeClient([_progress_done()])

    with pytest.raises(TencentDocsMCPError, match="export_xlsx_invalid"):
        _download(tmp_path, client)

    output_dir = tmp_path / "export-run"
    assert not list(output_dir.glob("*.xlsx"))
    assert not list(output_dir.glob("*.part"))


def test_corrupt_zip_crc_is_rejected(tmp_path: Path, monkeypatch) -> None:
    corrupted = bytearray(_xlsx_bytes())
    payload_index = corrupted.index(b"<sheetData/>")
    corrupted[payload_index + 2] ^= 1
    CurlDownloadStub(monkeypatch, bytes(corrupted))
    client = FakeClient([_progress_done()])

    with pytest.raises(TencentDocsMCPError, match="export_xlsx_zip_crc_invalid"):
        _download(tmp_path, client)


def test_valid_zip_with_invalid_workbook_content_is_rejected(tmp_path: Path, monkeypatch) -> None:
    CurlDownloadStub(monkeypatch, _xlsx_bytes(include_sheet=False))
    client = FakeClient([_progress_done()])

    with pytest.raises(TencentDocsMCPError, match="export_xlsx_has_no_sheets"):
        _download(tmp_path, client)


def test_completed_export_reuses_artifact_and_rejects_hash_change(tmp_path: Path, monkeypatch) -> None:
    xlsx = _xlsx_bytes()
    client = FakeClient([_progress_done()])
    CurlDownloadStub(monkeypatch, xlsx)
    receipt = _download(tmp_path, client)
    calls_before_reuse = len(client.calls)

    reused = _download(tmp_path, client)

    assert reused == receipt
    assert len(client.calls) == calls_before_reuse
    receipt.path.write_bytes(receipt.path.read_bytes() + b"tampered")
    with pytest.raises(TencentDocsMCPError, match="export_artifact_hash_changed"):
        _download(tmp_path, client)
    assert len(client.calls) == calls_before_reuse


def test_cli_only_exposes_file_token_and_output_arguments() -> None:
    with pytest.raises(SystemExit):
        export_module.main(["--doc-id", "legacy-doc", "--cookie-file", "old-cookies.json"])
