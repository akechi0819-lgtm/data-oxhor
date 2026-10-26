# 服务器清理与自建 raw 路径暂停（2026-10-26）

用户决定保留 Mac 命令更新链路；今天停止导出和迁移试验。正式版本仍为 `daily-20261026_094052`，没有回退或重新发布。

## 实际删除

- `/var/lib/shadow-bi/warehouse-validation/raw-pipeline-20261025-task4/computed`：分配 2,677,559,296 字节。
- `/var/lib/shadow-bi/raw-compute/runs/raw-20261026-dot-001/workspace`：分配 2,587,738,112 字节。
- `/var/lib/shadow-bi/releases/daily-20261025_184644t`：分配 802,287,616 字节。
- `/var/lib/shadow-bi/incoming/daily-20261025_184644t`：分配 1,138,196,480 字节。
- `/srv/shadow-bi-notify/releases/5307a3812cf7201bd05c953ac552670c7575d74c`：分配 12,427,264 字节。

同时移除仅指向旧 daily25 成品的 previous 软链接。删除前检查进程引用、硬链接及 Nginx 引用，先保存小型质量/指标/manifest/hash/输入绑定和日志回执；没有删除原始输入、历史仓、有效 Snapshot 或通知状态。

文件系统总量 31,024,283,648 字节。清理前 used/free 为 22,662,381,568 / 8,345,124,864；清理后为 15,542,988,800 / 15,464,517,632。实际净释放 7,119,392,768 字节（6.63 GiB）。小型回执和后续验收占用会使即时读数略变。

## 运行路径

停用并禁用 `shadow-bi-raw-compute.path`、`shadow-bi-raw-publish.path`；receiver override 将 RAW_ENABLED 和 RAW_PUBLISH_ENABLED 设为 0。raw POST 返回 404。保留候选代码和原始包作为已验证施工成果，不再自动接收/计算/发布。

Mac 成品入口、发布脚本和权限未改，`shadow-bi-receiver-publish.path` 仍 enabled/waiting；通知 path 也保留。未修改 bi-2 或其他日更计划。现用 `/srv/shadow-bi/raw-code` 仍是 receiver 运行依赖，不能作为废弃兼容删除。Nginx 的 `/var/www/dashboard/current` 静态依赖保留。

没有改业务源码、公式、日期完整性、去重或鉴权门禁。兼容清理仅删除已不用的旧成品、incoming 和旧通知部署版本；仍在用的运行代码没有强删。

## 验证与回执

看板和 receiver health 均 200；原成品 POST 和通知状态 GET 在未带凭据时均 401，原能力保留。current/manifest、DeliveryState 和发布脚本 hash 未变；状态文件 JSON 可读，Nginx 配置通过。没有导出、发送通知、清空投递状态或新建调度。

服务器证据：`/var/lib/shadow-bi/warehouse-validation/cleanup-20261026-task4/` 的 `result.json`、`pause-result.json`、`final-check.json` 及 receipts-0..4。本次没有宣称 Dot 脱机发布成功。
