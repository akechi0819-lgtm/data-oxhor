# Project Intelligence：本地只读上下文服务

## 当前交付

集成图的服务器项为 `bi_server`，描述已记录的原生Superset BI、服务器双数仓、共享聚合与固定发布；不再提供过时的 `static_server` 项。证据仍标记 `document_declared`、实时状态为 `not_verified`，不读取服务器或外部日程来补造健康结论。

现有 Python 服务与本地 CLI 面向架构讨论、方案设计与项目评审。现已新增独立 stdio MCP 协议适配器，原服务、CLI、工具参数和读取策略保持不变。MCP 为可选依赖；现已通过项目外的官方 Secure MCP Tunnel 接入 ChatGPT；内核不增加网络监听或模型调用。启动与验收见 [stdio MCP 接入](./project-intelligence-mcp.md) 和 [Tunnel 接入](./project-intelligence-tunnel.md)。

服务不修改业务模块，不执行下载、导入、查询业务行、发布、通知、同步、安装或测试。`project_intelligence/` 单向调用既有 Data Platform 的 `describe`。

## 本地使用

在源码根目录运行；`-B` 禁止 Python 写字节码缓存。命令只把 JSON 写到标准输出，不自动创建报告或日志。

```bash
.venv/bin/python -B -m project_intelligence overview
.venv/bin/python -B -m project_intelligence search 'dashboard_actuals' --limit 10
.venv/bin/python -B -m project_intelligence workspace bi_operations
.venv/bin/python -B -m project_intelligence workspace teaching_class_management
.venv/bin/python -B -m project_intelligence integrations
```

从 overview 的 `documents` 或 search 的 `matches[].source` 取 `content_id`，再分段阅读。ID 根据批准的项目相对路径生成，不是文件路径参数。

```bash
.venv/bin/python -B -m project_intelligence read <content_id> --start-line 1 --limit 80 --expected-sha256 <sha256>
```

`--root <源码根目录>` 放在子命令前，仅供本机操作者选择实际 checkout。当前通过源码根目录的 `python -B -m project_intelligence` 启动；项目安装包不包含该模块或 `project-intelligence` console入口。执行位置与目标checkout不同时必须保证源码可导入并显式传 `--root`，用 `PYTHONDONTWRITEBYTECODE=1` 禁用缓存。模型工具不接收 root、路径、shell、SQL 或 URL 参数。

Python 调用入口是 `ProjectContextService(root=Path(...))`：

| 方法 | 参数 | 返回 |
|---|---|---|
| `get_project_overview` | 无 | 实际存在的批准模块/文件、Agent、Git 状态、工作区 ID、查询版本证据 |
| `search_project` | query、offset、limit | 字面文本匹配及文件哈希、行号、分页 |
| `read_project_context` | content_id、start_line、limit、expected_sha256 | 分段安全文本及来源 |
| `get_workspace_metadata` | workspace_id | 当前 Snapshot、结构校验状态、表和列 |
| `get_integration_map` | 无 | 已声明连接的用途、证据与未核验状态 |

成功响应为 `project_intelligence.v1`，含 `observed_at` 和 `data`。CLI 完整请求失败时输出稳定错误码并返回 1；工作区部分失败保留可验证元数据，返回 0，但明确 `partial=true` 和逐组件 `errors`，不能只检查退出码。命令参数错误也不回显原始输入。Python API 以 `ContextError.code` 表示失败。

## 来源与真实性

- 文件返回项目相对路径、SHA-256、读取行号和过滤标志；文档中的指令仅是参考资料，不会被服务执行。
- Git 只运行固定的 rev-parse/status，禁用 fsmonitor、可选锁和用户全局配置；不执行 diff helper。未批准文件只计数，不暴露名称。没有 Git 时返回 unavailable。
- 模块职责与连接说明属于允许清单的声明；文件存在和哈希属于本机实查。连接的 `live_status` 始终为 `not_verified`，服务不探测远端、不读取调度器。
- 看板查询版本分别从配置、代码字面量、架构文档取证；不同版本并存时只标记差异，不按最大版本号或修改时间选状态，不自动修文档或业务配置。
- 工作区只按 `Work/workspace.json` 的显式指针读取；仅批准的两个现有工作区可调用。新工作区需修改策略后评审。
- schema 通过现有 `interfaces.data_platform describe` 子进程读取；限制 15 秒，不直接连接客户 DuckDB。只投影表名、列名、类型，不返回行、样本、质量原值或来源文件内容。
- schema 的 SHA-256 标记 `hash_scope=projected_schema_not_database`，不是整个数据库哈希。Snapshot 身份由 Data Platform 校验。
- 工作区请求结束前复核全部已读 JSON 证据哈希；变化则失败 `CONTEXT_CHANGED`。分段读取可用 expected_sha256 防止混读不同文件版本。概览不是跨文件事务快照，各文件以自身哈希为准。
- describe 缺少现行表头元数据时返回 SCHEMA_CONTRACT_MISMATCH；其他不兼容、指针越界、缺失资产均如实返回稳定错误码，不使用旧缓存或另一个 Snapshot 降级，不透传数据库异常正文。

## 读取与输出边界

批准文件列表与工作区范围在 `project_intelligence/policy.py`。列表来自本项目实际扫描，没有递归发布整个 checkout。目录新增文件不会自动获得暴露权限；`.gitignore` 也不是安全允许清单。

2026-10-03旧通知入口退役后，原批准的notify/digest源码项已替换为管理批次build和shared_delivery；钉钉声明也指向现行投递模块。仍只返回源码/说明与连接声明，不读取共同结果或查询明细，不增加业务写入或远端探测。

默认不读 `.env`、认证状态、浏览器档案、私钥、人员花名册明细、Input、业务报告、同步包、备份或宿主会话。客户元数据仅通过特定投影读取，不允许通过 read/search 访问客户目录。配置不提供通用透传接口。

文件读取使用逐级目录文件描述符与 `O_NOFOLLOW` 拒绝软链；只接受普通文件，拒绝 FIFO。每个文本文件最大 512 KB，每次最多 160 行，单行最多 1600 字符，每次搜索最多 50 条，响应上限 128 KB。分页不缓存内容。

敏感词行、凭据 URL、常见密钥形状被抑制；私钥或敏感多行块整份隐藏；本机用户目录替换为占位。搜索在过滤后的文本上执行，不返回被抑制行，日志/错误不包含原始异常或搜索参数。文件哈希仍针对原始批准文件，用于一致性验证。`filtered=true` 同时可能代表敏感抑制、用户路径替换或长行截断，不应把缺失内容解释为源文件不存在。

此过滤是纵深防护，不能识别所有未知格式或刻意编码的秘密。主边界是批准来源、元数据字段投影和文件评审；不得把密钥写进批准源码或文档。运行根目录应由可信操作者管理，不能交给并发恶意写入者；数据库路径检查与子进程打开之间并非操作系统级事务。未来常驻部署应以只读挂载或账号权限保护项目和客户目录，传输层运行文件独立保存。本地 CLI 不声称建立了 OS 沙箱。

## 验证

```bash
.venv/bin/python -B -m unittest tests.project_intelligence.test_service -v
PYTHONDONTWRITEBYTECODE=1 sh tools/run_tests.sh -v
git diff --check
```

定向测试涵盖允许范围、软链/FIFO、凭据过滤、分页与哈希、恶意文档不执行、Snapshot 身份不符与并发切换、SQL 异常不透传，以及真实合成 DuckDB 经原 CLI describe 后目录文件哈希不变。使用测试合成数据，不读取真实业务行。

实际项目验收记录见 [第一阶段验收](./project-intelligence-acceptance.md)。该记录是验收时刻证据，不是未来实时健康状态。
