from __future__ import annotations

import argparse
import hashlib
from http.client import HTTPException
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import ssl
import tempfile
import time
from typing import Callable, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
import uuid
import zipfile
import zlib
from xml.etree import ElementTree


DOCS_HOST = "docs.qq.com"
COS_HOST = "docs-import-export-1251316161.cos.ap-guangzhou.myqcloud.com"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
_MAX_JSON_BYTES = 2 * 1024 * 1024
_SHEET_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_COOKIE_NAME_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_SAFE_FILENAME_RE = re.compile(r"[^\w.-]+", flags=re.UNICODE)
_AUTH_HINTS = ("login", "unauthorized", "auth", "expired", "登录", "未登录", "认证", "过期")


class TencentDocsDownloadError(RuntimeError):
    """A safe, user-facing error from a Tencent Docs export or download."""


@dataclass(frozen=True)
class TencentDocsExportConfig:
    doc_id: str
    page_url: str
    output_dir: Path
    timeout_sec: float = 240.0
    poll_interval_sec: float = 2.0
    request_timeout_sec: float = 30.0
    user_agent: str = DEFAULT_USER_AGENT
    ca_file: Path | None = None

    def __post_init__(self) -> None:
        doc_id = self.doc_id.strip()
        if not doc_id or any(ord(char) < 32 for char in doc_id):
            raise ValueError("doc_id must be a non-empty document identifier")
        object.__setattr__(self, "doc_id", doc_id)

        try:
            page = urlsplit(self.page_url)
        except (TypeError, ValueError) as exc:
            raise ValueError("page_url must be a Tencent Docs HTTPS page URL") from exc
        try:
            page_port = page.port
        except ValueError as exc:
            raise ValueError("page_url must be a Tencent Docs HTTPS page URL") from exc
        if (
            page.scheme != "https"
            or page.hostname != DOCS_HOST
            or page_port not in (None, 443)
            or page.username is not None
            or page.password is not None
        ):
            raise ValueError("page_url must use https://docs.qq.com")
        if not self.user_agent or any(char in self.user_agent for char in "\r\n"):
            raise ValueError("user_agent must be a non-empty single-line value")
        for name, value in (
            ("timeout_sec", self.timeout_sec),
            ("poll_interval_sec", self.poll_interval_sec),
            ("request_timeout_sec", self.request_timeout_sec),
        ):
            try:
                valid = math.isfinite(float(value)) and value > 0
            except (TypeError, ValueError):
                valid = False
            if not valid:
                raise ValueError(f"{name} must be a positive finite number")


@dataclass(frozen=True)
class DownloadReceipt:
    path: Path
    size_bytes: int
    sha256: str


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _default_transport(request: Request, *, timeout: float, ca_file: Path | None = None):
    context = ssl.create_default_context(cafile=str(ca_file) if ca_file is not None else None)
    opener = build_opener(_NoRedirectHandler(), HTTPSHandler(context=context))
    return opener.open(request, timeout=timeout)


class TencentDocsDownloader:
    def __init__(
        self,
        config: TencentDocsExportConfig,
        *,
        transport: Callable[..., object] = _default_transport,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self._transport = transport
        self._clock = clock
        self._sleep = sleeper

    def download(self, cookie_file: Path) -> DownloadReceipt:
        cookies = _read_cookies(cookie_file)
        self._post_form("/v1/export/check", {"docId": self.config.doc_id, "dver": "3.0.0"}, cookies)
        submitted = self._post_form(
            "/v1/export/export_office",
            {
                "exportType": "0",
                "switches": json.dumps({"embedFonts": False}, separators=(",", ":")),
                "exportSource": "client",
                "docId": self.config.doc_id,
                "version": "2",
            },
            cookies,
        )
        operation_id = submitted.get("operationId")
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise TencentDocsDownloadError("Tencent Docs export response is missing operationId")

        deadline = self._clock() + self.config.timeout_sec
        max_polls = max(1, math.ceil(self.config.timeout_sec / self.config.poll_interval_sec) + 1)
        for attempt in range(max_polls):
            if self._clock() >= deadline:
                break
            progress = self._get_progress(operation_id, cookies)
            status = progress.get("status")
            if isinstance(status, str) and status.casefold() == "done":
                file_url = progress.get("file_url")
                file_name = progress.get("file_name")
                if not isinstance(file_url, str) or not isinstance(file_name, str) or not file_name:
                    raise TencentDocsDownloadError("Tencent Docs completed export is missing file metadata")
                expected_size = _expected_file_size(progress.get("file_size"))
                return self._download_file(file_url, file_name, expected_size)
            if isinstance(status, str) and status.casefold() in {"failed", "error", "cancelled", "canceled"}:
                raise TencentDocsDownloadError("Tencent Docs export task failed")

            remaining = deadline - self._clock()
            if remaining <= 0:
                break
            if attempt + 1 < max_polls:
                self._sleep(min(self.config.poll_interval_sec, remaining))

        raise TimeoutError(f"Tencent Docs export did not finish within {self.config.timeout_sec:g} seconds")

    def _docs_headers(self, path: str, cookies: list[dict]) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Referer": self.config.page_url,
            "User-Agent": self.config.user_agent,
        }
        cookie_header = _cookie_header(cookies, path)
        if cookie_header:
            headers["Cookie"] = cookie_header
        return headers

    def _post_form(self, path: str, fields: dict[str, str], cookies: list[dict]) -> dict:
        headers = self._docs_headers(path, cookies)
        headers["Content-Type"] = "application/x-www-form-urlencoded;charset=UTF-8"
        request = Request(
            f"https://{DOCS_HOST}{path}",
            data=urlencode(fields).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        payload = self._json_request(request, "export request")
        _check_ret(payload, "export request")
        return payload

    def _get_progress(self, operation_id: str, cookies: list[dict]) -> dict:
        path = "/v1/export/query_progress"
        query = urlencode({"operationId": operation_id})
        request = Request(
            f"https://{DOCS_HOST}{path}?{query}",
            headers=self._docs_headers(path, cookies),
            method="GET",
        )
        payload = self._json_request(request, "export progress query")
        _check_ret(payload, "export progress query")
        return payload

    def _json_request(self, request: Request, stage: str) -> dict:
        status, response = self._open(request, stage)
        try:
            if 300 <= status < 400:
                raise TencentDocsDownloadError(f"Tencent Docs {stage} returned a redirect; redirects are refused")
            if status in {401, 403}:
                raise TencentDocsDownloadError(f"Tencent Docs session expired or access was denied (HTTP {status})")
            if not 200 <= status < 300:
                raise TencentDocsDownloadError(f"Tencent Docs {stage} failed (HTTP {status})")
            body = response.read(_MAX_JSON_BYTES + 1)
        finally:
            response.close()

        if len(body) > _MAX_JSON_BYTES:
            raise TencentDocsDownloadError(f"Tencent Docs {stage} returned an oversized response")
        try:
            payload = json.loads(body.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            if body.lstrip().startswith(b"<"):
                raise TencentDocsDownloadError(
                    "Tencent Docs returned a login page; the captured session may have expired"
                ) from None
            raise TencentDocsDownloadError(f"Tencent Docs {stage} returned invalid JSON") from None
        if not isinstance(payload, dict):
            raise TencentDocsDownloadError(f"Tencent Docs {stage} returned an invalid JSON object")
        if "ret" not in payload:
            raise TencentDocsDownloadError(f"Tencent Docs {stage} response is missing ret")
        return payload

    def _open(self, request: Request, stage: str):
        try:
            response = self._transport(
                request,
                timeout=self.config.request_timeout_sec,
                ca_file=self.config.ca_file,
            )
        except HTTPError as exc:
            return exc.code, exc
        except (URLError, TimeoutError, OSError, HTTPException):
            raise TencentDocsDownloadError(f"Tencent Docs {stage} network request failed") from None
        try:
            status = int(response.status)
        except (AttributeError, TypeError, ValueError):
            status = int(response.getcode())
        return status, response

    def _download_file(self, file_url: str, file_name: str, expected_size: int | None) -> DownloadReceipt:
        url = _validated_file_url(file_url)
        output_dir = self.config.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        final_path = _new_output_path(output_dir, file_name)
        request = Request(
            url,
            headers={
                "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*",
                "User-Agent": self.config.user_agent,
            },
            method="GET",
        )
        status, response = self._open(request, "XLSX download")
        if 300 <= status < 400:
            response.close()
            raise TencentDocsDownloadError("Tencent Docs file download returned a redirect; redirects are refused")
        if status in {401, 403}:
            response.close()
            raise TencentDocsDownloadError(f"Tencent Docs file download was denied (HTTP {status})")
        if not 200 <= status < 300:
            response.close()
            raise TencentDocsDownloadError(f"Tencent Docs file download failed (HTTP {status})")

        try:
            file_descriptor, temporary_name = tempfile.mkstemp(
                prefix=".tencent-docs-", suffix=".part", dir=output_dir
            )
        except OSError:
            response.close()
            raise TencentDocsDownloadError("Tencent Docs could not create a temporary output file") from None
        temporary_path = Path(temporary_name)
        digest = hashlib.sha256()
        size = 0
        try:
            with os.fdopen(file_descriptor, "wb") as output:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
            response.close()
            if expected_size is not None and size != expected_size:
                raise TencentDocsDownloadError("Tencent Docs file size did not match its export metadata")
            _validate_xlsx(temporary_path)
            try:
                os.link(temporary_path, final_path)
            except FileExistsError:
                raise TencentDocsDownloadError("Tencent Docs output filename collided with an existing file") from None
            except OSError:
                raise TencentDocsDownloadError("Tencent Docs could not finalize the XLSX output file") from None
            return DownloadReceipt(path=final_path, size_bytes=size, sha256=digest.hexdigest())
        except TencentDocsDownloadError:
            raise
        except (OSError, HTTPException):
            raise TencentDocsDownloadError("Tencent Docs file download failed while receiving the XLSX") from None
        except (zipfile.BadZipFile, ElementTree.ParseError, zlib.error):
            raise TencentDocsDownloadError("Tencent Docs download was incomplete or was not a valid XLSX workbook") from None
        finally:
            try:
                response.close()
            finally:
                temporary_path.unlink(missing_ok=True)


def _read_cookies(cookie_file: Path) -> list[dict]:
    try:
        document = json.loads(Path(cookie_file).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise TencentDocsDownloadError("cookie file is unreadable or is not valid JSON") from None
    if not isinstance(document, dict) or not isinstance(document.get("cookies"), list):
        raise TencentDocsDownloadError('cookie file must contain a "cookies" array')

    active: list[dict] = []
    now = time.time()
    for cookie in document["cookies"]:
        if not isinstance(cookie, dict):
            raise TencentDocsDownloadError("cookie file contains an invalid cookie entry")
        domain = cookie.get("domain")
        if not isinstance(domain, str) or domain.lstrip(".").lower() != DOCS_HOST:
            continue
        name = cookie.get("name")
        value = cookie.get("value")
        if not isinstance(name, str) or not _COOKIE_NAME_RE.fullmatch(name):
            raise TencentDocsDownloadError("cookie file contains an invalid Tencent Docs cookie name")
        if not isinstance(value, str) or any(char in value for char in "\r\n;"):
            raise TencentDocsDownloadError("cookie file contains an invalid Tencent Docs cookie value")
        expires = cookie.get("expires")
        if expires is None:
            expires = cookie.get("expirationDate")
        if expires is not None:
            try:
                expiry = float(expires)
            except (TypeError, ValueError):
                raise TencentDocsDownloadError("cookie file contains an invalid cookie expiry") from None
            if not math.isfinite(expiry):
                raise TencentDocsDownloadError("cookie file contains an invalid cookie expiry")
            if expiry >= 0 and expiry <= now:
                continue
        cookie_path = cookie.get("path", "/")
        if not isinstance(cookie_path, str) or not cookie_path.startswith("/"):
            continue
        active.append({"name": name, "value": value, "path": cookie_path})
    if not active:
        raise TencentDocsDownloadError("cookie file has no active docs.qq.com cookies; the session may have expired")
    return active


def _cookie_header(cookies: list[dict], request_path: str) -> str:
    pairs: list[str] = []
    for cookie in cookies:
        cookie_path = cookie["path"]
        path_matches = request_path == cookie_path or request_path.startswith(cookie_path.rstrip("/") + "/")
        if cookie_path == "/":
            path_matches = True
        if path_matches:
            pairs.append(f"{cookie['name']}={cookie['value']}")
    return "; ".join(pairs)


def _check_ret(payload: dict, stage: str) -> None:
    ret = payload.get("ret")
    if (isinstance(ret, int) and not isinstance(ret, bool) and ret == 0) or ret == "0":
        return
    message = payload.get("message", payload.get("msg", ""))
    if isinstance(message, str) and any(hint in message.casefold() for hint in _AUTH_HINTS):
        raise TencentDocsDownloadError(
            f"Tencent Docs session expired or access was denied during {stage}"
        )
    raise TencentDocsDownloadError(f"Tencent Docs {stage} was rejected (ret was not 0)")


def _expected_file_size(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TencentDocsDownloadError("Tencent Docs export response has invalid file_size metadata")
    try:
        size = int(value)
    except (TypeError, ValueError):
        raise TencentDocsDownloadError("Tencent Docs export response has invalid file_size metadata") from None
    if size < 0 or (isinstance(value, float) and not value.is_integer()):
        raise TencentDocsDownloadError("Tencent Docs export response has invalid file_size metadata")
    return size


def _validated_file_url(file_url: str) -> str:
    try:
        parts = urlsplit(file_url)
        port = parts.port
    except (TypeError, ValueError):
        raise TencentDocsDownloadError("Tencent Docs export returned an invalid file URL") from None
    if (
        parts.scheme != "https"
        or parts.hostname != COS_HOST
        or parts.username is not None
        or parts.password is not None
        or port not in (None, 443)
        or not parts.path
        or parts.fragment
    ):
        raise TencentDocsDownloadError("Tencent Docs export returned a file URL outside the approved COS host")
    return file_url


def _safe_stem(file_name: str) -> str:
    basename = file_name.replace("\\", "/").rsplit("/", 1)[-1]
    stem = basename.rsplit(".", 1)[0] if "." in basename else basename
    stem = _SAFE_FILENAME_RE.sub("_", stem).strip("._-")
    return stem[:80] or "tencent_docs_export"


def _new_output_path(output_dir: Path, file_name: str) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    unique = uuid.uuid4().hex[:10]
    return output_dir / f"{_safe_stem(file_name)}_{timestamp}_{unique}.xlsx"


def _validate_xlsx(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise zipfile.BadZipFile("corrupt member")
        names = set(archive.namelist())
        if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
            raise zipfile.BadZipFile("required XLSX entries are missing")
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        if not workbook.findall(f".//{_SHEET_NS}sheet"):
            raise zipfile.BadZipFile("workbook has no sheets")


def download_tencent_doc_xlsx(
    config: TencentDocsExportConfig,
    cookie_file: Path,
    *,
    transport: Callable[..., object] = _default_transport,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> DownloadReceipt:
    """Create a fresh Tencent Docs export job and save its XLSX in output_dir."""
    return TencentDocsDownloader(config, transport=transport, clock=clock, sleeper=sleeper).download(cookie_file)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export one Tencent Docs document to a local XLSX file")
    parser.add_argument("--doc-id", required=True, help="Tencent Docs document id")
    parser.add_argument("--page-url", required=True, help="The document URL used as the export Referer")
    parser.add_argument("--cookie-file", type=Path, required=True, help="JSON file containing a Chrome cookies array")
    parser.add_argument("--output-dir", type=Path, required=True, help="Run-specific output directory")
    parser.add_argument("--timeout-sec", type=float, default=240.0)
    parser.add_argument("--poll-interval-sec", type=float, default=2.0)
    parser.add_argument("--request-timeout-sec", type=float, default=30.0)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument("--ca-file", type=Path, help="Optional CA bundle for TLS certificate verification")
    args = parser.parse_args(argv)

    try:
        config = TencentDocsExportConfig(
            doc_id=args.doc_id,
            page_url=args.page_url,
            output_dir=args.output_dir,
            timeout_sec=args.timeout_sec,
            poll_interval_sec=args.poll_interval_sec,
            request_timeout_sec=args.request_timeout_sec,
            user_agent=args.user_agent,
            ca_file=args.ca_file,
        )
        receipt = download_tencent_doc_xlsx(config, args.cookie_file)
    except (TencentDocsDownloadError, TimeoutError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {
                "status": "downloaded",
                "path": str(receipt.path.resolve()),
                "size_bytes": receipt.size_bytes,
                "sha256": receipt.sha256,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
