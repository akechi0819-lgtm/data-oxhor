> **最新运行记录（2026-10-26）**：[清理与暂停回执](server-cleanup-20261026.md)记载自建raw接收、计算和发布路径已暂停，保留Mac更新与原生成品发布/通知入口。服务器数仓与聚合能力、代码和必要历史基线仍保留；“能力已部署”不等于raw目前启用。本轮仅收录另一工作树的日期回执，未实读或更改服务器/日程。

# 来源完整性验证：本地 main 合同

本地代码已整合 `codex/raw-coverage-evidence` 的完整性验证和后来新增的固定raw发布程序。本说明描述整合后的源码合同，不是服务器部署回执；10月26日本轮只整理本地代码、文档和工作树，不安装服务器代码、不改变任何日程或生产状态。

## 记录日期与完整截止日

`management/sql/coverage.sql` 取得工单分配时间、现金业务日期的最大记录日。默认共同计算取两者与昨日的最小值，表示已有记录的计算截止，不证明上游业务日完整。raw manifest 的昨日声明、导出完成时间、ETL刷新时间及双仓导入回执也不构成完整性证明。

用户已确认：昨日完整性未经验证就不更新、不发通知。完整但零业务日可以计算为零，不要求源里必须有昨日记录，也不补造记录。本地raw链路使用受保护的上游完成水位；通过后 `metadata.data_through` 为经验证昨日，`metadata.observed_dates` 单独保存两张表的最大记录日，`metadata.source_completion` 记录证明身份。个人26日至次月25日、线上平台自然月、事实与金额及人员独立资格保持现有规则。

服务器已持有历史数仓基线，raw服务已实际完成双Snapshot、quality和聚合39表构建；完整性审批是后来仅在本地整合的新门禁，与服务器迁移是否已落地分别表述。现存Mac手动日更入口未接入这套审批，本地合并不能证明生产所有入口已实施新门禁，发布与调度按各自回执核对。

## 完成证据及信任边界

固定目录为 `/var/lib/shadow-bi/raw-control/source-completion/<batch>/`。每批包含 `approval.json`、`orders.evidence`、`cash.evidence`；目录和文件均须root所有且非组/全局可写。读取器使用目录FD、O_NOFOLLOW、O_NONBLOCK及fstat，拒绝链接、FIFO、不安全权限和超限文件。审批最多16KiB，每份来源证据最多2MiB，不执行或渲染证据。

审批为 `shadow_source_completion.v1`，严格校验字段、当日带时区且不晚于当前的reviewed_at，以及orders/cash两条 `upstream_completion_watermark`。binding绑定批次、公司、as_of、昨日、BI窗口、腾讯替换月、实际TAR及三Excel hash。来源ID分别为 `br_work_orders` 和 `br_cash`，完成日须为昨日，每份证据字节必须符合审批hash。腾讯文件绑定防混批，不冒称已证明腾讯来源每日完整。

审批安装/撤销属于受信任root运维，必须与发布共用既有 `/run/shadow-bi-receiver.lock` 串行操作；当前没有证据写入API或安装器，本轮也不新增。发布末次复核检查的是读取时的证明快照，不声称能够阻止绕过运维锁的root在检查后任意改写文件。

root审批不是来源数字签名。信任点是受信任审阅者核对真实上游完整业务日/分区水位及其与本次导出的关系；仅存截图、改kind标签或提供刷新时间都不能代替核验。当前没有审批安装脚本、HTTP签发路由或自动证明生成器，业务用户不需手写JSON。若实际来源无法提供可信完成证据，raw新批次继续停在未验证状态。

## 计算、复用与发布的同一证明

1. raw计算在复制历史/导入双仓前预检。缺失或无效时写 `coverage_unverified`、`published:false`，私有原因仅 `evidence_missing` 或 `evidence_invalid`。这表示未经验证，不能推断源站漏数。公开接口不暴露审批、路径或日志。
2. 通过后封存 `coverage-decision.json`。子进程在计算前和39表封口前重读审批；`require_unchanged` 要求当前审批与封存决定相同，库metadata须绑定同一证明。
3. 已prepared批次复用、维护 `recheck` 均强制重读同一证明；缺少decision或证明的旧候选不能通过。这些检查不保留无证明候选的兼容分支。历史failed及coverage_unverified不被HTTP重放复活，不新增自动恢复路由。
4. 固定publisher无条件复核来源证明、decision与library metadata，再核对三源、双Snapshot、quality、39表及正式current。P4重建和下一批基线预检完成后、切换current之前再次复核；期间撤销或更换审批就拒绝切换，清理失败候选并保留原current。
5. 发布仍沿原P4实际HTTP/18指标验收和失败恢复；成功后才晋升基线、清理确认无引用的旧成品。审批不授予通知或任意命令权限。

## 本地验证与生产停点

测试使用明确标识的合成审批/事实，不冒充真实来源完成证据。覆盖hash/window/day/month/company/batch绑定、权限/链接/FIFO/大小、日期时区、错误证明类型、未验证不构建、failed幂等、零业务日与绩效月边界、真实合成39表重建，以及发布前审批缺失/变化/构建期间撤销时不激活。

本次实际测试结果见 [本地整合记录](local-project-alignment-20261026.md)。10月26日既有raw接收和固定发布部署事实分别见 [接收计算回执](server-raw-receiver-deployment-20261026.md)、[固定发布回执](server-raw-fixed-publisher-20261026.md)；这些早于本地完整性整合，不证明新门禁已经部署。真实完成证据、服务器安装验收、Dot全程脱机新包正式发布和唯一生产者切换仍待独立处理。
