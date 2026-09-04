# Dashboard Product 开发前置准备

更新时间：2026-09-03

本文档是下一阶段看板开发的启动入口。看板是独立产品，负责固定指标的刷新、探针、渲染和推送；它只消费 Data Platform 的受控结果，不承担取数连接、业务口径解释或 Bridge 修改。

## 一、已确认边界

- 每次刷新必须显式传入一个客户 `workspace` 和一个新的 `run_id`。
- 当前 Snapshot、Bridge 和 Pack 均从该工作区读取，不使用 `latest`、修改时间或模糊文件名猜测状态。
- 看板不得 `duckdb.connect`，不得直接读取 landing 表；统一调用 `data-platform run-saved-query`。
- 看板可以拥有自己的 CLI、探针、渲染器、自动刷新脚本和推送适配器。
- 看板不能定义“粉丝量、标签率、转化率”等业务口径；口径由 Workspace Modeling 确认并固化为 saved query 或 Bridge 规则。
- 客户运行产物写入 `customers/<workspace>/Output/Dashboard/<run_id>/`，源码目录不保存运行结果。

## 二、当前已有能力

`dashboard_product/refresh.py` 目前只提供三项生命周期入口：

```bash
python3 -m dashboard_product.refresh refresh \
  --workspace customers/<workspace> --run-id run_<id>
python3 -m dashboard_product.refresh render \
  --artifact customers/<workspace>/Output/Dashboard/run_<id>/artifact.json
python3 -m dashboard_product.refresh push \
  --artifact customers/<workspace>/Output/Dashboard/run_<id>/artifact.json
```

当前行为：

- `refresh` 校验工作区并创建带 `run_id`、`snapshot_id`、`bridge_ref` 的不可变 artifact；
- `render` 只接受明确的 `dashboard_artifact.v1`；
- `push` 返回 `not_started`，尚未连接服务器或外部渠道。

## 三、开发前必须先定的合同

### 1. Saved Query 合同

每个看板指标先在 Workspace Modeling/Data Platform 中确认并版本化，至少包括：

```text
query_id / query_version
workspace_id
pack_ref / bridge_ref
snapshot_id（执行时绑定，不写死在代码）
parameters（时间窗、组织范围等）
columns / types
metric_definition
source_refs
quality_requirements
```

看板只保存 `query_id`、参数和结果引用，不保存业务 SQL 的第二份副本。执行结果必须带同一 `run_id`、`snapshot_id` 和来源凭据。

### 2. Dashboard Artifact 合同

继续使用 `dashboard_artifact.v1`，后续扩展时不得破坏以下身份字段：

```text
artifact_id
run_id
snapshot_id
workspace_id
bridge_ref
query_results[]
probe_results[]
created_at
status
errors[]
```

artifact 必须不可变。刷新失败写入该 run 的错误信息并返回非零退出码；不得覆盖已有 run，也不得产生 `latest.json` 指针。

### 3. 探针合同

每个探针是确定性检查，不负责解释原因。建议首批覆盖：

- Snapshot/Bridge/Pack 兼容性；
- 查询结果是否为空、列类型是否符合合同；
- 日期窗口、行数、金额范围和重复键异常；
- 来源 manifest、查询身份和结果哈希是否一致；
- 指标缺失时是否阻断渲染或标记为 warning。

探针输出至少包含：`probe_id`、`status`、`severity`、`observed`、`expected`、`evidence_refs`、`errors`。

## 四、建议实施顺序

1. 将 `refresh.py` 改为调用 `interfaces.data_platform` 的 `run-saved-query`，补齐 workspace/Bridge/Pack 校验。
2. 定义并测试 `dashboard_artifact.v1` 的完整 JSON schema 和退出码。
3. 建立 `queries/` 或 manifest 层，只登记已确认的 `query_id`，不复制 SQL 和业务映射。
4. 实现探针框架和首批数据质量探针。
5. 实现纯读渲染器：输入只能是明确 artifact，输出 HTML/JSON 等不可变文件。
6. 增加显式 CLI：

   ```text
   dashboard-product refresh --workspace <path> --run-id <id>
   dashboard-product render --artifact <path>
   dashboard-product push --artifact <path>
   ```

7. 最后再做定时刷新、服务器认证、企业微信推送和外部发布适配。

## 五、测试与验收门禁

新增 `dashboard_product/tests/`，至少覆盖：

- 缺少 workspace、Snapshot、Bridge、Pack 时失败；
- saved query 只能执行当前显式 Snapshot；
- 看板代码不直接连接 DuckDB；
- 不接受 `latest`、硬编码 Snapshot、硬编码 landing 表名；
- artifact 身份字段完整且不可覆盖；
- 查询结果和探针结果绑定同一 `run_id`/`snapshot_id`；
- 空结果、类型漂移、质量失败的阻断和 warning 语义；
- render 只接受合法 artifact，不能从工作区自动寻找“最新”文件；
- push 在未实现时返回稳定的 `not_started` 和退出码 `2`。

跨模块最小验收流程：

```text
data_acquisition 原始产物
  -> data_platform 发布 Snapshot
  -> workspace_modeling 确认 Bridge / saved query
  -> dashboard_product refresh
  -> probe
  -> render
```

## 六、明确不做

- 不在看板项目内建设取数 Agent、BI 登录或企业微信连接器；这些属于 `data_acquisition`。
- 不在看板项目内维护客户字段解释、业务枚举或指标口径；这些属于 Workspace Modeling/Bridge/Pack。
- 不恢复旧 Dashboard 原型的固定 SQL、配置 CSV、`/api/latest` 或源码目录运行产物。
- 不建设项目级总路由器；由宿主或明确 CLI 选择分析产品、看板产品和工作区建模能力。

## 七、启动前检查清单

- [ ] 明确首批看板指标及其业务负责人。
- [ ] 每个指标已有 confirmed saved query 和版本号。
- [ ] 确认参数、时间窗口、空值和异常值语义。
- [ ] 确认 artifact JSON schema、退出码和输出目录。
- [ ] 确认首批探针及阻断级别。
- [ ] 准备一个可用的客户工作区和显式 Snapshot 做端到端测试。
- [ ] 为每个公共接口补合同测试，再开始页面和推送开发。
