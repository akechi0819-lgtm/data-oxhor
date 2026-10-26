> 状态依据截至 2026-10-26 的日期回执：Superset 原生 BI 已在用，Mac `p5.daily` 仍是正式更新入口；current 为 `daily-20261026_094052`、数据截止 10-25。服务器通知适配已部署，10-26 人工触发的 8 条消息为 sent；一个 HTTP job 仍为 `unknown`，只读对账回执关联了先前发送。Dot 每日 10:00 日程记录是通知触发，不是 BI 采集调度。固定 raw 接收与发布服务已部署，但真实 Dot 批次未通过业务截止门禁，未发布、未切换生产者。Grok 例行按用户要求停止；本次文档更新未实读调度平台状态。

# 正式 BI 部署与运行

2026-10-25正式代码基线为已核验的 Superset 原生 BI。模块路径保留 `dashboard_product.shadow_bi`，避免更改已有服务、源码引用和任务路径。原静态生产说明已归档到 `docs/history/dashboard/static-deployment-through-20261025.md`。

## 当前生产边界

- 用户入口为 `https://dashboard.apinova.cn/superset/dashboard/shadow-bi-native/?standalone=1`；首页和四个旧HTML入口已跳转新版。
- 服务器服务 `shadow-bi.service`、代码 `/srv/shadow-bi/code`、环境 `/srv/shadow-bi/venv`，私有数据 `/var/lib/shadow-bi`。`current/library/business.duckdb`为只读业务库；PostgreSQL保存应用元数据。
- 当前正式数据版本应以现场 `current` 和 manifest 为准，不按目录时间或 latest 选择。2026-10-26 回执读回 `daily-20261026_094052`，业务截至 2026-10-25；这是该日期的核验结果，不代表本次文档编辑期间再次读取了服务器。
- 18个原账号沿用既有htpasswd与只读权限；本次不改认证、凭据或数据共享范围。
- 当前采集端仍负责历史合并、Snapshot、业务计算和投影；服务器P4只装载39张封存业务表。完整服务器数仓迁移暂停。

## 正式运行入口

```bash
python3 -m dashboard_product.shadow_bi.p5.daily --workspace customers/shadow_bi_daily
```

该命令会采集、重算并发布。按显式双仓身份和 `as_of-1` 截止口径运行，并通过现有双源门禁。10-26 的 Mac 手动更新由此入口完成；在 Dot 新输入链路通过正式切换验收前，它仍是正式更新入口。不得重传旧包覆盖更新 release。

服务器以 `shadow_bi/p4/rebuild.py` 构建候选库，`backup.sh`备份代码/配置/元数据，`activate.py`验版并切换；`p5/verify_daily.py`验证实际业务查询与批次。配置/元数据变化须配套恢复，不能只改软链。历史切版演练不授权正常发布倒退截止日。

### Dot 固定 raw 接收与发布

2026-10-26 已部署固定三 Excel 接收、受限计算和 root-owned 发布程序。外部接收为 `POST /shadow-bi/v1/raw-batches`，状态查询为 `GET /shadow-bi/v1/raw-batches/<batch>`；只有批次明确为 `prepared`、并由操作者确认来源任务、窗口、Snapshot 身份和质量后，才允许对同批调用 `/shadow-bi/v1/raw-batches/<batch>/publish-prepared`。该接口请求体固定为空对象 `{}`，只触发固定发布程序，不接受命令或路径参数。收到包、进入队列、计算完成和正式发布是不同状态；超时或 HTTP 错误后先按批次 ID 查询状态，不盲目重传。

本次真实 Dot 批次 `raw-20261026-dot-001` 以 `failed/published=false` 结束，业务截止门禁不匹配；该次raw操作未切换current。它不是已发布数据，也不是服务器整仓迁移完成。通知 receiver 的 `last_published`、`last_published_hash`、`last_failed` 状态文件权限问题已在[通知适配后续部署回执](../docs/bi-notification-adapter-20261025.md)修为 `root:shadowbi 0640`，实际 shadowbi 身份读取通过；不是仍待修复项。raw 服务自身的权限与部署证据见[raw 发布回执](../docs/server-raw-fixed-publisher-20261026.md)和[raw 接收回执](../docs/server-raw-receiver-deployment-20261026.md)。

### 本地完整性整合（尚未部署）

当前main已补齐[来源完整性验证](../docs/server-source-completion-candidate.md)：raw计算、候选复用、维护复验及publisher均强制使用同一受保护完成证明。缺少证明时不构建，审批/封存决定/metadata不一致时不发布；P4重建后且切current前再次复核。该新门禁只在本地整合，不能从既有服务部署推断它已经在服务器生效。Mac日更尚未接入审批，生产切换和任何日程变更另行验收。

## 通知与静态兼容路径

服务器通知适配已部署：`monitoring_product.release_notifications` 从固定正式 release 构建同批通知包，`shared_delivery` 负责状态去重与传输；通知不独立查询数仓。2026-10-26 的人工触发有 8 条 sent 状态。HTTP job `9cbbb2…` 保留原 `unknown/retryable=false`；独立只读对账回执将其关联到此前已发送的 8 条消息，`no_send_performed=true`，不表示该 job 自身发送成功。不得重发这些消息或清空 DeliveryState。详见[通知作业修复回执](../docs/notification-job-receipt-repair-20261026.md)。

历史静态入口 `run_management_daily.sh` 默认在生成并校验通知批次指针后结束，防止旧静态激活流程覆盖 Nginx。旧静态发布和激活保留 dry-run；真实恢复需显式 `ALLOW_LEGACY_STATIC_PUBLISH=1` 并有对应恢复授权。此开关仅供已授权恢复，不是另一条日常发布通道。

记录中自 2026-10-26 起的 Dot 上海 10:00 日程用于通知触发；不得据此推断 BI 采集／刷新已迁至 Dot。10-26 通知回执另记 Mac `bi-2` 为 ACTIVE/09:40；这只是日期记录，本次未实时读取调度平台。Grok 例行已按用户要求停止。正式切换到 Dot 采集／发布链路仍待真实批次通过业务门禁、发布验收及唯一生产者切换回执。旧静态页面链路保留为历史兼容内容，不是日常入口；当前代码合同见[raw链路合同](../docs/server-raw-pipeline-contract.md)；[10月25日正式基线](../docs/bi-production-baseline-20261025.md)仅保留当时证据。
