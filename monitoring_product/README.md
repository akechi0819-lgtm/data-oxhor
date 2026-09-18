# 日常监控

2026-09-16 云端迁移已验收，角色、排期和回执见 [云端部署验收](../docs/monitoring-cloud-deployment.md)。下文部署步骤中的待切换说明是迁移过程记录，实际状态以验收记录为准。

首个场景为人员绩效进度监控。模块从当前 Snapshot 受控取数，生成工单/现金/人头进度、落后名单、PNG、Excel 和钉钉正文。无须先刷新看板。

## 运行合同

```bash
python3 -m monitoring_product.notify send \
  --workspace customers/bi_operations \
  --snapshot-id <workspace.json中的current_snapshot_id> \
  --run-id <本次唯一运行编号> \
  --as-of-date <计算时间进度的日期> \
  --data-through-date <已核验的数据截止日期> \
  --team offline_market --dry-run
```

日期格式为 YYYY-MM-DD，数据截止日期由操作者按已完成的数据同步核验后明确传入，不从文件名或修改时间推测。日期标签不改变既有绩效月 SQL 筛选；SQL 仍查询上月 26 日至本月 25 日。`--team` 可重复；省略则选择五通道。`offline_market` 展开为线下青少、高中、大学；其余为 `online_private`、`online_platform`。

正式发送去掉 `--dry-run`，增加 `--env-file <C层凭据文件>`。现有凭据可保持原位置并显式传入，模块不自动寻找或复制密钥。缺 webhook 的通道标为 skipped，整体 partial、非零退出。

默认产物为 `<workspace>/Output/Monitoring/<run_id>/`：各通道 `people.html`、`people.png`、`details.xlsx`、`message.md`，以及本地 `evidence.json` 和 `_query/` 受控查询凭据。结果包含运行编号、Snapshot 和日期；上传只选择 PNG/XLSX，证据 JSON 不进公网。

每次使用唯一 run_id。Snapshot 必须与工作区 current 指针一致，数仓路径必须在该工作区内；Data Platform 再验证仓库身份和只读 SQL。全部选中通道完成取数和计算后才渲染、上传、发送。查询失败、结果丢失或计算异常整批阻断，CLI 输出 failed 并非零退出，预览同样阻断。成功查得零行属于有效结果。

## 业务口径归属

- `sql/notify_work_orders.sql`、`notify_cash.sql`、`notify_work_orders_by_ids.sql`：原通知查询原样迁入，保留 TMK 校代资源归属、现金团队兜底与跨月工单回查。
- `digest.py`：人员归属、工单落后判断、现金和人头计算。原有业务公式保持；通道合计从同一明细按行汇总，不重复累计多人共同归属。
- `workspace_modeling/operations/personnel.py`：看板和监控共用的绩效月、人员匹配规则。
- `workspace_modeling/operations/people.json`：现有 BI 运营花名册和人员目标，保持单一来源。SQL 中的线下人员名单仍需随其一起更新；本次未改变该既有耦合。该配置不是跨公司的通用行业 Pack。
- `notify_render.py`：图片、表格和正文；`notify.py`：受控查询、统一最终结果和发送编排。

## 部署与切换

1. A 层同时同步 `monitoring_product/`、`workspace_modeling/operations/`、修改后的 `dashboard_product/refresh.py` 和 `pyproject.toml`。删除旧通知 Python、通知 SQL、两个通知部署脚本及旧花名册路径；不删除运行证据或客户数据。
2. 云端宿主的通知任务改用上面的新命令和显式工作区/日期/Snapshot。先 dry-run 核对，再按原发送授权上线。看板日更命令不变，必须同步共享业务目录。
3. C 层密钥位置不变，任务通过 `--env-file` 引用；本次代码迁移不等于已部署云端或改好外部定时任务。
4. `deploy/publish_notify_assets.sh` 通过显式 ENV_FILE 发布 PNG/XLSX。沿用现有 `/notify/<token>/<channel>/` 静态地址；Nginx 属于共用托管设施，配置仍在 `dashboard_product/deploy/nginx-dashboard-http.conf`。必要时运行本模块 `deploy/install_notify_nginx.sh`，同样显式传 ENV_FILE。

旧 `dashboard_product.notify` 命令及 `--artifact` 输入已移除，不提供兼容转发。定时由外部宿主负责；尚未建设变化检测、去重冷却或自动重试。

## 验证

```bash
python3 -m unittest discover -s monitoring_product/tests -v
python3 -m unittest discover -s dashboard_product/tests -v
python3 -m monitoring_product.notify send --help
```
