> 2026-10-25通知后续：已新增本地服务器release通知适配并离线验证，尚未部署/发送/改调度。详情见[通知适配](../docs/bi-notification-adapter-20261025.md)；用户已停止全部Grok例行，以下较早状态描述不得用于恢复任务。

# 正式 BI 部署与运行

2026-10-25正式代码基线为已核验的 Superset 原生 BI。模块路径保留 `dashboard_product.shadow_bi`，避免更改已有服务、源码引用和任务路径。原静态生产说明已归档到 `docs/history/dashboard/static-deployment-through-20261025.md`。

## 当前生产边界

- 用户入口为 `https://dashboard.apinova.cn/superset/dashboard/shadow-bi-native/?standalone=1`；首页和四个旧HTML入口已跳转新版。
- 服务器服务 `shadow-bi.service`、代码 `/srv/shadow-bi/code`、环境 `/srv/shadow-bi/venv`，私有数据 `/var/lib/shadow-bi`。`current/library/business.duckdb`为只读业务库；PostgreSQL保存应用元数据。
- 当前正式数据版本以现场 `current` 和 manifest 为准，不按目录时间或latest选择。本轮读回 `daily-20261025_184644t`，业务截至2026-10-24；`previous=daily-20261025_cloud03`。
- 18个原账号沿用既有htpasswd与只读权限；本次不改认证、凭据或数据共享范围。
- 当前采集端仍负责历史合并、Snapshot、业务计算和投影；服务器P4只装载39张封存业务表。完整服务器数仓迁移暂停。

## 正式运行入口

```bash
python3 -m dashboard_product.shadow_bi.p5.daily --workspace customers/shadow_bi_daily
```

该命令是真实采集/重算/发布。保持显式双仓身份和as_of-1截止口径，使用现有双源门禁；`--resume`仅用于同日来源未变的失败后续发布，`--publish-prepared`仅消费已有通过联合门禁的批次。不得重传旧包覆盖更新release。

服务器以 `shadow_bi/p4/rebuild.py` 构建候选库，`backup.sh`备份代码/配置/元数据，`activate.py`验版并切换；`p5/verify_daily.py`验证实际业务查询与批次。配置/元数据变化须配套恢复，不能只改软链。历史切版演练不授权正常发布倒退截止日。

HTTPS采集端使用独立凭据和现行接收接口；源码与systemd固定worker见`shadow_bi/p5/deploy/`。接收成功、排队、构建和发布是不同状态；超时或HTTP错误后先核对实际状态，不能盲目重传。receiver的状态文件权限缺陷仍未修复，详见正式基线未完成项。

## 通知与旧静态路径

`management.build`仍使用共同计算生成通知所需shared_result；`monitoring_product.shared_delivery`只消费该批通知，保持当前来源门禁和DeliveryState。不得因新版BI上线停止通知或更换接收者。

`run_management_daily.sh`默认在生成并校验通知批次指针后结束，防止旧静态激活流程覆盖Nginx。旧静态发布和激活保留dry-run；真实恢复需显式 `ALLOW_LEGACY_STATIC_PUBLISH=1` 并有对应恢复授权。此开关仅供已授权恢复，不是另一条日常发布通道。

外部Grok、Mac bi-2及Dot的调度要分别实读确认；本次未停外部任务、未启用Dot调度。精确切换项见[正式基线](../docs/bi-production-baseline-20261025.md)。
