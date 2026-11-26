# 市场工作区

市场工作绑定正式工作区 `customers/shadow_bi_daily/`。先运行 `./oxhor status`，以显式 release 或 Snapshot 执行受控查询。留学记分卡、口径和同比范围见[经营分析技能](../.agents/skills/biz-analysis/SKILL.md)。

## 写入位置与清理

新任务文件归 `../workspace/tasks/<YYYYMM-任务名>/{scratch,evidence,deliverables}`。查询用 `./oxhor query --task <YYYYMM-任务名>`，每次独立 run ID。早期运维程序及历史报告与证据沿用已有位置。交付和清理见[根入口](../AGENTS.md#任务文件与收尾)。

周报、项目套图与新媒体双周报使用[双周报技能](../.agents/skills/biweekly-report/SKILL.md)。看板、腾讯表和钉钉按当前任务授权执行。
