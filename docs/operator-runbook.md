# 本地运维手册

## 1. 版本和路径

| 项目 | 当前值 |
|---|---|
| DeepSeek Harness | `@deepseek-ai/dsh@0.1.0-rc.6` |
| 全局命令 | `/Users/akechi/.local/bin/dsh` |
| Harness 共享目录 | `/Users/akechi/.dsh` |
| Python | `>=3.12` |
| DuckDB | `1.5.5` |

开源安装使用项目 extras，不需要手动逐个安装依赖：

```bash
python3 -m pip install "data-oxhor[full]"
```

源码工作区使用：

```bash
sh tools/install_runtime.sh full
```

可选 profile 为 `core`（数据分析）、`test`（项目测试）和 `full`（全部项目 Python 运行时）。全量测试统一使用 `sh tools/run_tests.sh`。PPT Master 由宿主全局 Skill 管理，不在项目 `.venv`、extras 或预检脚本中安装。
| Git | 本地 `main` 已包含 Bridge 对齐向导 S3.5；当前工作树状态以 `git status` 为准 |

Harness 是全局工具，不安装到项目目录。`/Users/akechi/.dsh` 可能包含机器配置和凭据，不纳入项目版本控制。

## 2. Harness 冒烟检查

macOS 可双击项目根目录的 `启动 DeepSeek Harness.command`。快捷方式会复用已经运行的本地服务；若服务未运行，则启动 `dsh web`，等待 HTTP 可用后自动打开默认浏览器。启动后保持终端窗口打开，停止服务使用 `Ctrl-C`。

等价的手动命令：

```bash
/Users/akechi/.local/bin/dsh --version
/Users/akechi/.local/bin/dsh web --host 127.0.0.1 --port 3080
```

另一个终端执行：

```bash
curl -fsSL -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3080
```

预期 HTTP 状态是 `200`。开发模式只绑定 `127.0.0.1`，不要在未配置认证和网络边界时暴露到局域网或公网。停止前台服务使用 `Ctrl-C`。

## 3. 核心模块验证

```bash
python3 -m interfaces.data_platform --help
python3 -m interfaces.business_pack validate
python3 -m interfaces.business_pack describe
python3 -m interfaces.company_bridge validate \
  --bridge artifacts/company_bridge/bridges/company_bridge.bi_operations.v1_2_0.json \
  --pack workspace_modeling/business_pack/packs/education_training_operations_cn/pack.json
python3 -m interfaces.bridge_alignment --help
python3 -m interfaces.workspace_modeling --help
sh tools/run_tests.sh -v
```

当前回归包括查询来源凭据测试。Pack 与主线 Bridge 校验状态均为 `passed`。向导测试中的 fake adapter 只验证候选合同，不代表或替代宿主；`finalize` 必须在 `propose` 产生至少一个候选后才能执行，空候选返回 `CANDIDATES_MISSING`。测试失败时先区分：Python/DuckDB 版本、外部 Golden Case 是否可读、源 SHA-256 是否变化、Pack/Bridge 交叉引用错误，还是代码回归。不要通过修改 Golden 值掩盖源文件变化。

## 4. 模型和密钥

模型 Provider 与 API Key 已在 Harness 的机器级设置中配置，不写入仓库、客户配置样例或日志。2026-08-14 已确认：Harness 真实模型回合可用，模型在项目 Workspace 通过 Shell 执行 `python3 -m interfaces.data_platform --help`，退出码为 0，并发现全部 7 个子命令。

真实主线数据已经通过 `inspect → ingest → describe → quality → query`。Codex 与 DeepSeek Harness 已完成主线 Bridge 的分析和 PPTX 生成验证。S5 Casebook、内测反馈回收和工作区引导路由已完成，可通过 `python3 -m interfaces.casebook --help` 检查入口。

PPT Master 现由宿主全局 Skill 管理。项目只保证交给它的当前 Snapshot 查询结果、口径、时间范围、来源和限制可回查；Quick/Default 路由、运行时依赖、产物门禁和升级由全局 Skill 自己负责。若宿主无法发现 `ppt-master`，先修复宿主全局安装，不在项目内恢复 Quick 脚本或 Skill 副本。

项目 Skill `diagnose-source-overlap` 已在 2026-08-16 由 Harness headless 真实调用，能正确区分全量刷新与多来源并存，并把去重处理路由到 Data Platform 只读查询和保存查询。


## 4.1 看板发布与钉钉

看板日更在云电脑 `/home/box/oxhor/dashboard`，每天 10:00 Asia/Shanghai 跑 `dashboard_product/deploy/publish_static_dashboard.sh`。本机 Codex 定时已停。

C 层环境变量只写在 `dashboard_product/.env.server`（mode 600），模板见 `dashboard_product/.env.server.example`：

| 变量 | 用途 |
|---|---|
| `SERVER_HOST` / `SERVER_PORT` / `SERVER_USER` / `SERVER_PASSWORD` | 静态分册和钉钉素材 SCP |
| `NOTIFY_PUBLIC_ORIGIN` | 钉钉图片/表格公网前缀 |
| `DINGTALK_WEBHOOK_<CHANNEL>` / `DINGTALK_SECRET_<CHANNEL>` | 五通道：`ONLINE_PRIVATE`、`ONLINE_PLATFORM`、`OFFLINE_YOUTH`、`OFFLINE_HIGH_SCHOOL`、`OFFLINE_UNIVERSITY` |

云电脑独立运行必须 CopyToBox 该文件，禁止进 Git、禁止贴聊天。缺 webhook 的通道会被跳过。钉钉发送：

```bash
python3 -m dashboard_product.notify send --artifact <artifact.json> --dry-run
python3 -m dashboard_product.notify send --artifact <artifact.json>
```

冒烟：`python3 -m unittest discover -s dashboard_product/tests -v`；公网 `http://dashboard.apinova.cn/healthz` 匿名 200，未登录业务页 401。

## 5. 升级策略

DeepSeek Harness 处于 Developer Preview。升级前必须：

1. 记录目标 npm 版本和 integrity；
2. 阅读上游变更；
3. 在隔离工作区验证 Web、Workspace、Skill、受控 Shell、CLI 和文件交付；
4. 通过当前端到端验收后再替换默认版本。

不得把业务逻辑补丁直接打进全局 Harness 包或上游 checkout。

## 6. 常见问题

| 现象 | 检查 |
|---|---|
| `dsh` 找不到 | 使用绝对路径并检查 `/Users/akechi/.local/bin` 是否在 `PATH` |
| Web 无法访问 | 确认进程仍在、端口 `3080` 未占用、绑定地址是 `127.0.0.1` |
| Workspace 能开但 CLI 不可用 | 检查工作目录、Python 环境、Shell 权限和 `python3 -m interfaces.data_platform --help` |
| 模型无法回复 | 检查 Provider、API Key、额度和网络，不修改业务代码 |
| 查询被拒绝 | 先确认 SQL 是否只读、是否引用外部 reader 或系统目录 |
| Snapshot 冲突 | 使用新的 `run_id` 和显式输出目录，不覆盖已发布 Snapshot |
| 向导 `awaiting_confirmation` / 退出 2 | 宿主向客户展示问题，理解自由回答后把 option、原回答和确认人传给 `answer` |
| 月度文件更新 | 先完成当前对齐会话；替换 `Input/Data/<source_id>` 当前文件并用新 `snapshot_id` 执行 `sync-data`，向导成功切换后自动删除旧 Snapshot |
| `ACTIVE_SESSION_EXISTS` | 先完成当前 Snapshot 的对齐会话，再执行月度刷新 |
| `sync-data` 返回 cleanup warning | 新 Snapshot 已是当前状态；在确认不再占用旧 Run 后手工清理该目录 |
| 客户工作区误入 Git | 使用默认忽略的 `customers/`，交付产品时可整体复制该客户工作区 |
| `ADAPTER_LOAD_FAILED` | 仅针对程序化 `propose --adapter` 入口：检查测试或批处理模块的 `module:attribute` 与 `propose(model_input)`；不要因此开发宿主包装层 |
| 宿主找不到 `ppt-master` | 检查宿主全局 Skill 安装与重启/重新发现；不在项目内恢复 PPT 副本 |
