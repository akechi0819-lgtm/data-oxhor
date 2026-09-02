from __future__ import annotations

import base64
import copy
from dataclasses import dataclass, field
from datetime import date, datetime
import io
from pathlib import Path
import platform
import time
from typing import Iterable, Protocol
import zipfile

from data_layer.auth_sessions import AuthSessionPaths, write_auth_session


DEFAULT_ORDER_FILTER_META = {
    "分配时间": {
        "fdId": "vbd72e8252b6a4959bd2d8e4",
        "dsId": "i2e269a4ea5d34590ad16727",
        "cdId": "tb6163fe63c3346039f72bd6",
        "fdType": "DATE",
        "filterType": "BT",
        "sourceCdId": "o443253f328874c938238599",
    },
}

DEFAULT_CASH_FILTERS = [
    {
        "name": "业务日期",
        "fdId": "q9a11a0ad4aa541c5a528121",
        "dsId": "of4905b0c643e4df8881f8e1",
        "cdId": "l7c4c81c230394601874711e",
        "fdType": "DATE",
        "filterType": "BT",
        "sourceCdId": "e26aad5d30d4d4cd1b0b200d",
    },
]


@dataclass(frozen=True)
class BIExportConfig:
    page_url: str = "https://bibr.staff.xdf.cn/page/c72ee6c698a5d416ba55733a"
    browser_profile_dir: Path = Path("data_layer/storage/browser_profiles/bi")
    auth_session_paths: AuthSessionPaths = field(default_factory=lambda: AuthSessionPaths(Path("."), "bi"))
    download_dir: Path = Path("data_layer/storage/raw/bi_downloads")
    export_timeout_sec: int = 240
    max_export_attempts: int = 2
    retry_backoff_sec: float = 5.0
    poll_log_interval_sec: float = 30.0
    default_start_date: str = "2025-06-01"
    order_card_id: str = "tb6163fe63c3346039f72bd6"
    order_filter_meta: dict[str, dict] = field(default_factory=lambda: copy.deepcopy(DEFAULT_ORDER_FILTER_META))
    cash_page_id: str = "u9325e10935054279894536e"
    cash_card_id: str = "l7c4c81c230394601874711e"
    cash_filters: list[dict] = field(default_factory=lambda: copy.deepcopy(DEFAULT_CASH_FILTERS))
    api_user_id: str = "bGl1bWluZ3poaTJAeGRmLmNu"
    api_x_dom_id: str = "Z3VhbmJp"


@dataclass(frozen=True)
class BIExportRequest:
    target: str
    api: str
    headers: dict[str, str]
    payload: dict


@dataclass(frozen=True)
class ExportTask:
    target: str
    task_id: str
    file_name: str


@dataclass(frozen=True)
class DownloadedArtifact:
    target: str
    path: Path


class BIExportClient(Protocol):
    def trigger_export(self, request: BIExportRequest) -> ExportTask:
        ...

    def poll_download(self, task: ExportTask, config: BIExportConfig) -> Path:
        ...


def build_common_headers(config: BIExportConfig) -> dict[str, str]:
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
    }
    if config.api_user_id:
        headers["user-id"] = config.api_user_id
    if config.api_x_dom_id:
        headers["x-dom-id"] = config.api_x_dom_id
    return headers


def build_order_export_request(
    config: BIExportConfig,
    start_date: str,
    end_date: str,
    team: str,
) -> BIExportRequest:
    filters = []
    for name, meta in config.order_filter_meta.items():
        if meta.get("fdType") == "DATE":
            filters.append({**meta, "name": name, "filterValue": [start_date, end_date], "displayValue": [start_date, end_date]})
    return BIExportRequest(
        target="orders",
        api=f"/api/write/file/{config.order_card_id}?typeOp=EXCEL",
        headers=build_common_headers(config),
        payload={
            "filters": filters,
            "treeFilters": [],
            "dynamicParams": [],
            "dynamicFieldFilters": [],
            "combinationFilters": [],
            "layerTreeFilters": [],
            "saveFilters": False,
        },
    )


def build_cash_export_request(config: BIExportConfig, start_date: str, end_date: str) -> BIExportRequest:
    filters = copy.deepcopy(config.cash_filters)
    for item in filters:
        if item.get("fdType") == "DATE":
            item["filterValue"] = [start_date, end_date]
            item["displayValue"] = [start_date, end_date]
    return BIExportRequest(
        target="cash",
        api="/api/batchExportCardExcel",
        headers=build_common_headers(config),
        payload={
            "pgId": config.cash_page_id,
            "cards": [
                {
                    "cdId": config.cash_card_id,
                    "saveFilters": False,
                    "filters": filters,
                    "treeFilters": [],
                    "dynamicParams": [],
                    "dynamicFieldFilters": [],
                    "combinationFilters": [],
                    "layerTreeFilters": [],
                }
            ],
            "exportType": "NORMAL",
            "saveType": "MANY_SHEET",
        },
    )


def _task_from_response(target: str, body: dict) -> ExportTask:
    response = body.get("response", body)
    if not response.get("taskId") or not response.get("fileName"):
        raise RuntimeError(f"{target} export response missing taskId/fileName: {body}")
    return ExportTask(target=target, task_id=str(response["taskId"]), file_name=str(response["fileName"]))


def _save_b64_file(data: dict, out_dir: Path, prefix: str) -> Path | None:
    if not isinstance(data, dict) or not data.get("isFile") or not data.get("b64"):
        return None
    payload = base64.b64decode(data["b64"])
    if not _is_valid_xlsx_payload(payload):
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"{prefix}_{timestamp}.xlsx"
    path.write_bytes(payload)
    return path


def _is_valid_xlsx_payload(payload: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            return archive.testzip() is None and "[Content_Types].xml" in archive.namelist()
    except zipfile.BadZipFile:
        return False


def _poll_state_label(data: dict) -> str:
    """Return a low-cardinality state label without logging BI response contents."""
    if data.get("isFile"):
        return "file_ready"
    if not data.get("ok", True):
        status = data.get("status")
        return f"http_error_{status}" if status else "request_error"
    return "pending"


class PlaywrightBIExportClient:
    def __init__(self) -> None:
        self._playwright = None
        self._context = None
        self._page = None

    def __enter__(self) -> PlaywrightBIExportClient:
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._context is not None:
            self._context.close()
        if self._playwright is not None:
            self._playwright.stop()

    def open(self, config: BIExportConfig) -> None:
        if self._playwright is None:
            raise RuntimeError("PlaywrightBIExportClient must be used as a context manager")
        config.browser_profile_dir.mkdir(parents=True, exist_ok=True)
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(config.browser_profile_dir),
            headless=False,
            accept_downloads=True,
            **_local_chrome_launch_kwargs(),
        )
        self._page = self._context.new_page()
        self._page.goto(config.page_url, wait_until="domcontentloaded")
        self._page.wait_for_timeout(3000)
        self._wait_for_login()
        self._export_auth_session(config)

    def _export_auth_session(self, config: BIExportConfig) -> None:
        context = self._context
        page = self._require_page()
        if context is None:
            raise RuntimeError("BI browser context is not open")
        local_storage = page.evaluate(
            """() => {
                const result = {};
                for (let index = 0; index < localStorage.length; index++) {
                    const key = localStorage.key(index);
                    result[key] = localStorage.getItem(key);
                }
                return result;
            }"""
        )
        if not isinstance(local_storage, dict):
            raise RuntimeError("BI localStorage export returned an invalid object")
        write_auth_session(
            "bi",
            cookies=context.cookies(),
            local_storage=local_storage,
            paths=config.auth_session_paths,
        )

    def _wait_for_login(self) -> None:
        page = self._require_page()
        bi_host = "bibr.staff.xdf.cn/page"
        if bi_host in (page.url or "").lower():
            return
        print("BI login required; complete login in the opened browser window.")
        for index in range(120):
            page.wait_for_timeout(1000)
            if bi_host in (page.url or "").lower():
                return
            if index % 15 == 0 and index > 0:
                print(f"waiting for BI login... {index}s")
        raise TimeoutError("BI login did not complete within 120 seconds")

    def trigger_export(self, request: BIExportRequest) -> ExportTask:
        page = self._require_page()
        result = page.evaluate(
            """async ({api, headers, payload}) => {
                const resp = await fetch(api, {method:'POST', credentials:'include', headers, body:JSON.stringify(payload)});
                let data = {}; try { data = await resp.json(); } catch(e) {}
                return {ok:resp.ok, status:resp.status, body:data};
            }""",
            {"api": request.api, "headers": request.headers, "payload": request.payload},
        )
        if not result.get("ok"):
            raise RuntimeError(f"{request.target} export failed: HTTP {result.get('status')}")
        return _task_from_response(request.target, result.get("body", {}) or {})

    def poll_download(self, task: ExportTask, config: BIExportConfig) -> Path:
        page = self._require_page()
        started_at = time.time()
        deadline = started_at + config.export_timeout_sec
        url = f"/api/export/file/common/{task.task_id}"
        payload = {
            "downloadFileName": task.file_name,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "fileNameWithTime": True,
        }
        headers = build_common_headers(config)
        prefix = "工单表" if task.target == "orders" else "现金表"
        last_state: str | None = None
        last_log_at = 0.0
        while time.time() < deadline:
            data = page.evaluate(
                """async ({url, headers, payload}) => {
                    try {
                        const resp = await fetch(url, {method:'POST', credentials:'include', headers, body:JSON.stringify(payload)});
                        const ct = (resp.headers.get('content-type') || '').toLowerCase();
                        const cd = (resp.headers.get('content-disposition') || '').toLowerCase();
                        const isFile = ct.includes('spreadsheet') || ct.includes('excel') || ct.includes('octet-stream') || cd.includes('attachment');
                        if (!resp.ok) return {ok:false, status:resp.status};
                        if (isFile) {
                            const buf = await resp.arrayBuffer();
                            const bytes = new Uint8Array(buf);
                            const chunk = 0x8000;
                            let binary = '';
                            for (let i = 0; i < bytes.length; i += chunk) {
                                const part = bytes.subarray(i, i + chunk);
                                binary += String.fromCharCode.apply(null, part);
                            }
                            return {ok:true, isFile:true, b64:btoa(binary)};
                        }
                        let json = null; try { json = await resp.json(); } catch(e) {}
                        return {ok:true, isFile:false, json};
                    } catch (e) { return {ok:false, error:String(e)}; }
                }""",
                {"url": url, "headers": headers, "payload": payload},
            )
            path = _save_b64_file(data, config.download_dir, prefix)
            if path:
                elapsed = int(time.time() - started_at)
                print(f"[BI] target={task.target} task_id={task.task_id} state=file_ready elapsed={elapsed}s")
                return path
            state = _poll_state_label(data)
            now = time.time()
            if last_state != state or now - last_log_at >= config.poll_log_interval_sec:
                elapsed = int(now - started_at)
                print(f"[BI] target={task.target} task_id={task.task_id} state={state} elapsed={elapsed}s")
                last_state = state
                last_log_at = now
            time.sleep(5)
        raise TimeoutError(
            f"{task.target} BI export timed out after {config.export_timeout_sec}s "
            f"(task_id={task.task_id})"
        )

    def _require_page(self):
        if self._page is None:
            raise RuntimeError("BI page is not open")
        return self._page


def _local_chrome_launch_kwargs() -> dict[str, str]:
    if platform.system() == "Darwin":
        path = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        if path.exists():
            return {"executable_path": str(path)}
    return {}


def run_bi_download(
    config: BIExportConfig | None = None,
    client: BIExportClient | None = None,
    targets: Iterable[str] = ("orders", "cash"),
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[DownloadedArtifact]:
    config = config or BIExportConfig()
    start_date = start_date or config.default_start_date
    end_date = end_date or date.today().isoformat()
    selected = list(targets)
    config.download_dir.mkdir(parents=True, exist_ok=True)

    requests: list[BIExportRequest] = []
    if "orders" in selected:
        requests.append(build_order_export_request(config, start_date=start_date, end_date=end_date, team=""))
    if "cash" in selected:
        if not config.cash_card_id:
            raise ValueError("BI cash card id is not configured")
        requests.append(build_cash_export_request(config, start_date=start_date, end_date=end_date))

    artifacts: list[DownloadedArtifact] = []
    preexisting_paths = {path.resolve() for path in config.download_dir.glob("*") if path.is_file()}
    created_paths: list[Path] = []

    def download_all(active_client: BIExportClient) -> list[DownloadedArtifact]:
        for request in requests:
            artifact = _download_request_with_retries(client=active_client, request=request, config=config)
            artifacts.append(artifact)
            if artifact.path.resolve() not in preexisting_paths:
                created_paths.append(artifact.path)
        return artifacts

    try:
        if client is not None:
            return download_all(client)

        with PlaywrightBIExportClient() as browser_client:
            browser_client.open(config)
            return download_all(browser_client)
    except Exception:
        # Never leave a newly downloaded half-pair that a later latest-file fallback
        # could mistake for a complete orders/cash snapshot.
        for path in created_paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _download_request_with_retries(
    *,
    client: BIExportClient,
    request: BIExportRequest,
    config: BIExportConfig,
) -> DownloadedArtifact:
    max_attempts = max(1, int(config.max_export_attempts))
    last_error: TimeoutError | None = None
    for attempt in range(1, max_attempts + 1):
        task: ExportTask | None = None
        try:
            task = client.trigger_export(request)
            print(
                f"[BI] target={request.target} attempt={attempt}/{max_attempts} "
                f"task_id={task.task_id} state=submitted"
            )
            path = client.poll_download(task, config).resolve()
            return DownloadedArtifact(task.target, path)
        except TimeoutError as exc:
            last_error = exc
            if attempt >= max_attempts:
                raise TimeoutError(
                    f"{request.target} BI export failed after {max_attempts} attempts: {exc}"
                ) from exc
            task_id = task.task_id if task is not None else "unknown"
            print(
                f"[BI] target={request.target} attempt={attempt}/{max_attempts} "
                f"task_id={task_id} state=retrying reason=timeout"
            )
            if config.retry_backoff_sec > 0:
                time.sleep(config.retry_backoff_sec)
    assert last_error is not None
    raise last_error
