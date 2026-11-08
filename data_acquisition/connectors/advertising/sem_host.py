"""Request-based SEM export host with a dedicated, protected auth session.

Loads the current workbook in a headless, cookie-injected context to use its
official Excel serializer, then creates/polls/downloads using requests only.
An explicit login flow saves only that origin's applicable cookies and
localStorage through the project's 0700/0600 auth-session writer. Collection
loads that service-specific state into a new context; it never attaches to an
existing browser or reads a browser profile.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import re
import time
import traceback
from urllib.parse import urlsplit, parse_qs
import uuid
from zoneinfo import ZoneInfo

from playwright.sync_api import Error as PlaywrightError

from data_acquisition.auth.auth_sessions import (
    AuthSessionExpiredError,
    AuthSessionMissingError,
    AuthSessionPaths,
    write_auth_session,
)
from .native_exports import (
    ExportError, ExportPending, download_sem,
)
from .sem_candidate import stage_sem

SHANGHAI = ZoneInfo("Asia/Shanghai")
WORKBOOK_TITLE = "汇报202610SEM"
WORKBOOK_URL = (
    "https://alidocs.dingtalk.com/i/nodes/Obva6QBXJw9lXeeoF7P7GMqqWn4qY5Pr"
    "?utm_scene=person_space"
)
WORKBOOK_HOST = "alidocs.dingtalk.com"
WORKBOOK_PATH = "/i/nodes/Obva6QBXJw9lXeeoF7P7GMqqWn4qY5Pr"
WORKBOOK_ORIGIN = "https://alidocs.dingtalk.com"


class SEMHostError(RuntimeError):
    """Safe, fixed diagnostics for the one-off SEM host."""

    def __init__(self, message: str, *, diagnostics: dict | None = None):
        super().__init__(message)
        self.diagnostics = diagnostics


class SEMHostExecutionError(SEMHostError):
    """Unexpected host error with a safe phase and stack summary."""


def _new_export_attempt(start_date: str, through_date: str) -> dict:
    now = datetime.now(SHANGHAI).isoformat()
    return {
        "schema": "sem_export_attempt.v1",
        "attempt_id": uuid.uuid4().hex,
        "source_id": "sem",
        "workbook_title": WORKBOOK_TITLE,
        "start_date": start_date,
        "through_date": through_date,
        "started_at": now,
        "updated_at": now,
        "phase": "attempt_initialized",
        "state": "pre_submit",
        "remote_task_id": None,
        "submission_events": [],
        "native_sha256": None,
        "published": False,
    }


def _atomic_write_json(path: str | Path, value: dict) -> None:
    path = Path(path)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _record_attempt_phase(attempt: dict, path: str | Path, phase: str,
                          state: str | None = None) -> None:
    attempt["phase"] = phase
    if state is not None:
        attempt["state"] = state
    elif phase == "export_request_pending":
        attempt["state"] = "submission_outcome_unknown"
    elif phase == "download_received":
        attempt["state"] = "download_received"
    elif phase in {"native_file_saved", "native_workbook_validated", "native_export_verified"}:
        attempt["state"] = "downloaded"
    elif phase == "candidate_receipt_written":
        attempt["state"] = "verified"
    elif attempt.get("state") not in {"submission_outcome_unknown", "task_submitted",
                                       "submitted_download_unknown", "download_received", "downloaded", "verified"}:
        attempt["state"] = "pre_submit"
    attempt["updated_at"] = datetime.now(SHANGHAI).isoformat()
    _atomic_write_json(path, attempt)


def _record_submission_event(attempt: dict, path: str | Path, event: dict) -> None:
    kind = event.get("kind") if event.get("kind") in {"submit", "query"} else "unknown"
    status = event.get("http_status")
    status = status if isinstance(status, int) and 100 <= status <= 599 else None
    task_id = event.get("task_id")
    task_id = str(task_id) if isinstance(task_id, (str, int)) and not isinstance(task_id, bool) else None
    if task_id is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", task_id):
        task_id = None
    body_status = event.get("response_body_status")
    if body_status not in {"parsed", "unavailable", "not_read"}:
        body_status = "unavailable"
    entries = attempt.setdefault("submission_events", [])
    if len(entries) < 8:
        entries.append({"kind": kind, "http_status": status,
                        "task_id": task_id, "response_body_status": body_status})
    attempt["submission_event_count"] = attempt.get("submission_event_count", 0) + 1
    if kind == "submit":
        task_ids = {item.get("task_id") for item in entries
                    if item.get("kind") == "submit" and item.get("task_id")}
        if len(task_ids) == 1:
            attempt["remote_task_id"] = next(iter(task_ids))
            attempt["state"] = "task_submitted"
        elif len(task_ids) > 1:
            attempt["remote_task_id"] = None
            attempt["task_id_status"] = "ambiguous"
    attempt["updated_at"] = datetime.now(SHANGHAI).isoformat()
    _atomic_write_json(path, attempt)


def _safe_error_record(exc: Exception) -> dict:
    code = str(exc) if isinstance(exc, (ExportError, SEMHostError,
                                        AuthSessionMissingError, AuthSessionExpiredError)) else None
    frames = traceback.extract_tb(exc.__traceback__) if exc.__traceback__ else []
    record = {
        "exception_type": type(exc).__name__,
        "code": code,
        "frames": [{"file": Path(frame.filename).name,
                    "function": frame.name, "line": frame.lineno}
                   for frame in frames[-8:]],
    }
    if isinstance(exc, PlaywrightError):
        message = str(exc).lower()
        if "execution context was destroyed" in message or "context was destroyed" in message:
            reason = "context_destroyed"
        elif "frame was detached" in message or "frame detached" in message:
            reason = "frame_detached"
        elif ("page closed" in message or "page has been closed" in message
              or "context or browser has been closed" in message
              or "target closed" in message):
            reason = "page_closed"
        elif "typeerror" in message:
            reason = "js_type"
        elif "referenceerror" in message:
            reason = "js_reference"
        elif "syntaxerror" in message:
            reason = "js_syntax"
        else:
            reason = "other"
        record["reason"] = reason
    diagnostics = getattr(exc, "diagnostics", None)
    safe_keys = {
        "title_matches", "editor_iframe_count", "reason",
        "label", "visible_match_count",
    }
    if isinstance(diagnostics, dict):
        safe = {key: value for key, value in diagnostics.items()
                if key in safe_keys and
                (value is None or isinstance(value, (str, bool, int)))}
        if safe:
            record["diagnostics"] = safe
    return record


def _record_attempt_failure(attempt: dict, paths: list[Path], exc: Exception) -> None:
    previous_state = attempt.get("state")
    attempt["failure_phase"] = attempt.get("phase")
    attempt["phase"] = "failed"
    attempt["error"] = _safe_error_record(exc)
    if previous_state == "submission_outcome_unknown":
        if attempt.get("remote_task_id"):
            attempt["state"] = "submitted_download_unknown"
    elif previous_state not in {"task_submitted", "download_received", "downloaded", "verified"}:
        attempt["state"] = "pre_submit_failed"
    attempt["updated_at"] = datetime.now(SHANGHAI).isoformat()
    for path in paths:
        try:
            if path.parent.is_dir():
                _atomic_write_json(path, attempt)
        except OSError:
            # Keep the original failure; any already-written pending marker remains.
            pass


def validate_workbook_url(url: str) -> None:
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname != WORKBOOK_HOST
            or parts.path != WORKBOOK_PATH
            or parse_qs(parts.query) != {"utm_scene": ["person_space"]}
            or parts.username or parts.password or parts.fragment):
        raise SEMHostError("sem_workbook_url_not_approved")


def mapped_sem_sheets(mapping_manifest: str | Path) -> list[str]:
    value = json.loads(Path(mapping_manifest).read_text(encoding="utf-8"))
    entries = [item for item in value.get("sources", []) if item.get("kind") == "sem_daily"]
    if len(entries) != 1:
        raise SEMHostError("sem_mapping_missing_or_ambiguous")
    sheets = entries[0].get("sheets")
    if not isinstance(sheets, dict) or not sheets:
        raise SEMHostError("sem_mapped_sheets_missing")
    return list(sheets)


def _login_prompt_visible(page) -> bool:
    current = urlsplit(page.url)
    host = (current.hostname or "").lower()
    if (host.endswith(".dingtalk.com")
            and (host in {"login.dingtalk.com", "passport.dingtalk.com"}
                 or any(part in current.path.lower() for part in ("/login", "/signin", "/passport")))):
        return True
    try:
        body = page.locator("body").inner_text(timeout=1500)
    except Exception:
        return False
    return any(label in body for label in (
        "扫码登录", "手机号登录", "密码登录", "钉钉登录", "验证码登录",
        "请登录", "登录后查看",
    ))


def _workbook_readiness_probe(page) -> dict:
    """Return only safe page readiness booleans/counts; never expose query data or text."""
    probe = {
        "page_host": None, "page_path": None, "title_matches": None,
        "editor_iframe_count": None,
        "reason": None,
    }
    try:
        current = urlsplit(page.url)
    except Exception:
        probe["reason"] = "page_url_unavailable"
        return probe
    probe["page_host"] = current.hostname
    probe["page_path"] = current.path
    if current.hostname != WORKBOOK_HOST or current.path != WORKBOOK_PATH:
        probe["reason"] = "workbook_url_mismatch"
        return probe
    try:
        probe["title_matches"] = WORKBOOK_TITLE in page.title()
    except Exception:
        probe["reason"] = "workbook_title_unavailable"
        return probe
    if not probe["title_matches"]:
        probe["reason"] = "workbook_title_mismatch"
        return probe
    try:
        probe["editor_iframe_count"] = page.locator("#wiki-new-sheet-iframe").count()
    except Exception:
        probe["reason"] = "editor_iframe_unavailable"
        return probe
    if probe["editor_iframe_count"] == 0:
        probe["reason"] = "editor_iframe_missing"
        return probe
    if probe["editor_iframe_count"] != 1:
        probe["reason"] = "editor_iframe_ambiguous"
        return probe
    # The request exporter waits for the editor model, not menu controls.
    return probe


def wait_for_workbook(page, *, timeout_sec: int = 300, poll_sec: float = 1.0,
                      fail_on_login: bool = False) -> dict:
    """Wait for this workbook after any ordinary user login/QR step."""
    deadline = time.monotonic() + timeout_sec
    last_probe = {
        "page_host": None, "page_path": None, "title_matches": None,
        "editor_iframe_count": None,
        "reason": "navigation_pending",
    }
    while time.monotonic() < deadline:
        if fail_on_login and _login_prompt_visible(page):
            raise AuthSessionExpiredError("dingtalk_sem_login_required")
        last_probe = _workbook_readiness_probe(page)
        if last_probe["reason"] is None:
            return last_probe
        try:
            page.wait_for_timeout(max(100, int(poll_sec * 1000)))
        except Exception:
            last_probe["reason"] = "page_wait_failed"
            raise SEMHostError(
                f"sem_workbook_not_ready_{last_probe['reason']}",
                diagnostics=last_probe,
            ) from None
    raise SEMHostError(
        f"sem_workbook_not_ready_{last_probe['reason']}",
        diagnostics=last_probe,
    )


def _auth_paths(workspace: str | Path) -> AuthSessionPaths:
    return AuthSessionPaths(Path(workspace), "dingtalk_sem")


def load_auth_state(workspace: str | Path) -> tuple[list[dict], dict[str, str]]:
    """Load only the dedicated SEM auth files, validating their scope and mode."""
    paths = _auth_paths(workspace)
    files = (paths.cookies, paths.local_storage)
    present = [path.is_file() and not path.is_symlink() for path in files]
    if not any(present):
        raise AuthSessionMissingError("dingtalk_sem_auth_missing")
    if not all(present):
        raise SEMHostError("dingtalk_sem_auth_state_incomplete")
    if paths.root.is_symlink() or any(path.stat().st_mode & 0o077 for path in files) or paths.root.stat().st_mode & 0o077:
        raise SEMHostError("dingtalk_sem_auth_state_not_private")
    try:
        cookies = json.loads(paths.cookies.read_text(encoding="utf-8"))
        local_storage = json.loads(paths.local_storage.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        raise SEMHostError("dingtalk_sem_auth_state_invalid") from None
    if not isinstance(cookies, list) or not isinstance(local_storage, dict):
        raise SEMHostError("dingtalk_sem_auth_state_invalid")
    host = WORKBOOK_HOST
    scoped_cookies = []
    now = datetime.now().timestamp()
    for cookie in cookies:
        if (not isinstance(cookie, dict) or not isinstance(cookie.get("name"), str)
                or not isinstance(cookie.get("value"), str)):
            raise SEMHostError("dingtalk_sem_auth_state_invalid")
        domain = cookie.get("domain")
        if not isinstance(domain, str):
            raise SEMHostError("dingtalk_sem_auth_cookie_scope_invalid")
        domain = domain.lstrip(".").lower()
        if (domain != host and not host.endswith("." + domain)) or (
                domain != "dingtalk.com" and not domain.endswith(".dingtalk.com")):
            raise SEMHostError("dingtalk_sem_auth_cookie_scope_invalid")
        try:
            expires = float(cookie.get("expires", cookie.get("expirationDate", -1)))
        except (TypeError, ValueError):
            expires = -1
        if expires > 0 and expires <= now:
            continue
        scoped_cookies.append(cookie)
    if any(not isinstance(key, str) or not isinstance(value, str)
           for key, value in local_storage.items()):
        raise SEMHostError("dingtalk_sem_auth_state_invalid")
    if not scoped_cookies and not local_storage:
        raise AuthSessionExpiredError("dingtalk_sem_auth_state_empty_or_expired")
    return scoped_cookies, local_storage


def install_auth_state(context, cookies: list[dict], local_storage: dict[str, str]) -> None:
    """Install state only into a fresh context and only on the approved origin."""
    if cookies:
        context.add_cookies(cookies)
    if local_storage:
        script = (
            "if (location.origin === " + json.dumps(WORKBOOK_ORIGIN) + ") {"
            "const saved = " + json.dumps(local_storage, ensure_ascii=False) + ";"
            "for (const [key, value] of Object.entries(saved)) localStorage.setItem(key, value);"
            "}"
        )
        context.add_init_script(script=script)


def _persist_login_state(page, context, workspace: str | Path) -> dict:
    current = urlsplit(page.url)
    if current.scheme != "https" or current.hostname != WORKBOOK_HOST or current.path != WORKBOOK_PATH:
        raise SEMHostError("dingtalk_sem_login_not_verified_on_workbook")
    cookies = context.cookies([WORKBOOK_ORIGIN])
    local_storage = page.evaluate("Object.fromEntries(Object.entries(localStorage))")
    if (not isinstance(cookies, list) or not isinstance(local_storage, dict)
            or (not cookies and not local_storage)
            or any(not isinstance(key, str) or not isinstance(value, str)
                   for key, value in local_storage.items())):
        raise SEMHostError("dingtalk_sem_login_state_empty_or_invalid")
    paths = _auth_paths(workspace)
    write_auth_session("dingtalk_sem", cookies=cookies,
                       local_storage=local_storage, paths=paths)
    return {"service": "dingtalk_sem", "credentials_written": True,
            "storage_directory_mode": oct(paths.root.stat().st_mode & 0o777),
            "cookie_file_mode": oct(paths.cookies.stat().st_mode & 0o777),
            "local_storage_file_mode": oct(paths.local_storage.stat().st_mode & 0o777)}


def _launch_browser(playwright, executable_path: str | Path | None = None, *, headless=False):
    if executable_path is None:
        return playwright.chromium.launch(channel="chrome", headless=headless, args=["--no-proxy-server"])
    binary = Path(executable_path).expanduser()
    if not binary.is_absolute() or not binary.is_file() or not binary.stat().st_mode & 0o111:
        raise SEMHostError("approved_chrome_executable_unavailable")
    return playwright.chromium.launch(executable_path=str(binary), headless=headless, args=["--no-proxy-server"])


def save_login(*, workspace: str | Path, executable_path: str | Path | None = None,
               login_wait_sec: int = 600) -> dict:
    """Open one dedicated normal login window and save only SEM-scoped state."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = _launch_browser(playwright, executable_path)
        try:
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()
            page.goto(WORKBOOK_URL, wait_until="domcontentloaded", timeout=60000)
            print("钉钉 SEM 专用窗口已打开。若要求登录/扫码，请在此窗口正常完成；验证《汇报202610SEM》打开后仅保存该站点会话。", flush=True)
            wait_for_workbook(page, timeout_sec=login_wait_sec)
            return _persist_login_state(page, context, workspace)
        finally:
            browser.close()


def check_saved_login(*, workspace: str | Path,
                      executable_path: str | Path | None = None) -> dict:
    """Verify saved state in a fresh browser process without exporting."""
    cookies, local_storage = load_auth_state(workspace)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = _launch_browser(playwright, executable_path)
        try:
            context = browser.new_context(accept_downloads=True)
            install_auth_state(context, cookies, local_storage)
            page = context.new_page()
            page.goto(WORKBOOK_URL, wait_until="domcontentloaded", timeout=60000)
            readiness = wait_for_workbook(page, fail_on_login=True)
            return {"status": "verified", "service": "dingtalk_sem",
                    "auth_reused": True, "workbook_accessible": True,
                    "editor_frame_ready": True, "readiness": readiness,
                    "exported": False}
        finally:
            browser.close()


def capture_page(page, *, mapping_manifest: str | Path, output: str | Path,
                 start_date: str, through_date: str,
                 workbook_title: str = WORKBOOK_TITLE,
                 attempt: dict | None = None,
                 phase_callback=None) -> dict:
    """Export once, validate the native workbook, and stage a SEM receipt."""
    current = urlsplit(page.url)
    if current.hostname != WORKBOOK_HOST or current.path != WORKBOOK_PATH:
        raise SEMHostError("sem_page_not_approved_workbook")
    if workbook_title != WORKBOOK_TITLE:
        raise SEMHostError("sem_workbook_title_not_approved")

    expected_sheets = mapped_sem_sheets(mapping_manifest)
    root = Path(output).absolute()
    if root.exists():
        if not (root / "native.request-state.json").is_file():
            raise ExportError("existing_sem_request_state_missing")
    else:
        root.mkdir(parents=True, exist_ok=False, mode=0o700)
    native = root / "native.xlsx"
    state_path = root / "export-state.json"
    attempt = attempt or _new_export_attempt(start_date, through_date)

    def record_phase(phase: str, state: str | None = None) -> None:
        _record_attempt_phase(attempt, state_path, phase, state)
        if phase_callback:
            phase_callback(phase, attempt)

    def record_submission(event: dict) -> None:
        _record_submission_event(attempt, state_path, event)
        if phase_callback:
            phase_callback("submission_response_observed", attempt)

    record_phase("workbook_verified", "pre_submit")
    result = download_sem(
        page, destination=native, workbook_title=workbook_title,
        expected_sheets=expected_sheets, start_date=start_date,
        through_date=through_date, phase_callback=record_phase,
        submission_callback=record_submission,
    )
    attempt["remote_task_id"] = result.get("task_id")
    attempt["native_sha256"] = result["files"][0]["sha256"]
    record_phase("native_export_verified", "downloaded")
    capture_path = root / "collector-capture.json"
    capture_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    staged = stage_sem(
        native, mapping_manifest, root / "sem-candidate",
        start=start_date, through=through_date, capture=capture_path,
    )
    record_phase("candidate_receipt_written", "verified")
    return {
        "status": "success",
        "source_id": "sem",
        "workbook_title": workbook_title,
        "start_date": start_date,
        "through_date": through_date,
        "account_sheets": expected_sheets,
        "task_id": attempt.get("remote_task_id"),
        "attempt_id": attempt.get("attempt_id"),
        "native_sha256": result["files"][0]["sha256"],
        "completion": result["completion"],
        "staged_manifest": staged["manifest"],
        "capture_receipt": staged["capture"],
        "export_state": str(state_path.resolve()),
        "published": False,
    }


def _sha256(path: str | Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _inside(path: str | Path, root: Path) -> Path:
    resolved = Path(path).resolve(strict=True)
    if not resolved.is_relative_to(root.resolve(strict=True)):
        raise ExportError("existing_sem_job_path_outside_output")
    return resolved


def _verified_existing_output(*, root: Path, mapping_manifest: str | Path,
                              start_date: str, through_date: str) -> dict:
    # Reuse only a fully verified output; never load auth or start a browser.
    state_path = root / "export-state.json"
    capture_path = root / "sem-candidate/capture.json"
    if not state_path.is_file() or not capture_path.is_file():
        raise ExportError("existing_sem_job_state_incomplete")
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        attempt_id = state.get("attempt_id")
        if not isinstance(attempt_id, str) or not re.fullmatch(r"[a-f0-9]{32}", attempt_id):
            raise ValueError
        attempt_path = root.with_name(f"{root.name}.attempt-{attempt_id}.json")
        attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
    except Exception:
        raise ExportError("existing_sem_job_attempt_unverifiable") from None
    for prior_path in root.parent.glob(f"{root.name}.attempt-*.json"):
        if prior_path == attempt_path:
            continue
        try:
            prior = json.loads(prior_path.read_text(encoding="utf-8"))
        except Exception:
            raise ExportError("existing_sem_job_history_unverifiable") from None
        events = prior.get("submission_events", [])
        if (prior.get("state") != "pre_submit_failed"
                or prior.get("remote_task_id")
                or any(isinstance(event, dict) and event.get("kind") == "submit"
                       for event in events)):
            raise ExportError("existing_sem_job_history_requires_review")
    if (state.get("state") != "verified"
            or state.get("phase") != "candidate_receipt_written"
            or state.get("published") is not False):
        raise ExportError("existing_sem_job_not_verified")
    identity_fields = ("attempt_id", "source_id", "workbook_title", "start_date",
                       "through_date", "state", "phase", "remote_task_id",
                       "native_sha256", "published")
    if any(attempt.get(key) != state.get(key) for key in identity_fields):
        raise ExportError("existing_sem_job_attempt_mismatch")
    if (state.get("source_id") != "sem"
            or state.get("workbook_title") != WORKBOOK_TITLE
            or state.get("start_date") != start_date
            or state.get("through_date") != through_date):
        raise ExportError("existing_sem_job_scope_mismatch")
    native = root / "native.xlsx"
    staged_native = root / "sem-candidate/native.xlsx"
    native_sha = state.get("native_sha256")
    if (not isinstance(native_sha, str) or not native.is_file()
            or not staged_native.is_file()
            or _sha256(native) != native_sha
            or _sha256(staged_native) != native_sha):
        raise ExportError("existing_sem_job_native_digest_mismatch")
    try:
        from .sem_candidate import load_sem_bundle
        entries, sources = load_sem_bundle(capture_path)
        expected_sheets = set(mapped_sem_sheets(mapping_manifest))
        if len(entries) != 1 or len(sources) != 1:
            raise ValueError
        entry, source = entries[0], sources[0]
        receipt = json.loads(capture_path.read_text())
        manifest_path = Path(receipt["manifest_path"])
        manifest_path = manifest_path if manifest_path.is_absolute() else capture_path.parent / manifest_path
        manifest_path = _inside(manifest_path, root)
        entry_path = _inside(entry["path"], root)
        if (entry.get("kind") != "sem_daily"
                or entry.get("sha256") != native_sha
                or set(entry.get("sheets", {})) != expected_sheets
                or entry_path != staged_native.resolve(strict=True)):
            raise ValueError
        if (source.get("source_id") != "sem"
                or source.get("status") != "success"
                or source.get("start_date") != start_date
                or source.get("through_date") != through_date
                or set(source.get("account_ids", [])) != expected_sheets):
            raise ValueError
        for spec in [*source.get("files", []), source.get("evidence", {})]:
            path = _inside(spec["path"], root)
            if _sha256(path) != spec["sha256"]:
                raise ValueError
        if source.get("task_id") and state.get("remote_task_id") and str(source["task_id"]) != str(state["remote_task_id"]):
            raise ValueError
    except ExportError:
        raise
    except Exception:
        raise ExportError("existing_sem_job_receipt_unverifiable") from None
    return {
        "status": "success",
        "source_id": "sem",
        "workbook_title": WORKBOOK_TITLE,
        "start_date": start_date,
        "through_date": through_date,
        "account_sheets": sorted(expected_sheets),
        "task_id": state.get("remote_task_id"),
        "attempt_id": attempt_id,
        "native_sha256": native_sha,
        "completion": source.get("completion"),
        "staged_manifest": str(manifest_path),
        "capture_receipt": str(capture_path.resolve(strict=True)),
        "export_state": str(state_path.resolve(strict=True)),
        "attempt_log": str(attempt_path.resolve(strict=True)),
        "reused_existing": True,
        "exported": False,
        "published": False,
    }


def run_one_off(*, workspace: str | Path, mapping_manifest: str | Path,
                output: str | Path, start_date: str, through_date: str,
                url: str = WORKBOOK_URL, executable_path: str | Path | None = None,
                login_wait_sec: int = 300) -> dict:
    """Use saved SEM state in a new ephemeral context and export exactly once."""
    validate_workbook_url(url)
    root = Path(output).absolute()
    if root.is_symlink():
        raise ExportError("destination_is_symlink")
    recovered_attempt = None
    if root.exists():
        request_state = root / "native.request-state.json"
        if not request_state.is_file() or (root / "sem-candidate/capture.json").is_file():
            return _verified_existing_output(
                root=root, mapping_manifest=mapping_manifest,
                start_date=start_date, through_date=through_date)
        saved_request = json.loads(request_state.read_text())
        if saved_request.get("state") == "submission_outcome_unknown" and not saved_request.get("job_id"):
            raise ExportPending("sem_export_submission_outcome_unknown")
        # The request exporter alone decides whether a saved job may resume.
        # Preserve its original attempt; never create a second task to recover it.
        recovered_attempt = json.loads((root / "export-state.json").read_text())
        if (recovered_attempt.get("workbook_title") != WORKBOOK_TITLE
                or recovered_attempt.get("start_date") != start_date
                or recovered_attempt.get("through_date") != through_date):
            raise ExportError("existing_sem_job_scope_mismatch")
    prior_attempts = list(root.parent.glob(f"{root.name}.attempt-*.json"))
    if prior_attempts and recovered_attempt is None:
        raise ExportError("existing_sem_attempt_requires_review")
    cookies, local_storage = load_auth_state(workspace)
    root.parent.mkdir(parents=True, exist_ok=True)
    attempt = recovered_attempt or _new_export_attempt(start_date, through_date)
    attempt_log = root.with_name(f"{root.name}.attempt-{attempt['attempt_id']}.json")
    _record_attempt_phase(attempt, attempt_log, "auth_state_loaded",
                          "task_submitted" if recovered_attempt and attempt.get("remote_task_id") else "pre_submit")

    def record_run_phase(phase: str, current: dict | None = None) -> None:
        if current is not None and current is not attempt:
            attempt.update(current)
        _record_attempt_phase(attempt, attempt_log, phase, attempt.get("state"))

    export_state = root / "export-state.json"
    try:
        from playwright.sync_api import sync_playwright

        record_run_phase("playwright_startup")
        with sync_playwright() as playwright:
            record_run_phase("browser_launch")
            browser = _launch_browser(playwright, executable_path, headless=True)
            try:
                record_run_phase("browser_launched")
                context = browser.new_context(accept_downloads=True)
                record_run_phase("browser_context_created")
                install_auth_state(context, cookies, local_storage)
                record_run_phase("auth_state_installed")
                page = context.new_page()
                record_run_phase("workbook_navigation")
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                record_run_phase("workbook_readiness")
                wait_for_workbook(page, timeout_sec=login_wait_sec, fail_on_login=True)
                record_run_phase("workbook_verified", attempt)
                result = capture_page(
                    page, mapping_manifest=mapping_manifest, output=root,
                    start_date=start_date, through_date=through_date,
                    attempt=attempt, phase_callback=record_run_phase,
                )
                result["auth_reused"] = True
                result["attempt_log"] = str(attempt_log.resolve())
                return result
            finally:
                browser.close()
    except Exception as exc:
        failure_phase = attempt.get("phase")
        _record_attempt_failure(attempt, [attempt_log, export_state], exc)
        if isinstance(exc, (AuthSessionExpiredError, AuthSessionMissingError, ExportError)):
            raise
        if isinstance(exc, SEMHostError):
            exc.diagnostics = {
                "attempt_id": attempt["attempt_id"],
                "failure_phase": failure_phase,
                "attempt_log": str(attempt_log.resolve()),
                "safe_error": _safe_error_record(exc),
            }
            raise
        raise SEMHostExecutionError(
            "sem_export_execution_failed",
            diagnostics={
                "attempt_id": attempt["attempt_id"],
                "failure_phase": failure_phase,
                "attempt_log": str(attempt_log.resolve()),
                "safe_error": _safe_error_record(exc),
            },
        ) from None


def run_authenticated(*, workspace: str | Path, mapping_manifest: str | Path,
                      output: str | Path, start_date: str, through_date: str,
                      executable_path: str | Path | None = None,
                      login_wait_sec: int = 600) -> dict:
    """Cookie-first: recover only missing/explicitly expired auth once."""
    job = {"workspace": workspace, "mapping_manifest": mapping_manifest,
           "output": output, "start_date": start_date, "through_date": through_date,
           "executable_path": executable_path}
    try:
        return run_one_off(**job)
    except (AuthSessionMissingError, AuthSessionExpiredError):
        save_login(workspace=workspace, executable_path=executable_path,
                   login_wait_sec=login_wait_sec)
        return run_one_off(**job)


def _default_window() -> tuple[str, str]:
    today = datetime.now(SHANGHAI).date()
    return today.replace(day=1).isoformat(), (today - timedelta(days=1)).isoformat()


def main() -> int:
    start_default, through_default = _default_window()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--mapping-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--start", default=start_default)
    parser.add_argument("--through", default=through_default)
    parser.add_argument("--login-wait-sec", type=int, default=600)
    parser.add_argument("--executable-path", type=Path,
                        help="Explicit installed Chrome/Chrome for Testing binary; no browser is installed by this command")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--login-only", action="store_true",
                      help="Open one normal SEM login window and save its site-scoped state; do not export")
    mode.add_argument("--check-auth", action="store_true",
                      help="Load saved state in a fresh browser context and verify the workbook; do not export")
    args = parser.parse_args()
    try:
        if args.login_only:
            result = save_login(workspace=args.workspace,
                                executable_path=args.executable_path,
                                login_wait_sec=args.login_wait_sec)
        elif args.check_auth:
            result = check_saved_login(workspace=args.workspace,
                                       executable_path=args.executable_path)
        elif args.output is None:
            parser.error("--output is required for export mode")
        else:
            result = run_authenticated(
                workspace=args.workspace,
                mapping_manifest=args.mapping_manifest, output=args.output,
                start_date=args.start, through_date=args.through,
                executable_path=args.executable_path,
                login_wait_sec=args.login_wait_sec,
            )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except AuthSessionMissingError:
        print(json.dumps({"status": "login_required", "reason": "dingtalk_sem_auth_missing", "exported": False}, ensure_ascii=False))
        return 2
    except AuthSessionExpiredError:
        print(json.dumps({"status": "login_required", "reason": "dingtalk_sem_auth_expired", "exported": False}, ensure_ascii=False))
        return 2
    except ExportPending as exc:
        print(json.dumps({"status": "pending", "reason": str(exc), "published": False}, ensure_ascii=False))
        return 2
    except ExportError as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc), "published": False}, ensure_ascii=False))
        return 2
    except SEMHostExecutionError as exc:
        print(json.dumps({
            "status": "failed", "reason": str(exc),
            "diagnostics": exc.diagnostics, "published": False,
        }, ensure_ascii=False))
        return 1
    except SEMHostError as exc:
        result = {"status": "blocked", "reason": str(exc), "published": False}
        if exc.diagnostics is not None:
            result["readiness"] = exc.diagnostics
        print(json.dumps(result, ensure_ascii=False))
        return 2
    except Exception as exc:
        # Keep browser exception text out of logs; it can contain request URLs.
        print(json.dumps({"status": "failed", "reason": type(exc).__name__, "published": False}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
