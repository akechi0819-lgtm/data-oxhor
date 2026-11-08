import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openpyxl import Workbook
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from data_acquisition.auth.auth_sessions import (
    AuthSessionExpiredError,
    AuthSessionMissingError,
    AuthSessionPaths,
    write_auth_session,
)
from data_acquisition.connectors.advertising import sem_host


class SEMHostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.mapping = self.root / "sources.json"
        self.mapping.write_text(json.dumps({"sources": [{
            "source_id": "sem_existing", "kind": "sem_daily", "path": "old.xlsx",
            "start_date": "2026-10-01", "end_date": "2026-10-27",
            "sheets": {
                "2665": {"business_line": "abroad", "business_group": "留学整体", "platform": "百度"},
                "bing": {"business_line": "abroad", "business_group": "留学整体", "platform": "必应"},
            },
        }]}), encoding="utf-8")
        self.page = type("Page", (), {
            "url": sem_host.WORKBOOK_URL,
            "title": lambda _: sem_host.WORKBOOK_TITLE,
            "locator": lambda _self, _selector: type("Iframe", (), {"count": lambda _self: 1})(),
            "frame_locator": lambda _self, _selector: None,
        })()

    def test_only_exact_approved_document_url_is_accepted(self):
        sem_host.validate_workbook_url(sem_host.WORKBOOK_URL)
        for url in (
            "http://alidocs.dingtalk.com" + sem_host.WORKBOOK_PATH + "?utm_scene=person_space",
            "https://alidocs.dingtalk.com/i/nodes/other?utm_scene=person_space",
            sem_host.WORKBOOK_URL + "&extra=1",
            "https://example.test" + sem_host.WORKBOOK_PATH + "?utm_scene=person_space",
        ):
            with self.subTest(url=url), self.assertRaisesRegex(sem_host.SEMHostError, "url_not_approved"):
                sem_host.validate_workbook_url(url)

    def test_wait_requires_the_exact_workbook_on_the_approved_host(self):
        ready = sem_host.wait_for_workbook(self.page, timeout_sec=1)
        self.assertEqual(ready["page_host"], sem_host.WORKBOOK_HOST)
        self.assertEqual(ready["page_path"], sem_host.WORKBOOK_PATH)
        self.assertTrue(ready["title_matches"])
        self.assertEqual(ready["editor_iframe_count"], 1)
        with mock.patch.object(self.page, "frame_locator", side_effect=AssertionError("menu access")):
            self.assertIsNone(sem_host.wait_for_workbook(self.page, timeout_sec=1)["reason"])
        other = type("Page", (), {
            "url": "https://alidocs.dingtalk.com/i/nodes/other",
            "title": lambda _: sem_host.WORKBOOK_TITLE,
            "wait_for_timeout": lambda *_: None,
        })()
        with self.assertRaisesRegex(sem_host.SEMHostError, "workbook_not_ready"):
            sem_host.wait_for_workbook(other, timeout_sec=0)

    def test_matching_title_without_loaded_sheet_frame_is_not_authenticated(self):
        page = type("TitleOnlyPage", (), {
            "url": sem_host.WORKBOOK_URL,
            "title": lambda _: sem_host.WORKBOOK_TITLE,
            "locator": lambda _self, _selector: type("Iframe", (), {"count": lambda _self: 0})(),
            "wait_for_timeout": lambda *_args: None,
        })()
        with self.assertRaisesRegex(sem_host.SEMHostError, "workbook_not_ready_editor_iframe_missing") as caught:
            sem_host.wait_for_workbook(page, timeout_sec=0.01, poll_sec=0.001)
        self.assertTrue(caught.exception.diagnostics["title_matches"])
        self.assertEqual(caught.exception.diagnostics["editor_iframe_count"], 0)
        self.assertNotIn("?", json.dumps(caught.exception.diagnostics))

    def test_frame_count_is_retained_in_safe_attempt_error(self):
        exc = sem_host.SEMHostError(
            "sem_workbook_not_ready_editor_iframe_ambiguous",
            diagnostics={
                "editor_iframe_count": 2,
                "reason": "editor_iframe_ambiguous",
                "page_path": "/must-not-be-retained",
            },
        )
        record = sem_host._safe_error_record(exc)
        self.assertEqual(record["diagnostics"], {
            "editor_iframe_count": 2,
            "reason": "editor_iframe_ambiguous",
        })
        self.assertNotIn("page_path", json.dumps(record))

    def test_playwright_error_records_only_a_fixed_safe_reason(self):
        cases = (
            (PlaywrightError, "Execution context was destroyed", "context_destroyed"),
            (PlaywrightError, "Frame was detached", "frame_detached"),
            (PlaywrightError, "Target page, context or browser has been closed", "page_closed"),
            (PlaywrightError, "TypeError: Cannot read properties of undefined", "js_type"),
            (PlaywrightError, "ReferenceError: secret is not defined", "js_reference"),
            (PlaywrightError, "SyntaxError: unexpected token", "js_syntax"),
            (PlaywrightTimeoutError, "Timeout 30000ms exceeded", "other"),
        )
        for error_type, message, expected in cases:
            exc = error_type(f"{message} https://private.example/private/path?token=fixture-secret")
            with self.subTest(reason=expected):
                record = sem_host._safe_error_record(exc)
                self.assertEqual(record["reason"], expected)
                serialized = json.dumps(record)
                self.assertNotIn("private.example", serialized)
                self.assertNotIn("private/path", serialized)
                self.assertNotIn("fixture-secret", serialized)

    def test_export_capture_is_staged_with_real_bytes_and_completion_signal(self):
        native = self.root / "export.xlsx"
        book = Workbook()
        book.active.title = "2665"
        for sheet in (book["2665"], book.create_sheet("bing")):
            sheet.append(["时间", "消费", "现金消费"])
            sheet.append(["2026-10-28", 12, 10])
        book.save(native)
        evidence = self.root / "export.evidence.json"
        evidence.write_text(json.dumps({"native_completed_dates": [], "completion_missing": True}))
        digest = hashlib.sha256(native.read_bytes()).hexdigest()
        result = {
            "source_id": "sem", "status": "success", "captured_at": "2026-10-29T09:00:00+08:00",
            "start_date": "2026-10-01", "through_date": "2026-10-28", "account_ids": ["2665", "bing"],
            "files": [{"path": str(native.resolve()), "sha256": digest}],
            "evidence": {"path": str(evidence.resolve()), "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()},
            "completion": {"complete": False, "through_date": None, "basis": "download_only"},
        }
        output = self.root / "capture"
        def fake_download(_page, *, destination, **_kwargs):
            destination = Path(destination)
            shutil.copyfile(native, destination)
            copied_evidence = destination.with_suffix(".evidence.json")
            shutil.copyfile(evidence, copied_evidence)
            value = dict(result)
            value["files"] = [{"path": str(destination.resolve()), "sha256": digest}]
            value["evidence"] = {
                "path": str(copied_evidence.resolve()),
                "sha256": hashlib.sha256(copied_evidence.read_bytes()).hexdigest(),
            }
            return value

        with mock.patch.object(sem_host, "download_sem", side_effect=fake_download) as export:
            captured = sem_host.capture_page(
                self.page, mapping_manifest=self.mapping, output=output,
                start_date="2026-10-01", through_date="2026-10-28",
            )
        export.assert_called_once()
        self.assertEqual(captured["native_sha256"], digest)
        self.assertFalse(captured["completion"]["complete"])
        self.assertFalse(captured["published"])
        receipt = json.loads(Path(captured["capture_receipt"]).read_text())
        source = receipt["sources"][0]
        self.assertEqual(source["status"], "success")
        self.assertEqual(source["account_ids"], ["2665", "bing"])
        self.assertFalse(source["completion"]["complete"])
        self.assertEqual(Path(source["files"][0]["path"]).read_bytes(), native.read_bytes())
        attempt = json.loads(Path(captured["export_state"]).read_text())
        self.assertEqual(attempt["state"], "verified")
        self.assertEqual(attempt["phase"], "candidate_receipt_written")
        self.assertEqual(attempt["native_sha256"], digest)
        self.assertNotIn("fixture", json.dumps(attempt))

    def test_wrong_page_stops_before_creating_output_or_export(self):
        output = self.root / "wrong-page"
        self.page.url = "https://alidocs.dingtalk.com/i/nodes/not-the-approved-workbook"
        with mock.patch.object(sem_host, "download_sem") as export:
            with self.assertRaisesRegex(sem_host.SEMHostError, "page_not_approved"):
                sem_host.capture_page(
                    self.page, mapping_manifest=self.mapping, output=output,
                    start_date="2026-10-01", through_date="2026-10-28",
                )
        export.assert_not_called()
        self.assertFalse(output.exists())

    def test_pending_export_leaves_recoverable_unknown_state_without_resubmitting(self):
        output = self.root / "pending-export"

        def pending_once(_page, *, phase_callback, **_kwargs):
            phase_callback("export_request_pending")
            raise sem_host.ExportPending("sem_export_submission_or_download_unknown")

        with mock.patch.object(sem_host, "download_sem", side_effect=pending_once) as export:
            with self.assertRaisesRegex(sem_host.ExportPending, "submission_or_download_unknown"):
                sem_host.capture_page(
                    self.page, mapping_manifest=self.mapping, output=output,
                    start_date="2026-10-01", through_date="2026-10-28")
        export.assert_called_once()
        attempt = json.loads((output / "export-state.json").read_text())
        self.assertEqual(attempt["phase"], "export_request_pending")
        self.assertEqual(attempt["state"], "submission_outcome_unknown")
        self.assertFalse((output / "native.xlsx").exists())
        self.assertTrue(attempt["attempt_id"])
        self.assertIsNone(attempt["remote_task_id"])
        self.assertEqual((output / "export-state.json").stat().st_mode & 0o777, 0o600)
        self.assertFalse(list(output.glob("*.tmp")))

    def test_unexpected_pre_submit_error_records_safe_stage_and_stack(self):
        paths = AuthSessionPaths(self.root, "dingtalk_sem")
        write_auth_session(
            "dingtalk_sem",
            cookies=[{"name": "s", "value": "fixture-cookie", "domain": ".dingtalk.com", "path": "/", "expires": -1}],
            local_storage={"key": "fixture-storage"},
            paths=paths,
        )

        class PlaywrightManager:
            def __enter__(self): return object()
            def __exit__(self, *_args): return False

        output = self.root / "failed-before-export"
        with mock.patch("playwright.sync_api.sync_playwright", return_value=PlaywrightManager()), \
             mock.patch.object(sem_host, "_launch_browser",
                               side_effect=RuntimeError("private token=fixture-secret")):
            with self.assertRaises(sem_host.SEMHostExecutionError) as caught:
                sem_host.run_one_off(
                    workspace=self.root, mapping_manifest=self.mapping, output=output,
                    start_date="2026-10-01", through_date="2026-10-28",
                    executable_path="/unused/test-chrome",
                )
        logs = list(self.root.glob("failed-before-export.attempt-*.json"))
        self.assertEqual(len(logs), 1)
        attempt = json.loads(logs[0].read_text())
        self.assertEqual(attempt["state"], "pre_submit_failed")
        self.assertEqual(attempt["failure_phase"], "browser_launch")
        self.assertEqual(attempt["error"]["exception_type"], "RuntimeError")
        self.assertTrue(attempt["error"]["frames"])
        self.assertNotIn("fixture-secret", json.dumps(attempt))
        self.assertEqual(logs[0].stat().st_mode & 0o777, 0o600)
        self.assertFalse(output.exists())
        self.assertNotIn("fixture-secret", json.dumps(caught.exception.diagnostics))

    def test_dingtalk_auth_is_private_and_loaded_only_for_approved_origin(self):
        paths = AuthSessionPaths(self.root, "dingtalk_sem")
        write_auth_session(
            "dingtalk_sem",
            cookies=[{"name": "session", "value": "fixture-only", "domain": ".dingtalk.com", "path": "/", "expires": -1}],
            local_storage={"key": "fixture-only"},
            paths=paths,
        )
        self.assertEqual(paths.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(paths.cookies.stat().st_mode & 0o777, 0o600)
        self.assertEqual(paths.local_storage.stat().st_mode & 0o777, 0o600)
        cookies, storage = sem_host.load_auth_state(self.root)

        class Context:
            def add_cookies(self, value):
                self.cookies = value

            def add_init_script(self, *, script):
                self.script = script

        context = Context()
        sem_host.install_auth_state(context, cookies, storage)
        self.assertEqual(context.cookies, cookies)
        self.assertIn('location.origin === "https://alidocs.dingtalk.com"', context.script)
        self.assertIn('localStorage.setItem(key, value)', context.script)
        self.assertEqual(AuthSessionPaths(self.root, "bi").root.exists(), False)

    def test_dingtalk_auth_rejects_cookie_scope_outside_document_domain(self):
        paths = AuthSessionPaths(self.root, "dingtalk_sem")
        write_auth_session(
            "dingtalk_sem",
            cookies=[{"name": "session", "value": "fixture-only", "domain": ".example.com", "path": "/"}],
            local_storage={}, paths=paths,
        )
        with self.assertRaisesRegex(sem_host.SEMHostError, "cookie_scope_invalid"):
            sem_host.load_auth_state(self.root)

    def test_login_state_is_saved_only_after_exact_workbook_is_open(self):
        class Context:
            def cookies(self, urls):
                self.requested_urls = urls
                return [{"name": "session", "value": "fixture-only", "domain": ".dingtalk.com", "path": "/"}]

        class Page:
            url = sem_host.WORKBOOK_URL

            def evaluate(self, _script):
                return {"key": "fixture-only"}

        context = Context()
        result = sem_host._persist_login_state(Page(), context, self.root)
        self.assertEqual(context.requested_urls, [sem_host.WORKBOOK_ORIGIN])
        self.assertEqual(result["service"], "dingtalk_sem")
        self.assertTrue(result["credentials_written"])
        self.assertNotIn("fixture-only", json.dumps(result))
        with self.assertRaises(sem_host.SEMHostError):
            sem_host._persist_login_state(
                type("WrongPage", (), {"url": "https://example.com/"})(), context, self.root / "wrong")
        self.assertFalse((self.root / "wrong/data_acquisition/storage/auth_sessions/dingtalk_sem").exists())

    def test_missing_or_expired_auth_are_the_only_login_recovery_triggers(self):
        with self.assertRaises(AuthSessionMissingError):
            sem_host.load_auth_state(self.root)
        expired = AuthSessionExpiredError("dingtalk_sem_auth_state_empty_or_expired")
        with mock.patch.object(sem_host, "run_one_off", side_effect=[expired, {"status": "ok"}]) as run, \
                mock.patch.object(sem_host, "save_login") as login:
            result = sem_host.run_authenticated(
                workspace=self.root, mapping_manifest=self.mapping, output=self.root / "out",
                start_date="2026-10-01", through_date="2026-10-28")
        self.assertEqual(result, {"status": "ok"})
        self.assertEqual(run.call_count, 2)
        login.assert_called_once()
        with mock.patch.object(sem_host, "run_one_off", side_effect=sem_host.ExportError("download_unknown")), \
                mock.patch.object(sem_host, "save_login") as login:
            with self.assertRaisesRegex(sem_host.ExportError, "download_unknown"):
                sem_host.run_authenticated(
                    workspace=self.root, mapping_manifest=self.mapping, output=self.root / "out",
                    start_date="2026-10-01", through_date="2026-10-28")
        login.assert_not_called()


    def _make_verified_export_output(self):
        from datetime import datetime
        native = self.root / "fixture.xlsx"
        workbook = Workbook()
        workbook.active.title = "2665"
        workbook["2665"].append(["时间", "消费", "现金消费"])
        workbook["2665"].append(["2026-10-28", 12, 10])
        workbook.create_sheet("bing").append(["时间", "消费", "现金消费"])
        workbook["bing"].append(["2026-10-28", 4, 3])
        workbook.save(native)
        source_evidence = self.root / "fixture.evidence.json"
        source_evidence.write_text(json.dumps({"native_completed_dates": []}))
        native_sha = hashlib.sha256(native.read_bytes()).hexdigest()
        output = self.root / "same-job"
        attempt = sem_host._new_export_attempt("2026-10-01", "2026-10-28")

        def fake_download(_page, *, destination, submission_callback,
                          phase_callback, **_kwargs):
            destination = Path(destination)
            shutil.copyfile(native, destination)
            copied_evidence = destination.with_suffix(".evidence.json")
            shutil.copyfile(source_evidence, copied_evidence)
            evidence_sha = hashlib.sha256(copied_evidence.read_bytes()).hexdigest()
            submission_callback({
                "kind": "submit", "http_status": 200, "task_id": "task-321",
                "response_body_status": "parsed",
            })
            submission_callback({
                "kind": "query", "http_status": 200, "task_id": "task-321",
                "response_body_status": "not_read",
            })
            return {
                "source_id": "sem", "status": "success",
                "captured_at": datetime.now(sem_host.SHANGHAI).isoformat(),
                "start_date": "2026-10-01", "through_date": "2026-10-28",
                "account_ids": ["2665", "bing"],
                "task_id": "task-321",
                "files": [{"path": str(destination.resolve()), "sha256": native_sha}],
                "evidence": {"path": str(copied_evidence.resolve()), "sha256": evidence_sha},
                "completion": {
                    "complete": False, "through_date": None, "basis": "download_only",
                },
            }

        with mock.patch.object(sem_host, "download_sem", side_effect=fake_download):
            captured = sem_host.capture_page(
                self.page, mapping_manifest=self.mapping, output=output,
                start_date="2026-10-01", through_date="2026-10-28",
                attempt=attempt,
            )
        state = json.loads(Path(captured["export_state"]).read_text())
        attempt_path = output.with_name(f"{output.name}.attempt-{state['attempt_id']}.json")
        sem_host._atomic_write_json(attempt_path, state)
        return output, captured

    def test_new_process_reuses_verified_same_output_without_auth_or_browser(self):
        output, captured = self._make_verified_export_output()
        with mock.patch.object(
                sem_host, "load_auth_state",
                side_effect=AssertionError("verified reuse must not load auth")),              mock.patch(
                "playwright.sync_api.sync_playwright",
                side_effect=AssertionError("verified reuse must not launch a browser")):
            reused = sem_host.run_one_off(
                workspace=self.root, mapping_manifest=self.mapping, output=output,
                start_date="2026-10-01", through_date="2026-10-28",
            )
        self.assertEqual(reused["task_id"], "task-321")
        self.assertEqual(reused["attempt_id"], captured["attempt_id"])
        self.assertTrue(reused["reused_existing"])
        self.assertFalse(reused["exported"])
        self.assertFalse(reused["published"])
        self.assertFalse(reused["completion"]["complete"])

    def test_verified_output_does_not_hide_another_unknown_attempt(self):
        output, _captured = self._make_verified_export_output()
        prior = sem_host._new_export_attempt("2026-10-01", "2026-10-28")
        prior["state"] = "submission_outcome_unknown"
        prior["phase"] = "export_request_pending"
        prior_path = output.with_name(f"{output.name}.attempt-{prior['attempt_id']}.json")
        sem_host._atomic_write_json(prior_path, prior)
        with mock.patch.object(
                sem_host, "load_auth_state",
                side_effect=AssertionError("unknown history must not load auth")), \
             mock.patch(
                "playwright.sync_api.sync_playwright",
                side_effect=AssertionError("unknown history must not launch a browser")):
            with self.assertRaisesRegex(sem_host.ExportError, "history_requires_review"):
                sem_host.run_one_off(
                    workspace=self.root, mapping_manifest=self.mapping, output=output,
                    start_date="2026-10-01", through_date="2026-10-28",
                )

    def test_existing_unknown_output_is_blocked_without_auth_or_browser(self):
        output = self.root / "unknown-job"
        output.mkdir()
        state = sem_host._new_export_attempt("2026-10-01", "2026-10-28")
        state["state"] = "submission_outcome_unknown"
        state["phase"] = "export_request_pending"
        sem_host._atomic_write_json(output / "export-state.json", state)
        sem_host._atomic_write_json(
            output.parent / f"unknown-job.attempt-{state['attempt_id']}.json",
            state,
        )
        (output / "sem-candidate").mkdir()
        (output / "sem-candidate/capture.json").write_text("{}")
        with mock.patch.object(
                sem_host, "load_auth_state",
                side_effect=AssertionError("unknown state must not load auth")),              mock.patch(
                "playwright.sync_api.sync_playwright",
                side_effect=AssertionError("unknown state must not launch a browser")):
            with self.assertRaisesRegex(sem_host.ExportError, "existing_sem_job_not_verified"):
                sem_host.run_one_off(
                    workspace=self.root, mapping_manifest=self.mapping, output=output,
                    start_date="2026-10-01", through_date="2026-10-28",
                )


if __name__ == "__main__":
    unittest.main()
