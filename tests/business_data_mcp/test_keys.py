from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
import io
from unittest.mock import patch

from business_data_mcp.keys import (issue_key, key_id_for_token, list_keys, main,
                                    revoke_key)


def _concurrent_registry_update(path: str, action: str, key_id: str | None,
                                barrier: object) -> None:
    barrier.wait(timeout=20)
    if action == "issue":
        issue_key(Path(path), "concurrent issuer")
    else:
        assert key_id is not None
        revoke_key(Path(path), key_id)


class KeyRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="business mcp keys ")
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "private" / "keys.json"

    def test_issue_store_hash_only_list_and_revoke(self) -> None:
        issued = issue_key(self.path, "A team lead")
        self.assertTrue(issued["token"].startswith("bdmcp_"))
        self.assertEqual(key_id_for_token(self.path, issued["token"]), issued["key_id"])
        self.assertIsNone(key_id_for_token(self.path, "bdmcp_invalid"))

        registry = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(registry["schema_version"], "business_data_mcp_keys.v1")
        self.assertEqual(len(registry["keys"]), 1)
        self.assertNotIn(issued["token"], self.path.read_text(encoding="utf-8"))
        self.assertEqual(len(registry["keys"][0]["token_sha256"]), 64)
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        self.assertEqual(list_keys(self.path)[0]["status"], "active")

        self.assertEqual(revoke_key(self.path, issued["key_id"])["status"], "revoked")
        self.assertIsNone(key_id_for_token(self.path, issued["token"]))
        self.assertEqual(list_keys(self.path)[0]["status"], "revoked")

    def test_keys_are_independent(self) -> None:
        first = issue_key(self.path, "first")
        second = issue_key(self.path, "second")
        revoke_key(self.path, first["key_id"])
        self.assertIsNone(key_id_for_token(self.path, first["token"]))
        self.assertEqual(key_id_for_token(self.path, second["token"]), second["key_id"])
        self.assertEqual([item["status"] for item in list_keys(self.path)], ["revoked", "active"])

    def test_standalone_cli_prints_key_once_and_supports_lifecycle(self) -> None:
        stdout = io.StringIO()
        with patch.dict(os.environ, {"BUSINESS_DATA_MCP_KEYS_FILE": str(self.path)}):
            with redirect_stdout(stdout):
                self.assertEqual(main(["issue", "--label", "CLI user"]), 0)
            issued = json.loads(stdout.getvalue())
            token = issued["token"]
            stdout.seek(0)
            stdout.truncate(0)

            with redirect_stdout(stdout):
                self.assertEqual(main(["list"]), 0)
            listing = stdout.getvalue()
            self.assertNotIn(token, listing)
            stdout.seek(0)
            stdout.truncate(0)

            with redirect_stdout(stdout):
                self.assertEqual(main(["revoke", issued["key_id"]]), 0)
        self.assertEqual(key_id_for_token(self.path, token), None)

    def test_concurrent_issue_and_revoke_preserve_both_updates(self) -> None:
        initial = issue_key(self.path, "initial")
        context = multiprocessing.get_context("spawn")
        barrier = context.Barrier(2)
        workers = [
            context.Process(target=_concurrent_registry_update,
                            args=(str(self.path), "issue", None, barrier)),
            context.Process(target=_concurrent_registry_update,
                            args=(str(self.path), "revoke", initial["key_id"], barrier)),
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=30)
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join()
            self.assertEqual(worker.exitcode, 0)

        entries = list_keys(self.path)
        self.assertEqual(len(entries), 2)
        self.assertEqual([entry["status"] for entry in entries], ["revoked", "active"])
        self.assertEqual(os.stat(self.path.with_name(self.path.name + ".lock")).st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
