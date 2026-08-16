# 本地运维手册

## 1. 版本和路径

| 项目 | 当前值 |
|---|---|
| 默认宿主 | 无；由实际部署选择 |
| Python | `>=3.12` |
| DuckDB | `1.5.5` |
| Data Foundation | ingest v2 / warehouse snapshot v2，无计划原始 landing |
| Git | 已初始化，当前 worktree 尚无可引用基线 commit |

项目目录是可移植核心，不安装进任何宿主目录。宿主的 Profile、Provider、密钥、Session 和缓存留在各自机器级目录，不纳入项目版本控制。

## 2. 核心冒烟检查

```bash
python3 -m interfaces.data_foundation --help
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

基线是 22 项现行测试通过。测试失败时先区分：Python/DuckDB 版本、外部 Golden Case 是否可读、源 SHA-256 是否变化、还是代码回归。不要通过修改 Golden 值掩盖源文件变化。

直接入仓不要求 `inspect` 或 cleaning plan。先准备只含 `sources → filename + sha256` 的 manifest，然后调用 `ingest`；入仓后通过 `ingest.sheets` 查 `target_table`，不要按中文 Sheet 名猜哈希表名。

## 3. 宿主接入冒烟

任一新宿主至少实际完成：

```bash
python3 -m interfaces.data_foundation --help
# 使用独立 run_id、snapshot_id、manifest、output_root 和 sql-file：
# ingest → describe → query
```

验收必须检查 stdout JSON、退出码和 DuckDB/manifest 实际内容，不能只看宿主最终回答。宿主专属 Session、交互表格和文件展示按部署需要另行验证，不阻塞核心接入。

### 已安装的 DeepSeek Harness（可选宿主）

```bash
/Users/akechi/.local/bin/dsh --version
/Users/akechi/.local/bin/dsh web --host 127.0.0.1 --port 3080
```

当前已安装 `@deepseek-ai/dsh@0.1.0-rc.6`，共享目录是 `/Users/akechi/.dsh`。它是已验证的可选宿主，不是项目默认运行时；其机器配置和凭据不得进入仓库。

## 4. 模型和密钥

模型 Provider 与 API Key 只在所选宿主的机器级设置中配置，不写入仓库、客户配置样例或日志。DeepSeek Harness 的真实 headless 模型已完成 Data Foundation 调用；Codex、Hermes 等使用各自配置。Session、交互表格和 Deliverables 等宿主能力不作为 Data Foundation 施工项。

## 5. 正式结论门禁（尚未实现）

当前 Data Foundation 能保证数据和查询可追溯，但还不能确定性验证“每个结论都绑定证据”。在 Analysis Contract 完成前，当前模型回答只能视为开发验证结果，不能声称已通过正式 Evidence Gate。

Stage 4 实现后的冒烟至少覆盖：

- 有 Snapshot、查询结果和口径引用的结论通过；
- 无证据引用的结论被阻断；
- 未确认 Bridge 映射被阻断；
- 证据冲突时只能输出带限制的 `conditional`；
- Renderer 拒绝 `blocked` claim；
- 不记录或要求模型私有逐 Token 思考链。

## 6. 升级策略

任一宿主升级前必须：

1. 记录目标版本和来源；
2. 阅读上游变更；
3. 在隔离配置中验证受控 Shell、CLI 和所需交付能力；
4. 通过当前端到端 Eval 后再用于客户部署。

不得把业务逻辑补丁直接打进任何宿主安装包或上游 checkout。

## 7. 常见问题

| 现象 | 检查 |
|---|---|
| 宿主能对话但 CLI 不可用 | 检查工作目录、Python 环境、Shell 权限和 `python3 -m interfaces.data_foundation --help` |
| 模型无法回复 | 检查所选宿主的 Provider、API Key、额度和网络，不修改业务代码 |
| 交互表格不可用 | 使用静态 HTML/XLSX/图片输出；该差异不影响核心计算 |
| 查询被拒绝 | 先确认 SQL 是否只读、是否引用外部 reader 或系统目录 |
| Snapshot 冲突 | 使用新的 `run_id` 和显式输出目录，不覆盖已发布 Snapshot |
| 不知道 landing 表名 | 查询 `ingest.sheets`，不要猜中文 Sheet 的哈希后缀 |
| 表头不在首行或是矩阵 | 不阻塞 ingest；先查询 landing 前若干源行，再在 SELECT/CTE 或 Bridge 中解释 |
| 结论没有可定位证据 | 在 Stage 4 完成前不得作为正式结论；完成后由 Evidence Gate 返回 `blocked` |
