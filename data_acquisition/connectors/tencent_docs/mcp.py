"""Small verified-TLS client for the installed Tencent Docs MCP endpoint."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any

MCP_ENDPOINT = "https://docs.qq.com/openapi/mcp"


class TencentDocsMCPError(RuntimeError):
    """Stable safe error code from Tencent Docs MCP operations."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _decode_mcp_response(body: bytes) -> dict[str, Any]:
    try:
        text = body.decode("utf-8-sig")
        data_lines = [line[5:].lstrip() for line in text.splitlines() if line.startswith("data:")]
        payload = data_lines[-1] if data_lines else text.strip()
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise TencentDocsMCPError("mcp_response_not_json_or_sse") from None
    if not isinstance(value, dict):
        raise TencentDocsMCPError("mcp_response_not_object")
    return value


class TencentDocsMCPClient:
    """Use the system curl CA store; credentials and request bodies stay off argv."""

    def __init__(self, token_file: str | Path, *, timeout_sec: float = 60.0) -> None:
        try:
            timeout = float(timeout_sec)
            valid_timeout = math.isfinite(timeout) and timeout > 0
        except (TypeError, ValueError):
            valid_timeout = False
        if not valid_timeout:
            raise ValueError("timeout_sec must be a positive finite number")
        self.token_file = Path(token_file).expanduser()
        self.timeout_sec = timeout
        self._request_id = 0

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            token = self.token_file.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            raise TencentDocsMCPError("mcp_token_file_unreadable") from None
        if not token or "\n" in token or "\r" in token:
            raise TencentDocsMCPError("mcp_token_invalid")

        self._request_id += 1
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": self._request_id, "method": "tools/call",
             "params": {"name": name, "arguments": arguments}},
            ensure_ascii=False,
        ).encode("utf-8")
        curl_config = (
            f"url = {json.dumps(MCP_ENDPOINT)}\n"
            f"header = {json.dumps('Authorization: ' + token)}\n"
            'header = "Content-Type: application/json"\n'
            'header = "Accept: application/json, text/event-stream"\n'
        )
        fd, body_name = tempfile.mkstemp(prefix="tencent-docs-mcp-", suffix=".json")
        try:
            with os.fdopen(fd, "wb") as body_file:
                body_file.write(payload)
            try:
                response = subprocess.run(
                    ["/usr/bin/curl", "-sS", "--max-time", str(self.timeout_sec), "--config", "-",
                     "--data-binary", f"@{body_name}", "--write-out", "\n__HTTP__%{http_code}"],
                    input=curl_config,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=self.timeout_sec + 5,
                )
            except subprocess.TimeoutExpired:
                raise TencentDocsMCPError("mcp_transport_timeout") from None
            except OSError:
                raise TencentDocsMCPError("mcp_curl_unavailable") from None
        finally:
            try:
                os.unlink(body_name)
            except FileNotFoundError:
                pass

        if response.returncode:
            raise TencentDocsMCPError("mcp_transport_error")
        body_text, marker, status_text = response.stdout.rpartition("\n__HTTP__")
        if not marker:
            raise TencentDocsMCPError("mcp_curl_response_invalid")
        try:
            status = int(status_text)
        except ValueError:
            raise TencentDocsMCPError("mcp_curl_response_invalid") from None
        if not 200 <= status < 300:
            raise TencentDocsMCPError(f"mcp_http_error:{status}")

        message = _decode_mcp_response(body_text.encode("utf-8"))
        if message.get("error"):
            raise TencentDocsMCPError("mcp_jsonrpc_error")
        result = message.get("result")
        if not isinstance(result, dict):
            raise TencentDocsMCPError("mcp_tool_response_invalid")
        if result.get("isError"):
            raise TencentDocsMCPError("mcp_tool_reported_error")
        structured = result.get("structuredContent")
        if not isinstance(structured, dict):
            raise TencentDocsMCPError("mcp_tool_structured_content_missing")
        if structured.get("error"):
            raise TencentDocsMCPError("mcp_tool_reported_error")
        return structured
