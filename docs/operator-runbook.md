> **2026-10-26 日期回执摘要（本轮未实读服务器或调度平台）**：正式产品为 Superset 原生 BI。服务器 raw receiver、root 只读历史基线、受限双 Snapshot / quality / 共享计算 worker 和固定 publisher 已部署；真实 Dot 批次完成双 Snapshot、quality 查询并实际运行到39张表，最终因截止不匹配以 `failed/published=false` 结束，没有发布 raw release。Mac `p5.daily` 是仍存在的手动入口，并有更新 `daily-20261026_094052` 的日期记录，不代表长期默认路径。有效新包正式发布、持续日更和唯一生产者收口仍待分别验收。Dot 10:00 日程记录针对通知，与 BI 更新分开。详见[部署说明](../dashboard_product/DEPLOYMENT.md)及本页 4.1。

# 本地运维手册

> 下方 2026-10-03—10-12 的 Grok 与静态发布记录均为历史操作，不是当前运行指令。原生 BI 与通知的当前边界见 `dashboard_product/DEPLOYMENT.md`、`monitoring_product/README.md` 和 `SYNC.md`。

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

可选profile为 `core`（DuckDB数据运行时）、`test`（工作簿/图片/日期及项目测试）和 `full`（再增加BI浏览器和通知传输）。`full`不包含宿主PPT、文档转换、音视频或模型SDK。全量测试统一使用 `sh tools/run_tests.sh`，覆盖主测试、看板和监控；PPT Master由宿主全局Skill管理，不在项目extras或预检脚本中安装。已有 `.venv` 不因依赖声明精简被自动卸载，环境更新时按新profile重建即可。
| Git | 当前代码版本与改动分别以 `git rev-parse HEAD` 和 `git status` 为准；工作树以 `git worktree list` 核对 |

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
  --bridge /absolute/path/to/confirmed-workspace-bridge.json \
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


## 4.1 正式 BI、服务器计算与固定发布

Superset 原生 BI 已正式上线。服务器 raw 接收、受限计算和固定发布程序已部署：worker读取root只读历史基线，在新副本中完成双 Snapshot、两份 quality 查询及共享聚合计算；10月26日真实批次已实际跑到39张表。该批候选 `data_through` 为10月24日，低于业务截止要求10月25日，因此最终状态是 `failed/published=false`，没有调用固定 publisher 切换 current。

同批计算、封存39表、`prepared`、发布队列和正式 `published` 是不同状态。接收／计算到39表不能作为发布通过的证据；物理库 COUNT 门禁在业务截止门禁之后，该批未执行该COUNT检查。raw服务部署本身和已执行的服务器数仓/计算能力已落地；仍待验收的是有效新raw包正式发布、持续日更与唯一生产者收口。对应详情见[固定发布回执](server-raw-fixed-publisher-20261026.md)、[接收部署回执](server-raw-receiver-deployment-20261026.md)和[raw合同](server-raw-pipeline-contract.md)。

10月26日 current `daily-20261026_094052`（数据截止10月25日）由 Mac `dashboard_product.shadow_bi.p5.daily` 手动入口更新，这是具体日期的运行记录；该入口仍存在，但不据此将其列为长期默认路径。正式操作前应确认当前服务器 manifest、候选状态、业务截止、来源质量及明确的发布授权；本轮未实读服务器和调度平台，不推断当前实时状态。`p5.daily` 是会采集、重算和发布的写入入口，若有明确需求使用仍须单独核对身份和授权。

服务器通知适配已部署。10-26 的人工触发中，DeliveryState 有 8 条 `sent` 回执；另一个 HTTP send job 仍保留 `unknown`，其只读对账回执确认这 8 条发送来自此前执行，并标记 `no_send_performed=true`。这不是该 HTTP job 自身成功发送的证明；不得重发这 8 条或清空状态。通知作业控制修复见[回执](notification-job-receipt-repair-20261026.md)。

Dot 每日上海10:00通知日程有10-26建立记录，属于通知触发，不代表 BI 采集／刷新调度；Grok例行按用户要求停止。10-26回执记录 Mac `bi-2` 为ACTIVE/09:40，但本次文档更新没有实读任何调度平台，因此不据此宣称当前启停。有效raw包的门禁、正式发布和唯一生产者切换分别验收；持续日更运行安排也需独立核实。

## 5. 升级策略

DeepSeek Harness 处于 Developer Preview。升级前必须：

1. 记录目标 npm 版本和 integrity；
2. 阅读上游变更；
3. 在隔离工作区验证 Web、Workspace、Skill、受控 Shell、CLI 和文件交付；
4. 通过当前端到端验收后再替换默认版本。

不得把业务逻辑补丁直接打进全局 Harness 包或上游 checkout。

## 6. 常见问题

BI滚动重建仅更新 `br_work_orders` 与 `br_cash`，其他来源槽位保留。重复Snapshot或当前对齐会话未完成会在下载前按现有sync检查拒绝；已有current却缺少manifest/landing/声明来源时明确失败，不把它当首次导入。成功JSON的 `orders/cash` 指向当前Input，`export_orders/export_cash` 指向原导出留存；不再返回成功后已经删除的暂存路径。一般失败会恢复两个输入槽位；如果当前发布状态无法读取或恢复失败，错误会给出本次 `input_backup/` 路径，保留该目录用于恢复，按实际current状态处理。除此之外不新建历史保留或备份服务。

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
| 留学工单清洗参考 | `customers/bi_operations/Input/Reference/留学-FY26-资源表.xlsx` 由现有 `data_acquisition.jobs.work_order_cleaning` 规则读取；当前调用方为线上/线下影子准备及 `online_team`、管理共同事实构建，`rebuild_bi_warehouse` 的主仓滚动合并不调用该清洗器。线上规则处理网络资源/新媒体；线下影子另做国家/条线补充。渠道与国家/条线校正分别计算，不把产品侧重洗当成原始输入或主Snapshot已被改写；语培原值不改 |
| 留学官方记分卡 | `customers/bi_operations/Input/Reference/留学板块-官方记分卡.md` 是业务确认的线上/线下完成值与 FY27 目标，置信度高于数仓；分析时先读它。不 ingest 进 Snapshot，不写入 Bridge，不自动回写看板目标。清洗参考表 `留学-FY26-资源表.xlsx` 不能覆盖本记分卡 |
| `ACTIVE_SESSION_EXISTS` | 先完成当前 Snapshot 的对齐会话，再执行月度刷新 |
| `sync-data` 返回 cleanup warning | 新 Snapshot 已是当前状态；在确认不再占用旧 Run 后手工清理该目录 |
| 客户工作区误入 Git | 使用默认忽略的 `customers/`，交付产品时可整体复制该客户工作区 |
| `ADAPTER_LOAD_FAILED` | 仅针对程序化 `propose --adapter` 入口：检查测试或批处理模块的 `module:attribute` 与 `propose(model_input)`；不要因此开发宿主包装层 |
| 宿主找不到 `ppt-master` | 检查宿主全局 Skill 安装与重启/重新发现；不在项目内恢复 PPT 副本 |
