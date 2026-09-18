# Project Intelligence Secure MCP Tunnel 接入

## 当前结果

2026-09-17 14:54（Asia/Shanghai），ChatGPT 6-Pro 已通过 Secure MCP Tunnel 实际调用全部五个原工具，逐项工具回执均为 `status=ok`。本机托管进程保持运行，状态为 process_running=true、healthy=true、ready=true。

## 范围

本阶段只配置官方 Tunnel、连接现有 stdio MCP 并补充运行说明。`project_intelligence/` 的工具、服务、允许清单和业务代码不变，不新增 HTTP 服务、业务查询或写入能力。

## 已配置身份与本机位置

- Tunnel 名称：Project Intelligence MCP。
- Tunnel ID：`tunnel_6aab8b6389748191a35e693a9663cda3`。
- 关联范围：当前 Personal Platform 组织与个人 ChatGPT 工作区；不发布到公共插件目录。
- 客户端：官方 `openai/tunnel-client` v0.0.14，darwin-arm64。下载自官方 release，压缩包 SHA-256 与同 release 的 SHA256SUMS.txt 一致：`b540493c5bdbcdbb755700c8e2e16597e28b1569e425007e0f73111047bd6a64`。
- 独立运行目录：`/Users/akechi/.local/share/project-intelligence-tunnel/`，目录权限 700；二进制及依赖运行时在 `bin/`。
- 配置：`profiles/project-intelligence.yaml`，只保存 Tunnel ID、非敏感启动参数和凭据文件引用。
- 凭据：`secrets/runtime-api-key`，只供 Tunnel 客户端读取，禁止提交、打印或复制进项目。
- 上游脚本：`mcp-stdio.sh`，固定当前项目、现有 Python 与原 stdio 模块；以空继承环境启动 MCP，隧道密钥不会传入 MCP 进程。
- ChatGPT 应用 ID：`asdk_app_6aab8e55b4548191a7251b8ca03abfe3`，development 模式，仅当前账户连接。
- 凭据保存器：`save-runtime-key.py`，通过 getpass 隐藏输入、验证基本 API Key 格式，并以 600 权限原子替换专用凭据文件；无效输入不改变现有文件。

官方说明：[Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)。本机具体命令已按安装版本的 `help quickstart`、`init --help`、`runtimes connect --help` 核对。

## Tunnel 配置步骤

1. 在 Platform 的 Organization → Tunnels 创建专用 Tunnel，同时关联 Personal 组织及目标 ChatGPT 工作区。上述 Tunnel 已创建，后续复用，不重复创建。
2. 在同组织 API keys 创建独立运行密钥；Restricted，仅 Tunnels Read/Use，不授予模型、文件或其他 API 能力。本次创建表单有效期为 30 天。不要使用 Admin key 运行守护进程。
3. 通过本机隐藏输入保存密钥：

```bash
python3 /Users/akechi/.local/share/project-intelligence-tunnel/save-runtime-key.py
```

4. 配置已由官方 init 生成。复现命令（已有文件时不要加 force 覆盖）：

```bash
cd /Users/akechi/.local/share/project-intelligence-tunnel
./bin/tunnel-client init \
  --sample sample_mcp_stdio_local \
  --profile project-intelligence \
  --profile-dir /Users/akechi/.local/share/project-intelligence-tunnel/profiles \
  --tunnel-id tunnel_6aab8b6389748191a35e693a9663cda3 \
  --control-plane-api-key-ref file:/Users/akechi/.local/share/project-intelligence-tunnel/secrets/runtime-api-key \
  --mcp-command /Users/akechi/.local/share/project-intelligence-tunnel/mcp-stdio.sh \
  --health-listen-addr 127.0.0.1:0
```

## 本机启动与停止

常用启动命令已封装为项目外脚本，并实测复用现有进程（already_running=true）：

```bash
/Users/akechi/.local/share/project-intelligence-tunnel/start-tunnel.sh
```

该脚本只执行下方完整的官方 runtimes connect 命令。v0.0.14 不接受仅传 alias 的简写，仍须指定 MCP 目标；脚本已固定所有必需参数，不接收任意透传参数。


先检查配置和授权：

```bash
cd /Users/akechi/.local/share/project-intelligence-tunnel
./bin/tunnel-client doctor --profile project-intelligence \
  --profile-dir /Users/akechi/.local/share/project-intelligence-tunnel/profiles --explain
```

长期运行使用官方托管进程，不使用 nohup/disown：

```bash
./bin/tunnel-client runtimes connect \
  --alias project-intelligence \
  --profile project-intelligence \
  --profile-dir /Users/akechi/.local/share/project-intelligence-tunnel/profiles \
  --tunnel-id tunnel_6aab8b6389748191a35e693a9663cda3 \
  --runtime-api-key file:/Users/akechi/.local/share/project-intelligence-tunnel/secrets/runtime-api-key \
  --mcp-command /Users/akechi/.local/share/project-intelligence-tunnel/mcp-stdio.sh

./bin/tunnel-client runtimes status project-intelligence --json
./bin/tunnel-client runtimes stop project-intelligence
```

status 必须同时证明进程运行、健康、ready，才能报告连接就绪。停止客户端或电脑离线时 ChatGPT 无法调用。健康页只监听本机回环；不启用 remote UI、HTTP 原始日志或 payload capture。凭据到期后更新私有凭据文件并重启，不修改 MCP 工具。

## ChatGPT 连接配置

1. Developer Mode 已确认开启。
2. 插件 → 创建应用，名称 `Project Intelligence MCP`。
3. 连接选择「隧道」，选中上述专用 Tunnel。
4. 应用层身份验证选择「无身份验证」：本地 stdio MCP 没有 OAuth，访问仍由 Secure MCP Tunnel 的账号、工作区与权限控制；不表示公开匿名 HTTP 服务。
5. 客户端运行且 ready 后创建连接。确认只发现原五个工具，保留现有 ChatGPT 操作确认策略。
6. 实际聊天中选用该插件，要求依次调用 overview、search、read、workspace、integrations，核对返回来源、Snapshot、部分失败和未核验状态。

## 实际调用验收（已完成）

| 项目 | 结果 |
|---|---|
| 官方客户端与下载校验 | v0.0.14 ARM64，SHA-256 匹配 |
| 组织和工作区关联 | Platform 已创建，ChatGPT 列表可见并选中 |
| 凭据 | Restricted，仅 Tunnels Read/Use；项目外 600 权限；配置只引用文件，无明文 key |
| 官方 doctor | ok；stdio 网络探测/OAuth 检查按设计 skip；未安装可选 Codex Tunnel 插件不影响本任务 |
| 托管进程 | process_running=true、healthy=true、ready=true；仅回环管理页 |
| ChatGPT 连接 | 显示“Project Intelligence MCP 已连接”；五个工具均识别为读取 |
| get_project_overview | ok，2026-09-17T06:54:42.672145+00:00 |
| search_project | ok，2026-09-17T06:54:44.339382+00:00；dashboard_actuals，limit=1 |
| read_project_context | ok，2026-09-17T06:54:46.221722+00:00；使用搜索返回 ID/哈希，读取 3 行 |
| get_workspace_metadata | ok，2026-09-17T06:54:47.308607+00:00；bi_operations，partial=false |
| get_integration_map | ok，2026-09-17T06:54:48.225887+00:00；6 类已声明连接 |
| 代码与数据 | 本轮 5 个 MCP 源文件哈希不变；前期基线中 130 个受保护业务/数据文件也均未变化 |

验收在 [ChatGPT 实际测试对话](https://chatgpt.com/c/6aab8eb0-7b60-83ea-88cf-a3a7ec441f6f) 中执行，模型界面为 6 Pro。逐项展开工具调用面板确认了返回值，不仅依赖模型总结；本机 dispatcher 同期记录了五次转发。未创建公开分享链接。应用设置可从 [Project Intelligence MCP](https://chatgpt.com/plugins#settings/Plugins/plugin_asdk_app_6aab8e55b4548191a7251b8ca03abfe3) 打开。

返回的当前 Snapshot 为 `snapshot_bi_operations_20260916_fy25`。`remote_state/live_status=not_verified` 仍指业务外部连接（如 BI、Grok 和发布服务器）未被本服务探测，不代表这次 ChatGPT→Tunnel→本机的链路未验证。`overview.execution` 是原内核的静态描述，保留不改；传输接入事实以本验收记录与运行状态为准。

启动时的回环管理页为 `http://127.0.0.1:61141/ui`，重启后端口可能变化，使用 runtimes status 读取当前地址。官方托管进程的状态、日志与健康 URL 文件位于 `~/Library/Application Support/tunnel-client/`，不进入项目。没有配置开机自动启动，也没有开启 payload capture 或 raw HTTP 日志。

## 凭据复制注意

浏览器自动化剪贴板与系统剪贴板可能隔离。首次人工保存内容格式不符被 doctor 拒绝，未作为有效凭据建立连接；后续从官方 Copy 按钮对应的浏览器剪贴板私下转存到既定文件，临时副本已删除，密钥未进入聊天或项目。后续更新可使用本机手动 Copy + getpass 保存器；不要把密钥粘贴进聊天或命令参数。
