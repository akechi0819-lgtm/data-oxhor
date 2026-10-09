from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import zipfile
from io import BytesIO

import pytest

from data_acquisition.connectors.tencent_docs.downloader import (
    COS_HOST,
    TencentDocsDownloadError,
    TencentDocsExportConfig,
    download_tencent_doc_xlsx,
)


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body = body
        self.status = status
        self.offset = 0
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self.body) - self.offset
        chunk = self.body[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk

    def getcode(self) -> int:
        return self.status

    def close(self) -> None:
        self.closed = True


class ScriptedTransport:
    def __init__(self, responses: list[tuple[str, FakeResponse]]) -> None:
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, *, timeout: float, ca_file: Path | None = None):
        self.requests.append(request)
        expected_path, response = self.responses.pop(0)
        assert urlsplit(request.full_url).path == expected_path
        assert timeout > 0
        return response


def _json_response(payload: dict, status: int = 200) -> FakeResponse:
    return FakeResponse(json.dumps(payload).encode("utf-8"), status=status)


def _xlsx_bytes() -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'/>")
        archive.writestr(
            "xl/workbook.xml",
            "<workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'>"
            "<sheets><sheet name='Sheet1' sheetId='1' r:id='rId1' "
            "xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'/></sheets>"
            "</workbook>",
        )
        archive.writestr("xl/worksheets/sheet1.xml", "<worksheet/>")
    return buffer.getvalue()


def _cookie_file(tmp_path: Path, cookies: list[dict] | None = None) -> Path:
    path = tmp_path / "cookies.json"
    path.write_text(
        json.dumps(
            {
                "cookies": cookies
                if cookies is not None
                else [
                    {"name": "sid", "value": "captured-value", "domain": ".docs.qq.com", "path": "/"},
                    {
                        "name": "old",
                        "value": "expired-value",
                        "domain": ".docs.qq.com",
                        "path": "/",
                        "expires": 1,
                    },
                    {"name": "other", "value": "foreign-value", "domain": ".example.com", "path": "/"},
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def _config(tmp_path: Path, **overrides) -> TencentDocsExportConfig:
    values = {
        "doc_id": "300000000$NtrQNCVnVIJu",
        "page_url": "https://docs.qq.com/sheet/300000000$NtrQNCVnVIJu",
        "output_dir": tmp_path / "run-20261009",
    }
    values.update(overrides)
    return TencentDocsExportConfig(**values)


def _successful_api_responses(xlsx: bytes, *, file_url: str | None = None) -> list[tuple[str, FakeResponse]]:
    return [
        ("/v1/export/check", _json_response({"ret": 0})),
        ("/v1/export/export_office", _json_response({"ret": 0, "operationId": "operation-1"})),
        (
            "/v1/export/query_progress",
            _json_response(
                {
                    "ret": 0,
                    "status": "Done",
                    "file_url": file_url or f"https://{COS_HOST}/export.xlsx?sign=signed-value",
                    "file_name": "原始导出.xlsx",
                    "file_size": len(xlsx),
                }
            ),
        ),
        ("/export.xlsx", FakeResponse(xlsx)),
    ]


def test_downloads_fresh_export_and_saves_valid_xlsx_without_sending_cookies_to_cos(tmp_path: Path) -> None:
    xlsx = _xlsx_bytes()
    transport = ScriptedTransport(_successful_api_responses(xlsx))

    receipt = download_tencent_doc_xlsx(_config(tmp_path), _cookie_file(tmp_path), transport=transport)

    assert receipt.path.parent == tmp_path / "run-20261009"
    assert receipt.path.suffix == ".xlsx"
    assert receipt.path.read_bytes() == xlsx
    assert receipt.size_bytes == len(xlsx)
    assert receipt.sha256 == hashlib.sha256(xlsx).hexdigest()
    assert not list(receipt.path.parent.glob("*.part"))
    assert transport.responses == []

    docs_requests = transport.requests[:3]
    assert all(request.get_header("Cookie") == "sid=captured-value" for request in docs_requests)
    assert all(request.get_header("Referer") == "https://docs.qq.com/sheet/300000000$NtrQNCVnVIJu" for request in docs_requests)
    assert transport.requests[3].get_header("Cookie") is None
    assert transport.requests[3].get_header("Referer") is None
    assert parse_qs(transport.requests[0].data.decode("utf-8")) == {
        "docId": ["300000000$NtrQNCVnVIJu"],
        "dver": ["3.0.0"],
    }
    assert parse_qs(transport.requests[1].data.decode("utf-8")) == {
        "exportType": ["0"],
        "switches": ['{"embedFonts":false}'],
        "exportSource": ["client"],
        "docId": ["300000000$NtrQNCVnVIJu"],
        "version": ["2"],
    }


def test_expired_docs_cookies_stop_before_network_request(tmp_path: Path) -> None:
    expired = [{"name": "sid", "value": "old", "domain": ".docs.qq.com", "expires": 1}]
    transport = ScriptedTransport([])

    with pytest.raises(TencentDocsDownloadError, match="session may have expired"):
        download_tencent_doc_xlsx(_config(tmp_path), _cookie_file(tmp_path, expired), transport=transport)

    assert transport.requests == []


def test_http_auth_failure_reports_expired_session_without_response_contents(tmp_path: Path) -> None:
    transport = ScriptedTransport([("/v1/export/check", _json_response({"error": "private-token"}, status=401))])

    with pytest.raises(TencentDocsDownloadError, match="session expired") as error:
        download_tencent_doc_xlsx(_config(tmp_path), _cookie_file(tmp_path), transport=transport)

    assert "private-token" not in str(error.value)
    assert len(transport.requests) == 1


def test_nonzero_ret_with_login_message_is_safe_and_clear(tmp_path: Path) -> None:
    transport = ScriptedTransport(
        [("/v1/export/check", _json_response({"ret": 1001, "msg": "Please login token=private-token"}))]
    )

    with pytest.raises(TencentDocsDownloadError, match="session expired") as error:
        download_tencent_doc_xlsx(_config(tmp_path), _cookie_file(tmp_path), transport=transport)

    assert "private-token" not in str(error.value)


def test_pending_export_stops_at_bounded_timeout(tmp_path: Path) -> None:
    transport = ScriptedTransport(
        [
            ("/v1/export/check", _json_response({"ret": 0})),
            ("/v1/export/export_office", _json_response({"ret": 0, "operationId": "operation-1"})),
            ("/v1/export/query_progress", _json_response({"ret": 0, "status": "Running", "progress": 20})),
            ("/v1/export/query_progress", _json_response({"ret": 0, "status": "Running", "progress": 60})),
        ]
    )
    clock_value = [0.0]

    def clock() -> float:
        return clock_value[0]

    def sleep(seconds: float) -> None:
        clock_value[0] += seconds

    with pytest.raises(TimeoutError, match="did not finish within 2 seconds"):
        download_tencent_doc_xlsx(
            _config(tmp_path, timeout_sec=2, poll_interval_sec=1),
            _cookie_file(tmp_path),
            transport=transport,
            clock=clock,
            sleeper=sleep,
        )

    assert [urlsplit(request.full_url).path for request in transport.requests].count("/v1/export/query_progress") == 2
    assert not (tmp_path / "run-20261009").exists()


def test_incomplete_zip_is_removed_and_never_reported_as_downloaded(tmp_path: Path) -> None:
    transport = ScriptedTransport(_successful_api_responses(b"not an xlsx"))

    with pytest.raises(TencentDocsDownloadError, match="not a valid XLSX"):
        download_tencent_doc_xlsx(_config(tmp_path), _cookie_file(tmp_path), transport=transport)

    output_dir = tmp_path / "run-20261009"
    assert list(output_dir.iterdir()) == []


def test_signed_file_url_must_use_the_observed_cos_host(tmp_path: Path) -> None:
    xlsx = _xlsx_bytes()
    transport = ScriptedTransport(
        _successful_api_responses(xlsx, file_url="https://attacker.example/export.xlsx?sign=private-token")[:3]
    )

    with pytest.raises(TencentDocsDownloadError, match="outside the approved COS host") as error:
        download_tencent_doc_xlsx(_config(tmp_path), _cookie_file(tmp_path), transport=transport)

    assert "private-token" not in str(error.value)
    assert len(transport.requests) == 3
    assert not (tmp_path / "run-20261009").exists()
