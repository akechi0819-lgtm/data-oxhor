# 看板发布 Agent

## 正式入口

当前正式产品是 Superset 原生 BI，稳定代码路径保留 `dashboard_product.shadow_bi`。运行与恢复以 [部署说明](../../dashboard_product/DEPLOYMENT.md) 为准；不要按旧P1实验或旧静态部署说明重新安装生产环境。

日更使用 `python3 -m dashboard_product.shadow_bi.p5.daily --workspace customers/shadow_bi_daily`；这是写入/发布命令，须有日更或发布授权，不能作为只读检查。复用BI/Tencent采集、明确双仓Snapshot、现有共同计算、投影、封存和P4验证激活，业务截止严格as_of-1。

正式状态必须核对服务器current、manifest、真实业务查询及页面；health为正常不能替代全链路成功。任一源失败或身份不匹配保留上一成功版，不伪造回执、不混仓、不倒退截止日。

## 通知与兼容代码

`management/calculation.py`为共同业务计算，`management.build`继续为同批通知及恢复生成shared_result。通知消费方为`monitoring_product.shared_delivery`及原有投递入口，不独立改SQL、业务归属、接收者或DeliveryState。

旧`run_management_daily.sh`默认只准备通知批次，不再激活静态网页。静态发布/激活保留dry-run与显式恢复开关`ALLOW_LEGACY_STATIC_PUBLISH=1`，不得当日常新版入口。完整旧Agent说明已归档于`docs/history/dashboard/static-publisher-agent-through-20261025.md`。

外部任务的启停与源码同步分别验收；Git合并不代表Grok任务已停或Dot已接管。只有核实具体任务、来源及通知连续性后才协调切换。不另建重复调度，不在本任务发送钉钉。

## 数据边界

所有查询通过受控入口，携带显式Snapshot/run_id；保留Pack、Bridge、来源与参考资料的现有权威边界。不读取或复制凭据，不将客户输入、整个工作区或运行产物加入Git。完整服务器数仓迁移暂停；未来MCP权限不由BI上线自动授予。
