"""Real subprocess MCP tests; the optional mcp extra is required to run them."""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from project_intelligence.service import ProjectContextService
from tests.platform.test_query_service import warehouse

HAS_MCP = importlib.util.find_spec('mcp') is not None
if HAS_MCP:
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters
    from project_intelligence.mcp_server import TOOL_DESCRIPTIONS, create_server

REPO = Path(__file__).resolve().parents[2]


def command(root):
    return [sys.executable, '-B', '-m', 'project_intelligence.mcp_server', '--root', str(root)]


def prepare(root):
    (root / 'README.md').write_text('Architecture\nArchitecture detail\npassword=SECRET_FILE_VALUE\n')
    base = root / 'customers/bi_operations'
    pointer = base / 'Work/workspace.json'
    pointer.parent.mkdir(parents=True)
    relative = 'Work/Runs/run_query_test/data/snapshots/snapshot_query_test/warehouse.duckdb'
    pointer.write_text(json.dumps({
        'schema_version': 'bridge_alignment_workspace.v1', 'company_id': 'company_fixture',
        'business_port': 'operations', 'current_snapshot_id': 'snapshot_query_test',
        'current_warehouse_path': relative, 'pack_path': 'Work/Pack/pack.json',
        'pack_ref': {'pack_id': 'fixture', 'pack_version': '1.0.0'}, 'bridge_reference_path': None,
        'password': 'SECRET_METADATA_VALUE',
    }))
    pack = base / 'Work/Pack/pack.json'; pack.parent.mkdir()
    pack.write_text('{"pack_id":"fixture","pack_version":"1.0.0"}')
    db = base / relative; db.parent.mkdir(parents=True)
    warehouse(db)


def fingerprints(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


@unittest.skipUnless(HAS_MCP, 'Install the optional mcp extra for MCP protocol tests')
class MCPClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='pi mcp ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        prepare(self.root)

    def client(self, mode='legacy'):
        args = command(self.root)
        return Client(StdioServerParameters(command=args[0], args=args[1:], cwd=REPO,
                      env={'PYTHONDONTWRITEBYTECODE': '1'}), mode=mode, read_timeout_seconds=10)

    async def test_initialize_and_exact_tool_discovery(self):
        async with self.client() as client:
            self.assertEqual(client.server_info.name, 'Project Intelligence')
            self.assertIsNotNone(client.server_capabilities.tools)
            self.assertIsNone(client.server_capabilities.resources)
            self.assertIsNone(client.server_capabilities.prompts)
            result = await client.list_tools()
            self.assertEqual({t.name for t in result.tools}, set(TOOL_DESCRIPTIONS))
            expected = {'get_project_overview': set(), 'search_project': {'query', 'offset', 'limit'},
                        'read_project_context': {'content_id', 'start_line', 'limit', 'expected_sha256'},
                        'get_workspace_metadata': {'workspace_id'}, 'get_integration_map': set()}
            for tool in result.tools:
                self.assertTrue(tool.annotations.read_only_hint)
                self.assertFalse(tool.annotations.destructive_hint)
                self.assertFalse(tool.annotations.open_world_hint)
                self.assertTrue(tool.annotations.idempotent_hint)
                self.assertEqual(set(tool.input_schema['properties']), expected[tool.name])
                self.assertFalse(tool.input_schema['additionalProperties'])
            await client.send_ping()

    async def test_five_tools_preserve_payloads_and_files(self):
        before = fingerprints(self.root)
        service = ProjectContextService(self.root)
        async with self.client() as client:
            overview = await client.call_tool('get_project_overview')
            ref = next(x for x in overview.structured_content['data']['documents'] if x['path'] == 'README.md')
            calls = [
                ('get_project_overview', {}),
                ('search_project', {'query': 'Architecture', 'limit': 1}),
                ('read_project_context', {'content_id': ref['content_id'], 'expected_sha256': ref['sha256']}),
                ('get_workspace_metadata', {'workspace_id': 'bi_operations'}),
                ('get_integration_map', {}),
            ]
            for name, args in calls:
                result = await client.call_tool(name, args)
                self.assertFalse(result.is_error, name)
                payload = result.structured_content
                self.assertEqual(json.loads(result.content[0].text), payload)
                self.assertEqual(payload['data'], getattr(service, name)(**args)['data'])
                self.assertNotIn('SECRET_FILE_VALUE', json.dumps(payload))
                self.assertNotIn('SECRET_METADATA_VALUE', json.dumps(payload))
        self.assertEqual(before, fingerprints(self.root))

    async def test_strict_arguments_and_unknown_tools_are_safe(self):
        async with self.client() as client:
            cases = [
                ('search_project', {'query': 'x', 'limit': 'SECRET_ARGUMENT'}),
                ('search_project', {'query': 'x', 'limit': True}),
                ('search_project', {}),
                ('get_project_overview', {'root': 'SECRET_ARGUMENT'}),
                ('SECRET_ARGUMENT', {}),
            ]
            for name, args in cases:
                result = await client.call_tool(name, args)
                self.assertTrue(result.is_error)
                self.assertNotIn('SECRET_ARGUMENT', result.model_dump_json())
            self.assertFalse((await client.call_tool('get_integration_map')).is_error)

    async def test_domain_error_and_partial_state_remain_distinct(self):
        async with self.client() as client:
            for name, args, code in (
                ('read_project_context', {'content_id': '../../.env'}, 'CONTENT_NOT_ALLOWED'),
                ('get_workspace_metadata', {'workspace_id': '../../private'}, 'WORKSPACE_NOT_ALLOWED'),
            ):
                result = await client.call_tool(name, args)
                self.assertTrue(result.is_error)
                self.assertEqual(result.structured_content['error']['code'], code)
            partial = await client.call_tool('get_workspace_metadata', {'workspace_id': 'bi_operations'})
            self.assertFalse(partial.is_error)
            self.assertTrue(partial.structured_content['data']['partial'])
            self.assertEqual(partial.structured_content['data']['business_readiness'], 'not_evaluated')

    async def test_stale_hash_rejected_over_protocol(self):
        async with self.client() as client:
            match = (await client.call_tool('search_project', {'query': 'Architecture'})).structured_content['data']['matches'][0]
            (self.root / 'README.md').write_text('Updated')
            result = await client.call_tool('read_project_context', {
                'content_id': match['source']['content_id'], 'expected_sha256': match['source']['sha256']})
            self.assertTrue(result.is_error)
            self.assertEqual(result.structured_content['error']['code'], 'CONTEXT_CHANGED')

    async def test_unexpected_service_exception_is_sanitized(self):
        service = ProjectContextService(self.root)
        server = create_server(service)
        with patch.object(service, '_git', side_effect=RuntimeError('SECRET_INTERNAL_EXCEPTION')):
            async with Client(server) as client:
                result = await client.call_tool('get_project_overview')
                self.assertTrue(result.is_error)
                self.assertEqual(result.structured_content['error']['code'], 'CONTEXT_UNAVAILABLE')
                self.assertNotIn('SECRET_INTERNAL_EXCEPTION', result.model_dump_json())

    async def test_sdk_auto_negotiation_also_works(self):
        async with self.client(mode='auto') as client:
            self.assertEqual(len((await client.list_tools()).tools), 5)
            self.assertFalse((await client.call_tool('get_integration_map')).is_error)


@unittest.skipUnless(HAS_MCP, 'Install the optional mcp extra for MCP protocol tests')
class MCPWireTests(unittest.TestCase):
    def test_stdout_protocol_only_malformed_params_and_clean_eof(self):
        with tempfile.TemporaryDirectory(prefix='pi wire ') as tmp:
            root = Path(tmp); prepare(root)
            before = fingerprints(root)
            with tempfile.TemporaryFile(mode='w+') as err:
                proc = subprocess.Popen(command(root), cwd=REPO, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=err, text=True)
                selector = selectors.DefaultSelector(); selector.register(proc.stdout, selectors.EVENT_READ)
                try:
                    def request(value):
                        proc.stdin.write(json.dumps(value) + '\n'); proc.stdin.flush()
                        self.assertTrue(selector.select(5), 'No MCP response')
                        line = proc.stdout.readline()
                        self.assertNotIn('SECRET_WIRE_VALUE', line)
                        return json.loads(line)  # Any banner/debug print fails here.
                    init = request({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                        'protocolVersion': '2025-11-25', 'capabilities': {},
                        'clientInfo': {'name': 'wire-test', 'version': '1.0'}}})
                    self.assertEqual(init['result']['protocolVersion'], '2025-11-25')
                    proc.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n');proc.stdin.flush()
                    result = request({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}})
                    self.assertEqual(len(result['result']['tools']), 5)
                    malformed = request({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                                         'params': {'name': {'SECRET_WIRE_VALUE': 1}}})
                    self.assertEqual(malformed['error']['code'], -32602)
                    result = request({'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {
                        'name': 'search_project', 'arguments': {'query': 'x', 'limit': 'SECRET_WIRE_VALUE'}}})
                    self.assertTrue(result['result']['isError'])
                    proc.stdin.close()
                    self.assertEqual(proc.wait(timeout=5), 0)
                    self.assertEqual(proc.stdout.read(), '')
                    err.seek(0); self.assertEqual(err.read(), '')
                finally:
                    selector.close()
                    if proc.poll() is None: proc.kill();proc.wait()
                    proc.stdout.close()
                    if not proc.stdin.closed: proc.stdin.close()
            self.assertEqual(before, fingerprints(root))

    def test_startup_errors_do_not_pollute_stdout_or_echo_input(self):
        for args in (['--root', '/missing/SECRET_STARTUP'], ['--SECRET_STARTUP']):
            result = subprocess.run([sys.executable, '-B', '-m', 'project_intelligence.mcp_server', *args],
                                    cwd=REPO, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, '')
            self.assertNotIn('SECRET_STARTUP', result.stderr)
            self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()
