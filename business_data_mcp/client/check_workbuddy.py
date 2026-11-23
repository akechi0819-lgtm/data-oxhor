"""Check the installed business-data connection using the system curl."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

URL = "https://dashboard.apinova.cn/business-mcp/mcp"


def call(connection, method, params):
    # Supply the private header on stdin so it stays out of the process list.
    message = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    result = subprocess.run(
        ["curl.exe" if os.name == "nt" else "curl", "--disable", "--silent",
         "--show-error", "--fail", "--max-time", "90",
         "--header", "@-", "--header", "Content-Type: application/json",
         "--header", "Accept: application/json, text/event-stream",
         "--data-binary", json.dumps(message), URL],
        input="Authorization: " + connection["headers"]["Authorization"] + "\n",
        capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode:
        raise RuntimeError("MCP 请求失败，curl 退出码 %s" % result.returncode)
    body = result.stdout.strip()
    if not body.startswith("{"):
        body = next((line[6:] for line in body.splitlines() if line.startswith("data: ")), "")
    reply = json.loads(body)
    if "error" in reply or "result" not in reply:
        raise RuntimeError("MCP 返回调用错误")
    return reply["result"]


def tool(connection, name, arguments):
    reply = call(connection, "tools/call", {"name": name, "arguments": arguments})
    if reply.get("isError"):
        raise RuntimeError(name + " 调用失败")
    return reply.get("structuredContent") or json.loads(reply["content"][0]["text"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", type=Path, default=Path.home() / ".workbuddy-ai")
    connection = json.loads((parser.parse_args().config_dir / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]["business-data"]
    if connection["url"] != URL:
        raise RuntimeError("连接地址与交接包不符")
    names = {item["name"] for item in call(connection, "tools/list", {})["tools"]}
    if not {"describe_business_context", "read_business_context", "read_dashboard_data", "describe_data", "query_data", "read_query_result", "export_query_csv"} <= names:
        raise RuntimeError("业务工具不完整")
    overview = tool(connection, "describe_data", {})
    info = tool(connection, "describe_data", {"domain": "training", "table": "work_orders"})
    relation = info["table"]["relation"]
    result = tool(connection, "query_data", {"expected_release": overview["release"], "domain": "training",
                  "sql": "SELECT count(*) AS n FROM " + relation})
    if result.get("release") != overview["release"] or result["row_count"] != 1 or not isinstance(result["rows"][0][0], int):
        raise RuntimeError("取数结果校验失败")
    print("连接及只读取数成功。数据截至", overview["data_through"], "工单记录数", result["rows"][0][0])


if __name__ == "__main__":
    try:
        main()
    except (KeyError, ValueError, RuntimeError, OSError, IndexError) as error:
        print(str(error) if isinstance(error, RuntimeError) else "配置或返回格式异常：" + type(error).__name__, file=sys.stderr)
        sys.exit(1)
