# Project Intelligence stdio MCP

## 当前状态

2026-09-17 已完成本机 stdio Server 与协议验收。仅新增 `project_intelligence/mcp_server.py`，直接调用原 `ProjectContextService`。`service.py`、`policy.py`、原 CLI 和业务代码未修改。该 stdio 阶段没有配置 Tunnel。后续现已通过官方 Secure MCP Tunnel 接入 ChatGPT，见 [Tunnel 接入与实测](./project-intelligence-tunnel.md)；未新增 HTTP/SSE MCP 服务或业务工具。

## 安装与启动

使用项目现有 Python 3.12 环境。MCP SDK 固定为官方 `mcp==2.2.0`，可选 extra 名为 `mcp`。当前本机已安装并通过 `pip check`。

```bash
cd '/Users/akechi/Desktop/manager -CowH'
.venv/bin/python -m pip install 'mcp==2.2.0'
.venv/bin/python -B -m project_intelligence.mcp_server \
  --root '/Users/akechi/Desktop/manager -CowH'
```

安装整个项目时使用 `python -m pip install '.[mcp]'`，将生成 `project-intelligence-mcp` 入口；使用该入口时设置 `PYTHONDONTWRITEBYTECODE=1`。源码运行优先使用上面的 `python -B -m`，不要求重新安装项目。

这是长驻 stdio 子进程：正常启动后等待客户端输入 JSON-RPC，不打印横幅或就绪文本。由 MCP 客户端启动和管理；stdin EOF 或 Ctrl-C 停止。工作目录须能导入本项目；root 必须由本机操作者显式指定，不可由模型工具参数或客户端 roots 改写。

本地客户端启动参数（不是 ChatGPT URL 配置）：

```json
{
  "command": "/Users/akechi/Desktop/manager -CowH/.venv/bin/python",
  "args": [
    "-B", "-m", "project_intelligence.mcp_server",
    "--root", "/Users/akechi/Desktop/manager -CowH"
  ],
  "cwd": "/Users/akechi/Desktop/manager -CowH"
}
```

参数以数组传递，支持项目路径中的空格，不拼接 shell 命令。新适配器不扩展原文件允许清单。

## 协议合同

- Server 名称：`Project Intelligence`，版本 `0.1.0`。
- 仅提供原五个工具：`get_project_overview`、`search_project`、`read_project_context`、`get_workspace_metadata`、`get_integration_map`。
- 输入 JSON Schema 从现有服务方法的签名与类型生成，保持参数名称和默认值；严格类型，拒绝额外参数，不接受 root、任意路径、SQL、shell 或 URL。
- 每个工具标记 readOnlyHint=true、destructiveHint=false、idempotentHint=true、openWorldHint=false；真实边界仍由原服务约束。
- 同一原始服务 JSON 同时放入 structuredContent 和一个 JSON 文本内容块，保留 observed_at、哈希、来源、partial 和组件错误。没有更改业务语义或内部响应版本。
- 原 ContextError 转为 isError=true 和现有稳定错误码；参数错误为 INVALID_ARGUMENT，未知工具为 TOOL_NOT_ALLOWED，未预期异常为 CONTEXT_UNAVAILABLE。
- 工作区的部分失败仍是有效服务响应，isError=false、partial=true，不能将其当作 schema/业务可用。
- SDK 负责握手、协议协商、通知和 stdio；没有自行实现 JSON-RPC 或旧协议兼容层。采用官方 low-level Server 回调，是为了直接控制结构化失败并避免参数错误回显输入。
- 服务调用在线程中执行，避免文件读取与 describe 阻塞协议循环；不增加自动重试、缓存、调度或外部访问。

stdout 只供协议使用；独立 Server 进程关闭 SDK 日志，stderr 只在启动失败时写固定错误码，不打印参数、原始异常或回溯。原内容过滤与源文件允许清单不变，沿用 [本地服务安全边界](./project-intelligence.md)，不宣称 OS 沙箱或任意秘密识别能力。

## 本地验收（2026-09-17）

命令：

```bash
.venv/bin/python -B -m unittest \
  tests.project_intelligence.test_service \
  tests.project_intelligence.test_mcp -v
```

结果：27/27 通过。其中原服务测试 18 项，新 MCP 测试 9 项。没有 skip；当前 SDK 与依赖检查通过。本轮未重跑无改动的全部业务回归；第一阶段旧查询对比失败在该次 MCP 验收中未修复；2026-09-18 已改为核对运行配置声明的 v10，相关测试通过。

| 验收 | 结果 |
|---|---|
| 真进程握手 | initialize → initialized 成功；显式协商 2025-11-25；另测 SDK auto 协商成功 |
| 工具发现 | 恰好五个原工具，输入字段一致、额外参数被拒绝、只读标注齐全 |
| 工具调用 | 五个工具均经真实 stdio 调用；合成数据结果与直接调用原服务的 data 完全一致 |
| 部分失败 | Bridge 未配置等 partial 响应保持原语义，不伪装成完整成功 |
| 安全错误 | 错误类型、未知工具、越界内容 ID、旧哈希、底层异常均返回稳定错误，不回显敏感诱饵 |
| 协议通道 | stdout 全部可解析为 MCP JSON；错误请求后仍可调用；stderr 无敏感内容；EOF 正常退出 |
| 无写入 | 合成目录的文件集合/哈希不变；实盘 130 个原服务、业务代码、配置和当前数据库文件与施工前哈希一致 |
| 真实项目 | overview、search、read、workspace、integrations 均调用成功 |
| 运营 Snapshot | snapshot_bi_operations_20260916_fy25，describe 返回 passed |
| 教学工作区 | 如实返回 BRIDGE_NOT_CONFIGURED、SCHEMA_CONTRACT_MISMATCH |
| 外部连接 | 返回 6 类已声明连接，保持未实查，不发出网络探测 |

测试通过临时合成工作区执行安全场景，不在真实客户数据上做写操作。实盘验收仅输出元数据摘要。进程均在测试结束时退出，没有残留后台服务。

## ChatGPT 接入（已完成）

后续接入阶段已完成官方 Tunnel 配置与 ChatGPT 6-Pro 五工具实测，服务与适配器代码保持不变。Tunnel ID、项目外运行目录、凭据隔离、启动/停止命令和真实回执见 [Secure MCP Tunnel 接入](./project-intelligence-tunnel.md)。本文件上方的验收仍特指本地 stdio 阶段。
