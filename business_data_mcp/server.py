"""Remote Streamable HTTP MCP wrapper around the controlled query worker."""
from __future__ import annotations

import argparse
from contextvars import ContextVar
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Literal

import anyio
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import ConfigDict, Field, ValidationError, create_model
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .context import describe_business_context, read_release_business_context
from .keys import KEYS_FILE_ENV, KeyStoreError, key_id_for_token, list_keys
from .query import BusinessDataQuery


CONTEXT_ENV = "BUSINESS_DATA_MCP_CONTEXT"
CURRENT_ENV = "BUSINESS_DATA_MCP_CURRENT"
RESULTS_ENV = "BUSINESS_DATA_MCP_RESULTS"
HOST_ENV = "BUSINESS_DATA_MCP_HOST"
PORT_ENV = "BUSINESS_DATA_MCP_PORT"
ALLOWED_HOSTS_ENV = "BUSINESS_DATA_MCP_ALLOWED_HOSTS"
ALLOWED_ORIGINS_ENV = "BUSINESS_DATA_MCP_ALLOWED_ORIGINS"
DEFAULT_ALLOWED_HOSTS = "127.0.0.1:*,localhost:*,[::1]:*"

CURRENT_KEY_ID: ContextVar[str | None] = ContextVar("business_data_mcp_key_id", default=None)

TOOL_DESCRIPTIONS = {
    "describe_business_context": "List approved Bridge, dashboard and official scorecard sources, their scope and query limitations. Call before answering business metric questions.",
    "read_business_context": "Read one approved business context source by source_id; apply its stated scope and limitations.",
    "describe_data": (
        "Show the available training and study data releases and tables. Supply a domain and table ID "
        "from this result to inspect one table's fields."
    ),
    "read_dashboard_data": "Export published dashboard results. Use describe_data without arguments for datasets and filter names. For team_metrics, omitted business_line, unit_id and acquisition_scope default to training, total and 被动 (all new and returning students). Set any of these filters to '*' for all its values, or provide explicit values. For team_metrics, prior is the prior-year comparison over the selected period start through actual cutoff, each shifted back one year; it applies to training and is null for abroad and future periods. Select period_id and metric (heads, cash, orders). Pass result_id to export_query_csv.",
    "query_data": (
        "Run one read-only SQL query against a selected domain and explicit data release. Include the "
        "release returned by describe_data so later publication changes cannot silently alter this query. "
        "The result includes a first page and a result ID for further reading or CSV export."
    ),
    "read_query_result": "Read a page from this query's saved result using its result ID and row offset.",
    "export_query_csv": (
        "Read this query's complete CSV in chunks of up to 500 rows, reduced automatically to fit the MCP response budget. "
        "Start at offset 0 and continue with each returned "
        "next_offset until it is null; only the first chunk includes the header."
    ),
}

QUERY_ERROR_HINTS = {
    "CONTEXT_UNAVAILABLE": "The approved business context is not available; contact the data service owner. Do not invent definitions.",
    "CONTEXT_NOT_FOUND": "Call describe_business_context to select an available source ID.",
    "QUERY_INVALID": "Check the SQL syntax and verify table and column names with describe_data, then retry.",
    "QUERY_PARAMETERS_INVALID": "Pass query parameters as JSON values such as strings, numbers, arrays, or objects.",
    "QUERY_INPUT_TOO_LARGE": "Keep SQL and parameters focused; remove unused columns or conditions and retry.",
    "QUERY_REJECTED": "Use one read-only SELECT over the tables returned by describe_data; writes and external readers are disabled.",
    "QUERY_TIMEOUT": "Narrow the date range or simplify joins and calculations, then retry.",
    "RELEASE_UNAVAILABLE": "Call describe_data to select a currently published release, then rerun with that release ID.",
    "CURRENT_RELEASE_INVALID": "The current published release is not ready for querying; contact the data service owner.",
    "CURRENT_RELEASE_UNAVAILABLE": "The current data release cannot be read; contact the data service owner.",
    "DOMAIN_NOT_FOUND": "Call describe_data to check the available domains and choose one of them.",
    "TABLE_NOT_FOUND": "Call describe_data to check the available tables for this domain.",
    "COLUMN_NOT_FOUND": "Call describe_data with this domain and table to check the current field names.",
    "SCHEMA_UNAVAILABLE": "The selected table is not available in this release; call describe_data to verify current tables.",
    "QUERY_RESULT_TOO_LARGE": "Select fewer columns, narrow the date range, or aggregate the result, then retry.",
    "RESULT_CAPACITY_EXCEEDED": "The short-term result store is full; retry after older results expire.",
    "RESULT_STORE_INVALID": "The short-term result store is unavailable; contact the data service owner.",
    "CONFIG_INVALID": "The query service configuration is invalid; contact the data service owner.",
    "RESULT_CORRUPT": "This saved result cannot be read. Run the query again against the same release.",
    "RESULT_NOT_FOUND": "The result is unavailable or expired. Run the query again against the same release.",
    "PAGE_OFFSET_INVALID": "Use offset 0 or a next_offset returned by the previous page.",
    "PAGE_SIZE_INVALID": "Use a page size from 1 to 500.",
    "PAGE_ROW_TOO_LARGE": "Select fewer columns or shorten large text fields with substr, then rerun the query.",
    "QUERY_FAILED": "Check the selected release and fields, reduce the query size, then retry; contact the data service owner if it persists.",
    "INVALID_ARGUMENT": "Use the listed tool arguments; page sizes and CSV chunk limits must be from 1 to 500.",
}

DEFAULT_SCOPE_GUIDANCE = (
    "未指明范围的经营指标默认且仅查询语培市场总计、被动、全部新老生。"
    "例如用户说“帮我导出本月的人头和签约现金”，只调用一次 team_metrics，"
    "filters 只传本月 period_id 和 metric=[heads,cash]，直接导出该 result_id 的两行。"
    "只有用户明确提到其他业务线、主动、各团队或所有范围时才覆盖相应维度。"
)

TOOL_DESCRIPTIONS["read_dashboard_data"] += " " + DEFAULT_SCOPE_GUIDANCE

INSTRUCTIONS = (
    DEFAULT_SCOPE_GUIDANCE + " " +
    "Read-only business data service. Call describe_business_context and read_business_context for relevant confirmed definitions and official scorecard scope before interpreting metrics. Call describe_data to select the current published domain and table "
    "and inspect actual fields. Run SQL only with a release ID returned by the service. Results are isolated "
    "to the calling key and kept briefly for paging and CSV chunks. CSV is returned inside MCP; there is no "
    "separate download URL."
)

_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


class ServiceConfigError(ValueError):
    """A required service configuration is missing or invalid."""


class KeyAuthMiddleware:
    """Verify the independent bearer key on each HTTP request."""

    def __init__(self, app: Any, keys_file: Path):
        self.app = app
        self.keys_file = keys_file

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope.get("path") == "/health":
            await self.app(scope, receive, send)
            return

        authorization_headers = [value for name, value in scope.get("headers", [])
                                 if name.lower() == b"authorization"]
        authorization = (authorization_headers[0].decode("latin-1")
                         if len(authorization_headers) == 1 else "")
        scheme, separator, token = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or not token or " " in token:
            await JSONResponse({"error": "AUTH_REQUIRED"}, status_code=401,
                                headers={"WWW-Authenticate": "Bearer"})(scope, receive, send)
            return

        try:
            key_id = await anyio.to_thread.run_sync(lambda: key_id_for_token(self.keys_file, token))
        except KeyStoreError:
            await JSONResponse({"error": "AUTH_REGISTRY_UNAVAILABLE"}, status_code=503)(scope, receive, send)
            return
        if key_id is None:
            await JSONResponse({"error": "AUTH_INVALID"}, status_code=401,
                                headers={"WWW-Authenticate": "Bearer"})(scope, receive, send)
            return

        state = scope.setdefault("state", {})
        state["business_data_key_id"] = key_id
        context_token = CURRENT_KEY_ID.set(key_id)
        try:
            await self.app(scope, receive, send)
        finally:
            CURRENT_KEY_ID.reset(context_token)


def _result(payload: dict[str, Any], *, error: bool = False,
            content: list[types.TextContent] | None = None) -> types.CallToolResult:
    if content is None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        content = [types.TextContent(type="text", text=body)]
    return types.CallToolResult(
        content=content,
        structuredContent=payload,
        isError=error,
    )


def _tool_error(code: str) -> types.CallToolResult:
    safe_code = code if _CODE.fullmatch(code) else "QUERY_FAILED"
    error = {"code": safe_code}
    hint = QUERY_ERROR_HINTS.get(safe_code)
    if hint is not None:
        error["hint"] = hint
    payload = {"schema_version": "business_data_mcp.v1", "status": "error", "error": error}
    return _result(payload, error=True)


def _worker_code(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    return code if isinstance(code, str) and _CODE.fullmatch(code) else "QUERY_FAILED"


def _models() -> dict[str, Any]:
    config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)
    return {
        "describe_business_context": create_model("describe_business_context_arguments", __config__=config),
        "read_business_context": create_model("read_business_context_arguments", __config__=config, source_id=(str, ...)),
        "describe_data": create_model(
            "describe_data_arguments", __config__=config,
            domain=(Literal["training", "study"] | None, None),
            table=(str | None, None),
        ),
        "read_dashboard_data": create_model(
            "read_dashboard_arguments", __config__=config,
            dataset=(str, ...), expected_release=(str, ...),
            filters=(dict[str, str | list[str]] | None, None),
            page_size=(int, Field(default=100, ge=1, le=500)),
        ),
        "query_data": create_model(
            "query_data_arguments", __config__=config,
            domain=(Literal["training", "study"], ...),
            sql=(str, ...),
            expected_release=(str, ...),
            parameters=(dict[str, Any] | list[Any] | None, None),
            page_size=(int, Field(default=100, ge=1, le=500)),
        ),
        "read_query_result": create_model(
            "read_query_result_arguments", __config__=config,
            result_id=(str, ...),
            offset=(int, Field(default=0, ge=0)),
            limit=(int, Field(default=100, ge=1, le=500)),
        ),
        "export_query_csv": create_model(
            "export_query_csv_arguments", __config__=config,
            result_id=(str, ...),
            offset=(int, Field(default=0, ge=0)),
            limit=(int, Field(default=500, ge=1, le=500)),
        ),
    }


def create_server(
    current_path: Path,
    results_root: Path,
    *,
    worker_factory: Any = BusinessDataQuery,
    context_root: Path | None = None,
) -> Server:
    """Build the official MCP SDK server, with per-key worker result storage."""
    models = _models()
    workers: dict[str, Any] = {}
    query_slots = anyio.Semaphore(2)

    def worker_for_request() -> Any:
        key_id = CURRENT_KEY_ID.get()
        if key_id is None:
            raise ServiceConfigError("AUTH_REQUIRED")
        worker = workers.get(key_id)
        if worker is None:
            # key_id is generated by the CLI as key_<hex UUID>, never supplied by a client.
            worker = worker_factory(current_path, results_root / key_id, capacity_root=results_root)
            workers[key_id] = worker
        return worker

    async def list_tools(context: Any, params: Any) -> types.ListToolsResult:
        annotations_by_tool = {
            name: types.ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                        idempotentHint=name not in {"query_data", "read_dashboard_data"}, openWorldHint=False)
            for name in TOOL_DESCRIPTIONS
        }
        tools = [
            types.Tool(name=name, description=description,
                       inputSchema=models[name].model_json_schema(),
                       annotations=annotations_by_tool[name])
            for name, description in TOOL_DESCRIPTIONS.items()
        ]
        return types.ListToolsResult(tools=tools)

    async def call_tool(context: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        if params.name not in models:
            return _tool_error("TOOL_NOT_ALLOWED")
        try:
            validated = models[params.name].model_validate(params.arguments or {}).model_dump()
        except (ValidationError, TypeError, ValueError):
            return _tool_error("INVALID_ARGUMENT")
        try:
            if params.name == "describe_business_context":
                return _result(describe_business_context())
            if params.name == "read_business_context":
                return _result(await anyio.to_thread.run_sync(lambda: read_release_business_context(current_path, context_root, **validated)))
            worker = worker_for_request()
            if params.name == "describe_data":
                payload = await anyio.to_thread.run_sync(lambda: worker.describe(**validated))
            elif params.name == "read_dashboard_data":
                async with query_slots:
                    payload = await anyio.to_thread.run_sync(lambda: worker.read_dashboard_data(**validated))
            elif params.name == "query_data":
                async with query_slots:
                    payload = await anyio.to_thread.run_sync(lambda: worker.query(**validated))
            elif params.name == "read_query_result":
                payload = await anyio.to_thread.run_sync(lambda: worker.read_page(**validated))
            else:
                payload = await anyio.to_thread.run_sync(lambda: worker.export_csv(**validated))
            if params.name == "export_query_csv":
                text_payload = {key: value for key, value in payload.items() if key != "csv_text"}
                content = [
                    types.TextContent(type="text", text=json.dumps(text_payload, ensure_ascii=False,
                                                                    separators=(",", ":")) + "\n"),
                    types.TextContent(type="text", text=payload["csv_text"]),
                ]
                return _result(text_payload, content=content)
            return _result(payload)
        except ServiceConfigError as exc:
            return _tool_error(str(exc))
        except Exception as exc:
            return _tool_error(_worker_code(exc))

    return Server(
        "Business Data",
        version="0.1.0",
        instructions=INSTRUCTIONS,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


async def _health(request: Request) -> Response:
    return JSONResponse({"status": "ok"})


def create_app(
    current_path: Path,
    results_root: Path,
    keys_file: Path,
    *,
    allowed_hosts: list[str] | None = None,
    allowed_origins: list[str] | None = None,
    worker_factory: Any = BusinessDataQuery,
    context_root: Path | None = None,
) -> Any:
    """Build the MCP Starlette app with bearer auth and public health endpoint."""
    # Fail startup on a missing or malformed registry, while still re-reading it
    # per request so later issue/revoke operations take effect immediately.
    list_keys(keys_file)
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts if allowed_hosts is not None else _csv_setting(ALLOWED_HOSTS_ENV, DEFAULT_ALLOWED_HOSTS),
        allowed_origins=allowed_origins if allowed_origins is not None else _csv_setting(ALLOWED_ORIGINS_ENV, ""),
    )
    if not security.allowed_hosts:
        raise ServiceConfigError("ALLOWED_HOSTS_REQUIRED")
    server = create_server(current_path, results_root, worker_factory=worker_factory, context_root=context_root)
    app = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        host="127.0.0.1",
        transport_security=security,
        custom_starlette_routes=[Route("/health", _health, methods=["GET"])],
    )
    return KeyAuthMiddleware(app, keys_file)


def _csv_setting(name: str, default: str) -> list[str]:
    value = os.environ.get(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


def _required_path(name: str) -> Path:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ServiceConfigError(f"{name}_REQUIRED")
    return Path(value).expanduser()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="business-data-mcp")
    parser.add_argument("--host", default=os.environ.get(HOST_ENV, "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get(PORT_ENV, "8765")))
    return parser


def main(argv: list[str] | None = None) -> int:
    sys.dont_write_bytecode = True
    try:
        args = build_parser().parse_args(argv)
        if not 1 <= args.port <= 65535:
            raise ServiceConfigError("PORT_INVALID")
        current_path = _required_path(CURRENT_ENV)
        results_root = _required_path(RESULTS_ENV)
        keys_file = _required_path(KEYS_FILE_ENV)
        allowed_hosts = _csv_setting(ALLOWED_HOSTS_ENV, DEFAULT_ALLOWED_HOSTS)
        allowed_origins = _csv_setting(ALLOWED_ORIGINS_ENV, "")
        app = create_app(current_path, results_root, keys_file,
                         allowed_hosts=allowed_hosts, allowed_origins=allowed_origins,
                         context_root=Path(os.environ[CONTEXT_ENV]).expanduser() if os.environ.get(CONTEXT_ENV) else None)
        import uvicorn

        uvicorn.run(app, host=args.host, port=args.port, proxy_headers=False, log_level="info")
        return 0
    except KeyboardInterrupt:
        return 0
    except (ServiceConfigError, KeyStoreError) as exc:
        print(f"business-data-mcp: {exc}", file=sys.stderr)
        return 1
    except Exception:
        print("business-data-mcp: SERVER_UNAVAILABLE", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
