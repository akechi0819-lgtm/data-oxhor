# 本地运维手册

## 1. 版本和路径

| 项目 | 当前值 |
|---|---|
| DeepSeek Harness | `@deepseek-ai/dsh@0.1.0-rc.6` |
| 全局命令 | `/Users/akechi/.local/bin/dsh` |
| Harness 共享目录 | `/Users/akechi/.dsh` |
| Python | `>=3.12` |
| DuckDB | `1.5.5` |
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
python3 -m interfaces.data_foundation --help
python3 -m interfaces.business_pack validate
python3 -m interfaces.business_pack describe
python3 -m interfaces.company_bridge validate \
  --bridge artifacts/company_bridge/bridges/company_bridge.v1_2_0.json \
  --pack business_pack/packs/education_training_operations_cn/pack.json
python3 -m interfaces.bridge_alignment_wizard --help
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

当前回归包括 Quick 与查询来源凭据测试。Pack 与主线 Bridge 校验状态均为 `passed`。完整测试会额外暴露 vendored PPT Master 文件树摘要与 pinned metadata 的既有不一致；这不是 Quick 代码失败，不能修改上游目录或摘要来掩盖。向导测试中的 fake adapter 只验证候选合同，不代表或替代宿主；真实 Harness 教务案例是 S3.5 历史验证。`finalize` 必须在 `propose` 产生至少一个候选后才能执行；空候选返回 `CANDIDATES_MISSING`。测试失败时先区分：Python/DuckDB 版本、外部 Golden Case 是否可读、源 SHA-256 是否变化、Pack/Bridge 交叉引用错误，还是代码回归。不要通过修改 Golden 值掩盖源文件变化。

## 4. 模型和密钥

模型 Provider 与 API Key 已在 Harness 的机器级设置中配置，不写入仓库、客户配置样例或日志。2026-08-14 已确认：Harness 真实模型回合可用，模型在项目 Workspace 通过 Shell 执行 `python3 -m interfaces.data_foundation --help`，退出码为 0，并发现全部 7 个子命令。

真实主线数据已经通过 `inspect → ingest → describe → quality → query`；教务 Bridge 只保留为 S3.5 历史兼容性验证，当前 S4 不再导入教务数据。S4 已把固定版本 PPT Master 放入 `.agents/skills/ppt-master`，可用以下命令分别检查 attribution 与项目回归：

```bash
.venv/bin/python .agents/skills/ppt-master/scripts/attribution_guard.py
.venv/bin/python -m unittest tests.foundation.test_query_service tests.test_s4_ppt_quick -v
```

Codex 与 DeepSeek Harness 已完成主线 Bridge 的分析和 PPTX 生成验证。S4 后续只需用现金明细和工单的新版冻结分析做 Quick 性能回归，核对 `validation/quick_run.json` 中确定性命令的耗时与退出码；这不是 Session 或 Deliverables 平台开发。首轮关闭自动更新、外部研究、生图、TTS、旁白和本地 Web 辅助界面。

首次或干净机器上的 S4 PPT 运行环境必须由项目脚本建立，不依赖系统 Python：

```bash
sh tools/install_s4_ppt_runtime.sh
.venv/bin/python tools/s4_ppt_preflight.py
```

Codex 和 Harness 的 S4 回合都从项目根目录启动，并将 `.venv/bin` 放在 `PATH` 首位；依赖由 `tools/s4_ppt_requirements.lock` 精确锁定。首轮命令必须通过 `tools/run_s4_local.sh` 启动，任务提示还要声明不使用网络、外部素材、图片/语音生成、旁白或本地 Web UI。`tools/s4_ppt_preflight.py` 会检查 PPTX 导出所需模块，并在直接环境存在 provider 凭据时失败。

短数据 PPT 的双宿主 Quick 入口：

```bash
tools/run_s4_local.sh quick-ppt prepare <project> \
  --analysis <analysis_frozen.json> \
  --markdown <analysis_frozen.md> \
  --evidence-root <evidence_dir>

# Agent 仅在项目 svg_output/ 中写完 SVG 后执行
tools/run_s4_local.sh quick-ppt finalize <project> \
  --output <project>/exports/<name>.pptx
```

入口只编排冻结身份校验、Quick 初始化、最终 SVG checker 和 Quick export，不实现第二套 PPT Renderer。`prepare` 是唯一运行 attribution guard 和本地预检的阶段；`finalize` 不重复这两个门禁。`analysis_frozen.json` 必须是 `s4_ppt_frozen_analysis.v1`，逐项列明证据相对路径、SHA-256、允许来源和指向证据的 `key_queries`；每份证据还必须携带 Data Foundation 写入的实际 `referenced_source_ids`，禁止来源会因此直接阻断。旧格式或缺少该来源凭据时，先重新执行受控查询再冻结，不能手改清单绕过。`prepare` 的 JSON 输出会返回实际项目路径，`finalize` 必须使用它。若实际生成了数据驱动图表，Agent 必须在最终 checker 前按 PPT Master 的 Quick `verify-charts` 规则完成一次图表验证；没有 blocking error 时不得重复运行 checker。Quick 项目不需要 `project_manager validate`、Confirm UI、Live Preview、Design Spec、Spec Lock、Speaker Notes 或 `finalize_svg.py`，并拒绝 SVG 图片、远程/内嵌资源与动画。

项目 Skill `diagnose-source-overlap` 已在 2026-08-16 由 Harness headless 真实调用，能正确区分全量刷新与多来源并存，并把去重处理路由到 Data Foundation 只读查询和保存查询。

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
| Workspace 能开但 CLI 不可用 | 检查工作目录、Python 环境、Shell 权限和 `python3 -m interfaces.data_foundation --help` |
| 模型无法回复 | 检查 Provider、API Key、额度和网络，不修改业务代码 |
| 查询被拒绝 | 先确认 SQL 是否只读、是否引用外部 reader 或系统目录 |
| Snapshot 冲突 | 使用新的 `run_id` 和显式输出目录，不覆盖已发布 Snapshot |
| 向导 `awaiting_confirmation` / 退出 2 | 宿主向客户展示问题，理解自由回答后把 option、原回答和确认人传给 `answer` |
| 月度文件更新 | 先完成当前对齐会话；替换 `Input/Data/<source_id>` 当前文件并用新 `snapshot_id` 执行 `sync-data`，向导成功切换后自动删除旧 Snapshot |
| `ACTIVE_SESSION_EXISTS` | 先完成当前 Snapshot 的对齐会话，再执行月度刷新 |
| `sync-data` 返回 cleanup warning | 新 Snapshot 已是当前状态；在确认不再占用旧 Run 后手工清理该目录 |
| 客户工作区误入 Git | 使用默认忽略的 `customers/`，交付产品时可整体复制该客户工作区 |
| `ADAPTER_LOAD_FAILED` | 仅针对程序化 `propose --adapter` 入口：检查测试或批处理模块的 `module:attribute` 与 `propose(model_input)`；不要因此开发宿主包装层 |
| Quick `unsupported frozen analysis schema` 或 `source provenance missing` | 用主线 Bridge 的受控查询重新写证据 JSON，再生成 `s4_ppt_frozen_analysis.v1`；旧冻结格式和手写来源标签不能复用 |
