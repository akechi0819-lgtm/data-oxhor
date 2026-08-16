# 本地运维手册

## 1. 版本和路径

| 项目 | 当前值 |
|---|---|
| DeepSeek Harness | `@deepseek-ai/dsh@0.1.0-rc.6` |
| 全局命令 | `/Users/akechi/.local/bin/dsh` |
| Harness 共享目录 | `/Users/akechi/.dsh` |
| Python | `>=3.12` |
| DuckDB | `1.5.5` |
| Git | 已有基线提交 `a5df0b6`；工作树有未提交改动 |

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
python3 -m interfaces.company_bridge --help
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

当前基线是 46 项现行测试通过，Pack 校验状态为 `passed`。测试失败时先区分：Python/DuckDB 版本、外部 Golden Case 是否可读、源 SHA-256 是否变化、Pack/Bridge 交叉引用错误，还是代码回归。不要通过修改 Golden 值掩盖源文件变化。

## 4. Company Bridge 验证

合同和入口说明见 [Company Bridge v1 合同](./company-bridge-contract.md)。历史扫描必须把输出写到扫描根目录之外；它只能产出候选集，不能直接作为正式 Bridge：

```bash
python3 -m interfaces.company_bridge scan-history \
  --root /Users/akechi/Desktop/super_agent \
  --output /path/to/candidates/super_agent_history_scan.json \
  --company-id company_super_agent \
  --candidate-set-id scan_super_agent_20260814

python3 -m interfaces.company_bridge validate-candidates \
  --input /path/to/candidates/super_agent_history_scan.json \
  --pack business_pack/packs/education_training_operations_cn/pack.json
```

2026-08-14 的只读扫描产物为 `artifacts/company_bridge/candidates/super_agent_history_scan_20260814_v6.json`，校验结果为 136 个候选、851 条拒收记录。2026-08-15 的 reviewed 输入 v1 保留在 `artifacts/company_bridge/reviewed/super_agent_confirmed_review_20260815_v1.json`；按真实 Data Foundation 字段对齐的 reviewed v2 为 `artifacts/company_bridge/reviewed/super_agent_confirmed_review_20260815_v2.json`，包含 135 个 confirmed 候选。正式 Bridge 1.1.0 为 `artifacts/company_bridge/bridges/company_bridge.v1_1_0.json`，已对 `snapshot_super_agent_inputs_20260815_v2` 兼容性通过；不要把历史扫描文件直接传给正式构建入口。

## 5. 模型和密钥

模型 Provider 与 API Key 已在 Harness 的机器级设置中配置，不写入仓库、客户配置样例或日志。2026-08-14 已确认：Harness 真实模型回合可用，模型在项目 Workspace 通过 Shell 执行 `python3 -m interfaces.data_foundation --help`，退出码为 0，并发现全部 7 个子命令。

以下项目尚无通过证据：

- 完整 Data Foundation 数据链路；
- Session 重启后继续对话；
- 项目 Skill 实际调用；
- Deliverables 生成和展示。

## 6. 升级策略

DeepSeek Harness 处于 Developer Preview。升级前必须：

1. 记录目标 npm 版本和 integrity；
2. 阅读上游变更；
3. 在独立 Profile 中验证 Web、Workspace、Skill、受控 Shell、CLI、Session 和 Deliverables；
4. 通过当前端到端 Eval 后再替换默认版本。

不得把业务逻辑补丁直接打进全局 Harness 包或上游 checkout。

## 7. 常见问题

| 现象 | 检查 |
|---|---|
| `dsh` 找不到 | 使用绝对路径并检查 `/Users/akechi/.local/bin` 是否在 `PATH` |
| Web 无法访问 | 确认进程仍在、端口 `3080` 未占用、绑定地址是 `127.0.0.1` |
| Workspace 能开但 CLI 不可用 | 检查工作目录、Python 环境、Shell 权限和 `python3 -m interfaces.data_foundation --help` |
| 模型无法回复 | 检查 Provider、API Key、额度和网络，不修改业务代码 |
| 查询被拒绝 | 先确认 SQL 是否只读、是否引用外部 reader 或系统目录 |
| Snapshot 冲突 | 使用新的 `run_id` 和显式输出目录，不覆盖已发布 Snapshot |
