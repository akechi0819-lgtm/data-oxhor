# 本地运维手册

## 1. 版本和路径

| 项目 | 当前值 |
|---|---|
| DeepSeek Harness | `@deepseek-ai/dsh@0.1.0-rc.6` |
| 全局命令 | `/Users/akechi/.local/bin/dsh` |
| Harness 共享目录 | `/Users/akechi/.dsh` |
| Python | `>=3.12` |
| DuckDB | `1.5.5` |
| Git | 当前任务分支含 Bridge 对齐向导最小切片；合并状态以 `git status` 为准 |

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

基线是 56 项现行测试通过，Pack 与 Bridge 校验状态均为 `passed`。向导测试使用 fake adapter，不代表真实宿主模型已接入。`finalize` 必须在 `propose` 产生至少一个候选后才能执行；空候选返回 `CANDIDATES_MISSING`。测试失败时先区分：Python/DuckDB 版本、外部 Golden Case 是否可读、源 SHA-256 是否变化、Pack/Bridge 交叉引用错误，还是代码回归。不要通过修改 Golden 值掩盖源文件变化。

## 4. 模型和密钥

模型 Provider 与 API Key 已在 Harness 的机器级设置中配置，不写入仓库、客户配置样例或日志。2026-08-14 已确认：Harness 真实模型回合可用，模型在项目 Workspace 通过 Shell 执行 `python3 -m interfaces.data_foundation --help`，退出码为 0，并发现全部 7 个子命令。

真实三表已经通过 `inspect → ingest → describe → quality → query` 和 Bridge 兼容性验证。以下项目尚无通过证据：

- Session 重启后继续对话；
- Deliverables 生成和展示。

项目 Skill `diagnose-source-overlap` 已在 2026-08-16 由 Harness headless 真实调用，能正确区分全量刷新与多来源并存，并把去重处理路由到 Data Foundation 只读查询和保存查询。

## 5. 升级策略

DeepSeek Harness 处于 Developer Preview。升级前必须：

1. 记录目标 npm 版本和 integrity；
2. 阅读上游变更；
3. 在独立 Profile 中验证 Web、Workspace、Skill、受控 Shell、CLI、Session 和 Deliverables；
4. 通过当前端到端 Eval 后再替换默认版本。

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
| 月度文件更新 | 替换 `Input/Data/<source_id>` 当前文件并用新 `snapshot_id` 执行 `sync-data`；不要删除旧 Snapshot |
| 客户工作区误入 Git | 使用默认忽略的 `customers/`，交付产品时可整体复制该客户工作区 |
| `ADAPTER_LOAD_FAILED` | 检查宿主 adapter 的 `module:attribute` 引用及其 `propose(model_input)` 方法 |
