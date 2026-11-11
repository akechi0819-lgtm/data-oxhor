from __future__ import annotations

import base64
import copy
from dataclasses import dataclass, field
from datetime import date, datetime
import io
import hashlib
import json
from pathlib import Path
import platform
import time
from typing import Iterable, Protocol
import zipfile

from dateutil.relativedelta import relativedelta

from data_acquisition.auth.auth_sessions import AuthSessionPaths, write_auth_session


def _rolling_default_start_date() -> str:
    """ISO date = today minus 6 calendar months (export window start)."""
    return (date.today() - relativedelta(months=6)).isoformat()


DEFAULT_ORDER_FILTER_META = {
    "分配日期": {
        "fdId": "bf9ab43250ab34a98836dcf4",
        "dsId": "i2e269a4ea5d34590ad16727",
        "cdId": "j7378d2612e2242ab85e3140",
        "fdType": "DATE",
        "filterType": "BT",
        "sourceCdId": "xa6e577520eb543e7913a773",
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
    page_url: str = "https://bibr.staff.xdf.cn/page/dc1bca538e57f49038476541"
    browser_profile_dir: Path = Path("data_acquisition/storage/browser_profiles/bi")
    auth_session_paths: AuthSessionPaths = field(default_factory=lambda: AuthSessionPaths(Path("."), "bi"))
    download_dir: Path = Path("data_acquisition/storage/raw/bi_downloads")
    export_timeout_sec: int = 900
    poll_log_interval_sec: float = 30.0
    default_start_date: str = field(default_factory=_rolling_default_start_date)
    order_card_id: str = "j7378d2612e2242ab85e3140"
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
    start_date: str | None = None
    end_date: str | None = None
    mode: str = "full"


class OfficialExportFailed(RuntimeError):
    """The official history proves failure, or a finished task has an invalid workbook."""

    def __init__(self, task: ExportTask, status: str):
        self.task = task
        self.status = status
        super().__init__(f"{task.target} export {status} (task_id={task.task_id})")


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
        api="/api/batchExportCardExcel",
        headers=build_common_headers(config),
        payload={
            "pgId": config.page_url.rstrip("/").rsplit("/", 1)[-1],
            "cards": [
                {
                    "cdId": config.order_card_id,
                    "saveFilters": False,
                    "filters": filters,
                    "treeFilters": [],
                    "dynamicParams": [],
                    "dynamicFieldFilters": [],
                    "combinationFilters": [],
                    "layerTreeFilters": [],
                }
            ],
            "exportType": "PIVOT",
            "saveType": "MANY_SHEET",
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


def _payload_reject_reason(payload: bytes) -> str:
    if not payload:
        return "empty"
    head = payload[:120]
    if head.lstrip().startswith((b"{", b"[")):
        return f"json head={head!r}"
    if head.lstrip().startswith((b"<", b"<!")):
        return f"html head={head!r}"
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = archive.namelist()
            return (
                f"zip size={len(payload)} testzip={archive.testzip()!r} "
                f"has_ct={'[Content_Types].xml' in names} names={names[:12]}"
            )
    except zipfile.BadZipFile as exc:
        return f"not_zip size={len(payload)} magic={payload[:16]!r} err={exc}"


def _save_b64_file(data: dict, out_dir: Path, prefix: str) -> Path | None:
    if not isinstance(data, dict) or not data.get("isFile") or not data.get("b64"):
        return None
    payload = base64.b64decode(data["b64"])
    if not _is_valid_xlsx_payload(payload):
        print(f"[BI] rejected {prefix} {_payload_reject_reason(payload)}")
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
        import os

        cdp = (os.environ.get("OXHOR_BI_CDP") or "").strip()
        if cdp:
            # Attach to the visible box-chrome so cloud-desktop preview shows the QR.
            browser = self._playwright.chromium.connect_over_cdp(cdp)
            self._context = browser.contexts[0] if browser.contexts else browser.new_context()
            self._page = self._context.new_page()
        else:
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
        for index in range(600):
            page.wait_for_timeout(1000)
            if bi_host in (page.url or "").lower():
                return
            if index % 15 == 0 and index > 0:
                print(f"waiting for BI login... {index}s")
        raise TimeoutError("BI login did not complete within 600 seconds")

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
            if data.get("isFile") and data.get("b64"):
                # A file response can arrive before the workbook is complete.
                # Keep polling a RUNNING task; only the official terminal status
                # lets the caller use the existing order-window fallback.
                self.require_not_failed(task, invalid_workbook=True)
            if not data.get("ok", True):
                self.require_not_failed(task)
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

    def require_not_failed(self, task: ExportTask, *, invalid_workbook: bool = False) -> None:
        result = self._require_page().evaluate(
            """async () => {
                const r = await fetch('/api/task-offline/guandata/history', {credentials:'include'});
                if (!r.ok) return null;
                return await r.json();
            }"""
        )
        if not isinstance(result, dict) or not isinstance(result.get("data"), list):
            return
        for row in result["data"]:
            if row.get("taskId") != task.task_id:
                continue
            status = row.get("taskStatus")
            if status in {"CANCELED", "FAILED"}:
                raise OfficialExportFailed(task, status)
            if invalid_workbook and status == "FINISHED":
                raise OfficialExportFailed(task, "INVALID_XLSX")

    def _require_page(self):
        if self._page is None:
            raise RuntimeError("BI page is not open")
        return self._page


def _local_chrome_launch_kwargs() -> dict:
    # --class=box-chrome: cloud desktop preview only surfaces this WM class.
    kwargs: dict = {
        "viewport": {"width": 1280, "height": 800},
        "args": [
            "--window-size=1280,800",
            "--window-position=0,0",
            "--start-maximized",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--class=box-chrome",
        ],
    }
    if platform.system() == "Darwin":
        mac = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        if mac.exists():
            kwargs["executable_path"] = str(mac)
    else:
        for candidate in (
            Path("/usr/bin/google-chrome-stable"),
            Path("/usr/bin/google-chrome"),
            Path("/usr/bin/chromium"),
        ):
            if candidate.exists():
                kwargs["executable_path"] = str(candidate)
                break
    return kwargs


def run_bi_download(
    config: BIExportConfig | None = None,
    client: BIExportClient | None = None,
    targets: Iterable[str] = ("orders", "cash"),
    start_date: str | None = None,
    end_date: str | None = None,
    orders_start_date: str | None = None,
    orders_end_date: str | None = None,
    orders_fallback_start_date: str | None = None,
    orders_fallback_end_date: str | None = None,
) -> list[DownloadedArtifact]:
    config = config or BIExportConfig()
    start_date = start_date or config.default_start_date
    end_date = end_date or date.today().isoformat()
    selected = list(targets)
    config.download_dir.mkdir(parents=True, exist_ok=True)
    if bool(orders_start_date) != bool(orders_end_date):
        raise ValueError("both order window dates are required")
    if bool(orders_fallback_start_date) != bool(orders_fallback_end_date):
        raise ValueError("both order fallback window dates are required")

    def download_all(active_client: BIExportClient) -> list[DownloadedArtifact]:
        artifacts = []
        if "orders" in selected:
            first_start = orders_start_date or start_date
            first_end = orders_end_date or end_date
            try:
                artifact = _download_request(
                    client=active_client,
                    request=build_order_export_request(config, first_start, first_end, ""),
                    config=config, start_date=first_start, end_date=first_end,
                    mode="incremental" if orders_start_date else "full",
                )
            except OfficialExportFailed:
                if orders_start_date or not orders_fallback_start_date:
                    raise
                artifact = _download_request(
                    client=active_client,
                    request=build_order_export_request(config, orders_fallback_start_date, orders_fallback_end_date, ""),
                    config=config, start_date=orders_fallback_start_date, end_date=orders_fallback_end_date,
                    mode="incremental",
                )
            artifacts.append(artifact)
        if "cash" in selected:
            if not config.cash_card_id:
                raise ValueError("BI cash card id is not configured")
            artifacts.append(_download_request(
                client=active_client, request=build_cash_export_request(config, start_date, end_date),
                config=config, start_date=start_date, end_date=end_date, mode="full",
            ))
        return artifacts

    # Inspect all required task receipts before opening a login window. An
    # interrupted submission without an ID cannot safely create another task.
    cached = []
    pending = False
    windows = []
    if "orders" in selected:
        windows.append((build_order_export_request(config, orders_start_date or start_date,
                        orders_end_date or end_date, ""), orders_start_date or start_date,
                        orders_end_date or end_date, "incremental" if orders_start_date else "full"))
    if "cash" in selected:
        if not config.cash_card_id:
            raise ValueError("BI cash card id is not configured")
        windows.append((build_cash_export_request(config, start_date, end_date), start_date, end_date, "full"))
    for request, window_start, window_end, mode in windows:
        try:
            state = _load_request_state(request, config, window_start, window_end)
        except OfficialExportFailed:
            if request.target != "orders" or orders_start_date or not orders_fallback_start_date:
                raise
            window_start, window_end, mode = orders_fallback_start_date, orders_fallback_end_date, "incremental"
            request = build_order_export_request(config, window_start, window_end, "")
            state = _load_request_state(request, config, window_start, window_end)
        if state is not None and state["status"] == "downloaded":
            cached.append(_cached_artifact(request.target, state, window_start, window_end, mode))
        else:
            pending = True
    if not pending:
        return cached
    if client is not None:
        return download_all(client)
    with PlaywrightBIExportClient() as browser_client:
        browser_client.open(config)
        return download_all(browser_client)


def _download_request(*, client: BIExportClient, request: BIExportRequest,
                      config: BIExportConfig, start_date: str, end_date: str,
                      mode: str) -> DownloadedArtifact:
    if date.fromisoformat(start_date) > date.fromisoformat(end_date):
        raise ValueError("invalid BI export date window")
    state_path = config.download_dir / f"{request.target}-{start_date}-{end_date}.task.json"
    fingerprint = hashlib.sha256(json.dumps(request.payload, sort_keys=True).encode()).hexdigest()

    def save(state):
        temporary = state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2))
        temporary.chmod(0o600)
        temporary.replace(state_path)

    state = _load_request_state(request, config, start_date, end_date)
    if state is not None:
        if state["status"] == "downloaded":
            return _cached_artifact(request.target, state, start_date, end_date, mode)
        task = ExportTask(request.target, state["task_id"], state["file_name"])
    else:
        state = {"target": request.target, "start_date": start_date, "end_date": end_date,
                 "mode": mode, "request_sha256": fingerprint, "status": "submitting"}
        save(state)
        task = client.trigger_export(request)
        state.update(task_id=task.task_id, file_name=task.file_name, status="submitted")
        save(state)
        print(f"[BI] target={request.target} task_id={task.task_id} state=submitted")
    try:
        path = client.poll_download(task, config).resolve()
    except OfficialExportFailed as error:
        state["status"] = error.status
        save(state)
        raise
    state.update(status="downloaded", path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    save(state)
    return DownloadedArtifact(task.target, path, start_date, end_date, mode)


def _load_request_state(request: BIExportRequest, config: BIExportConfig,
                        start_date: str, end_date: str) -> dict | None:
    if date.fromisoformat(start_date) > date.fromisoformat(end_date):
        raise ValueError("invalid BI export date window")
    state_path = config.download_dir / f"{request.target}-{start_date}-{end_date}.task.json"
    if not state_path.exists():
        return None
    state = json.loads(state_path.read_text())
    fingerprint = hashlib.sha256(json.dumps(request.payload, sort_keys=True).encode()).hexdigest()
    if state.get("request_sha256") != fingerprint:
        raise ValueError("BI saved task request mismatch")
    if state["status"] != "downloaded" and not state.get("task_id"):
        raise RuntimeError("BI export submission result unknown; inspect original task before retry")
    if state["status"] in {"CANCELED", "FAILED", "INVALID_XLSX"}:
        task = ExportTask(request.target, state["task_id"], state["file_name"])
        raise OfficialExportFailed(task, state["status"])
    return state


def _cached_artifact(target: str, state: dict, start_date: str, end_date: str,
                     mode: str) -> DownloadedArtifact:
    path = Path(state["path"])
    if hashlib.sha256(path.read_bytes()).hexdigest() != state["sha256"]:
        raise ValueError("BI saved export SHA mismatch")
    return DownloadedArtifact(target, path, start_date, end_date, mode)
