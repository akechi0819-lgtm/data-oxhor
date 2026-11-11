# 远程 Business Data MCP 部署

## 服务边界

- 外部 MCP URL：`https://dashboard.apinova.cn/business-mcp/mcp`。同域现有 TLS 证书终止于 Nginx；Nginx 去掉 `/business-mcp/` 前缀后，只转发到 `127.0.0.1:8765`。业务端口不监听公网。
- `business-mcp` 是独立 `nologin` 用户，使用 `/srv/business-data-mcp/venv`；不复用 BI 虚拟环境。只读业务代码从独立源码目录安装。
- Key registry 位于 `/etc/business-data-mcp/keys.json`，服务只读哈希。发行 Key 只经 `business-data-mcp-keys` 运维 wrapper 调用；wrapper 在返回一次性明文前恢复 `root:business-mcp 0640`，避免 CLI 原子替换后服务暂时无法读取。
- 查询结果位于 `/var/lib/business-data-mcp/results`。应用总容量为 1 GiB，查询最多两项并发；单结果输出最多 128 MiB，活动查询预留覆盖 128 MiB 输出与 256 MiB DuckDB spill。具体常量以 `business_data_mcp/query.py` 为准。
- `systemd-tmpfiles` 每 5 分钟只扫描 MCP 结果树，按 mtime 在 24 小时后删除结果，也会清理已撤销 Key 的结果。读取不会延长保存时间；临时 reservation 在 2 小时后清理，`.capacity.lock` 保留以维持跨进程锁。
- MCP 独立 cgroup 限制为 3 GiB 内存、2 CPU、32 个任务，禁用 swap；`OOMPolicy=kill` 会在 OOM 后终止该服务的剩余进程。查询子进程继承此 cgroup。

## 当前 SQL release 只读授权

`acl_sync.py` 在服务启动时和 `/var/lib/shadow-bi/current` 切换后核对显式 current。对 SQL release，验证 `candidate.json`、`release.json`、仓库身份与来源元数据后，只为当前 release 所需路径授予目录遍历权限，并仅对 `candidate.json`、`release.json`、`warehouse.duckdb` 和 `landing-description.json` 授予读权限。其他 release 和仓库目录中的兄弟文件不在 allowlist 内。

兼容的旧 release 若没有 SQL candidate，才使用 foundation 双 Snapshot 检查：验证 `prepared.json`、`library_manifest.json`、两个 Snapshot 身份和工作区指针，并只授权上述元数据、两个当前 Snapshot 的仓库及 `snapshot_manifest.json`。当前 SQL 单仓路径不读取 foundation Snapshot 文件。

换版时撤销旧 current 的 ACL，再授予新 release 所需权限；同步失败时保持拒绝访问，不回退旧 release。默认 ACL 无法穿透服务器 0700/0600 发布权限，因此部署使用独立 systemd path watcher；切换 current 到 ACL 同步完成之间，查询可能短暂因权限尚未就绪而失败。

## 关键运行单元

- `business-data-mcp.service`：MCP HTTP 应用与 cgroup 限额。
- `business-data-mcp-acl-sync.path` / `.service`：监听 current 原子切换并收敛只读 ACL。
- `business-data-mcp-results-clean.timer` / `.service`：每 5 分钟运行一次、只清理 MCP 结果目录。

Key token 不写入服务器 registry 或审计文件；一次性本机接入文件应保存在 `.local/` 下并限制为当前用户可读。
