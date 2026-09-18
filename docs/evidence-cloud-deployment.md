# 查询证据链与来源修复云端同步验收

验收日期：2026-09-18。状态：已完成；本机依据回传文件逐项核验，不仅依赖 Bot 的完成消息。

## 发布身份与范围

- 代码提交：`d09a22866f5c5aee097df13cf7e4348afcd69ed6`，包含前置 `730a4ba` 的查询证据链所需文件。
- A 层包：`.sync-outbox/20260918-A-evidence-d09a228.tgz`，134000 bytes，39 个代码/合同文件。
- 包 SHA-256：`01190b050edeff3b88cee0c3929db6756d1501ce73d7602da399289e7245941e`。
- 通过现有 Grok Bot 通道同步，赵高协调，牛马力工实施，Codex 主任务独立核对回执。
- 范围：查询回执 v2、来源解析修复、自由分析组包、Casebook/Bridge 配套接口、看板与监控的查询读取及相关合同。没有恢复已取消的最终产物统一改造。

## 云端落点与预检

Python 3.13.5，DuckDB 1.5.5。共享代码唯一落在 `/home/box/oxhor/warehouse`；看板刷新模块在 `/home/box/oxhor/dashboard`，监控入口在 `/home/box/oxhor/monitor`。现有接口、数据平台和工作区建模软链保持。

预检未发现相关仓刷新、看板发布或监控发送进程。云端此前仍使用旧查询回执，缺少 evidence/delivery 模块，因此本次成套安装了前置证据链与消费者，未只覆盖查询服务。

## 差异处理

初次核验有 7 份云端文档/Skill 不匹配已知基线，先跳过覆盖并回传原文件。主任务核对完整 diff，确认属于旧 PPT Quick、旧 Casebook 和旧模块说明，没有需保留的云端专属配置。按 `DOC_RESOLUTION.json` 指定的预期云端哈希再次核验，备份后精确替换为原包文件。

最终 39/39 文件 SHA-256 与包一致：1 个无需修改，38 个安装/更新，未知差异及剩余跳过均为 0。既有旧测试样例已不存在，没有删除客户证据。

## 验收结果

| 项目 | 结果 |
|---|---|
| warehouse 查询/证据/Casebook/Bridge 合成回归 | 56 项通过 |
| monitoring_product 回归 | 19 项通过 |
| dashboard_product 回归 | 30 项通过 |
| 合计 | 105 项通过，命令退出码均为 0 |
| CLI help 与实际模块导入路径 | 通过，共享模块解析到 warehouse |
| 主任务逐文件比对 | 39/39 与 Git 提交及同步包一致 |

分析角色读取的入口已确认是 warehouse 下 `agents/ad_hoc_analysis/AGENT.md` 与 `.agents/skills/business-analysis-routing/SKILL.md`。协调 Bot 已通知分析角色使用新合同，包含至多一次中性保存提醒及用户验收同意后原样保存 answer.md 的流程；未调整职责或排期。

未修改业务 SQL、花名册、云端 pyproject 热修、客户 Snapshot 指针或例行任务；未真实运行仓刷新、看板发布或钉钉发送，未搬运 B/C 层。

## 证据位置

本机 `.writeback-inbox/20260918-evidence-sync/` 保存 PREFLIGHT、FINAL_DEPLOYMENT、FINAL_FILE_HASHES、TEST_RESULTS、IMPORT_PATHS、冲突原文件、处理清单和 `LOCAL_VERIFIED_SUMMARY.json`。早期 DEPLOYMENT/FILE_HASHES 中的 7 项跳过已由 FINAL 回执取代，不能据早期回执误判当前状态。

本记录只证明此次代码与合同同步、合成测试及入口校验；不代表重新核算线上业务数据，也不代替后续例行任务的实际运行回执。
