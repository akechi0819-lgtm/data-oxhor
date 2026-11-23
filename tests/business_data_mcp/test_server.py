from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from business_data_mcp.keys import issue_key, revoke_key

try:
    from mcp import Client
    from starlette.testclient import TestClient
    from business_data_mcp.server import CURRENT_KEY_ID, create_app, create_server
except ImportError:
    Client = None
    TestClient = None
    CURRENT_KEY_ID = None
    create_app = None
    create_server = None


class FakeQueryError(RuntimeError):
    code = "RESULT_NOT_FOUND"


class FakeReleaseError(RuntimeError):
    code = "RELEASE_UNAVAILABLE"


class FakeQuery:
    def __init__(self, current_path: Path, result_root: Path, *, capacity_root: Path | None = None):
        self.current_path = current_path
        self.result_root = result_root
        self.capacity_root = capacity_root
        self.results: set[str] = set()

    def describe(self, domain=None, table=None, expected_release=None):
        if table:
            return {"status": "passed", "domain": domain, "table": table, "columns": ["student_id"]}
        return {"status": "passed", "release": "release-1", "domains": ["training", "study"]}

    def query(self, domain, sql, expected_release, parameters=None, page_size=100):
        if expected_release != "release-1":
            raise FakeReleaseError("do not leak local paths")
        self.results.add("result-1")
        return {"status": "passed", "result_id": "result-1", "domain": domain,
                "first_page": {"columns": ["student_id"], "rows": [["001"]]}}

    def read_page(self, result_id, offset=0, limit=100):
        if result_id not in self.results:
            raise FakeQueryError("SECRET_PATH_SHOULD_NOT_LEAK")
        return {"status": "passed", "result_id": result_id, "offset": offset,
                "rows": [["001"]] if offset == 0 else []}

    def export_csv(self, result_id, offset=0, limit=500):
        if result_id not in self.results:
            raise FakeQueryError("SECRET_PATH_SHOULD_NOT_LEAK")
        text = "student_id\n001\n" if offset == 0 else "002\n"
        return {"status": "passed", "filename": "result.csv", "offset": offset,
                "next_offset": 1 if offset == 0 else None, "complete": offset != 0,
                "row_count": 2, "csv_text": text}


class ConcurrentFakeQuery(FakeQuery):
    active = 0
    max_active = 0
    lock = threading.Lock()

    def query(self, domain, sql, expected_release, parameters=None, page_size=100):
        with self.lock:
            type(self).active += 1
            type(self).max_active = max(type(self).max_active, type(self).active)
        try:
            time.sleep(0.08)
            return super().query(domain, sql, expected_release, parameters, page_size)
        finally:
            with self.lock:
                type(self).active -= 1


@unittest.skipIf(Client is None, "Install the business-data-mcp extra for SDK tests")
class MCPToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_tools_call_worker_and_keep_results_per_key(self) -> None:
        with tempfile.TemporaryDirectory(prefix="business mcp ") as tmp:
            root = Path(tmp)
            server = create_server(root / "current", root / "results", worker_factory=FakeQuery)
            async with Client(server) as client:
                tools = await client.list_tools()
                self.assertEqual({item.name for item in tools.tools}, {
                    "describe_data", "query_data", "read_query_result", "export_query_csv",
                    "describe_business_context", "read_business_context", "read_dashboard_data"})

                actor = CURRENT_KEY_ID.set("key_" + "a" * 32)
                try:
                    described = await client.call_tool("describe_data")
                    self.assertFalse(described.is_error)
                    self.assertEqual(described.structured_content["release"], "release-1")
                    query = await client.call_tool("query_data", {
                        "domain": "training", "sql": "SELECT student_id FROM training_orders",
                        "expected_release": "release-1"})
                    self.assertFalse(query.is_error)
                    result_id = query.structured_content["result_id"]
                    page = await client.call_tool("read_query_result", {"result_id": result_id})
                    self.assertFalse(page.is_error)
                    csv_page = await client.call_tool("export_query_csv", {"result_id": result_id})
                    self.assertFalse(csv_page.is_error)
                    self.assertEqual(json.loads(csv_page.content[0].text)["next_offset"], 1)
                    self.assertEqual(csv_page.content[1].text, "student_id\n001\n")
                    self.assertEqual(csv_page.structured_content["next_offset"], 1)
                    self.assertNotIn("csv_text", csv_page.structured_content)
                finally:
                    CURRENT_KEY_ID.reset(actor)

                other_actor = CURRENT_KEY_ID.set("key_" + "b" * 32)
                try:
                    foreign_page = await client.call_tool("read_query_result", {"result_id": "result-1"})
                    self.assertTrue(foreign_page.is_error)
                    self.assertEqual(foreign_page.structured_content["error"]["code"], "RESULT_NOT_FOUND")
                    self.assertNotIn("SECRET_PATH_SHOULD_NOT_LEAK", foreign_page.model_dump_json())
                finally:
                    CURRENT_KEY_ID.reset(other_actor)

    async def test_invalid_arguments_and_wrong_release_are_sanitized(self) -> None:
        with tempfile.TemporaryDirectory(prefix="business mcp ") as tmp:
            root = Path(tmp)
            server = create_server(root / "current", root / "results", worker_factory=FakeQuery)
            actor = CURRENT_KEY_ID.set("key_" + "a" * 32)
            try:
                async with Client(server) as client:
                    malformed = await client.call_tool("query_data", {
                        "domain": "training", "sql": "SELECT 1", "expected_release": "release-1",
                        "unexpected": "SECRET_ARGUMENT"})
                    self.assertTrue(malformed.is_error)
                    self.assertEqual(malformed.structured_content["error"]["code"], "INVALID_ARGUMENT")
                    self.assertIn("hint", malformed.structured_content["error"])
                    self.assertNotIn("SECRET_ARGUMENT", malformed.model_dump_json())

                    wrong_release = await client.call_tool("query_data", {
                        "domain": "training", "sql": "SELECT 1", "expected_release": "old"})
                    self.assertTrue(wrong_release.is_error)
                    self.assertEqual(wrong_release.structured_content["error"]["code"], "RELEASE_UNAVAILABLE")
                    self.assertIn("hint", wrong_release.structured_content["error"])
                    self.assertIn("describe_data", wrong_release.structured_content["error"]["hint"])
                    self.assertNotIn("do not leak local paths", wrong_release.model_dump_json())
            finally:
                CURRENT_KEY_ID.reset(actor)

    async def test_at_most_two_queries_run_at_once(self) -> None:
        with tempfile.TemporaryDirectory(prefix="business mcp ") as tmp:
            root = Path(tmp)
            ConcurrentFakeQuery.active = 0
            ConcurrentFakeQuery.max_active = 0
            server = create_server(root / "current", root / "results", worker_factory=ConcurrentFakeQuery)
            actor = CURRENT_KEY_ID.set("key_" + "a" * 32)
            try:
                async with Client(server) as client:
                    calls = [client.call_tool("query_data", {
                        "domain": "training", "sql": "SELECT 1", "expected_release": "release-1"})
                        for _ in range(3)]
                    results = await asyncio.gather(*calls)
                    self.assertTrue(all(not result.is_error for result in results))
                self.assertEqual(ConcurrentFakeQuery.max_active, 2)
            finally:
                CURRENT_KEY_ID.reset(actor)


@unittest.skipIf(TestClient is None, "Install the business-data-mcp extra for HTTP tests")
class HTTPAuthTests(unittest.TestCase):
    def test_health_is_public_and_mcp_checks_key_per_request(self) -> None:
        with tempfile.TemporaryDirectory(prefix="business mcp http ") as tmp:
            root = Path(tmp)
            keys_file = root / "keys.json"
            first = issue_key(keys_file, "first user")
            second = issue_key(keys_file, "second user")
            app = create_app(root / "current", root / "results", keys_file,
                             allowed_hosts=["testserver"], worker_factory=FakeQuery)
            with TestClient(app) as client:
                health = client.get("/health")
                self.assertEqual(health.status_code, 200)
                self.assertEqual(health.json(), {"status": "ok"})

                unauthorized = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1,
                    "method": "tools/list", "params": {}})
                self.assertEqual(unauthorized.status_code, 401)
                self.assertEqual(unauthorized.json()["error"], "AUTH_REQUIRED")

                authorized = client.post("/mcp", headers={"Authorization": "Bearer " + first["token"]},
                    json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
                self.assertEqual(authorized.status_code, 200)

                call = client.post("/mcp", headers={"Authorization": "Bearer " + first["token"]},
                    json={"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                          "params": {"name": "describe_data", "arguments": {}}})
                self.assertEqual(call.status_code, 200)
                self.assertEqual(call.json()["result"]["structuredContent"]["release"], "release-1")

                revoke_key(keys_file, first["key_id"])
                revoked = client.post("/mcp", headers={"Authorization": "Bearer " + first["token"]},
                    json={"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}})
                self.assertEqual(revoked.status_code, 401)
                still_active = client.post("/mcp", headers={"Authorization": "Bearer " + second["token"]},
                    json={"jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {}})
                self.assertEqual(still_active.status_code, 200)


if __name__ == "__main__":
    unittest.main()
