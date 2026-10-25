> 历史说明，仅供追溯；当前入口见[正式部署](../../../dashboard_product/DEPLOYMENT.md)。

# 固定看板

当前唯一构建入口是 `dashboard_product.management`，结合明确BI与独立留学Snapshot生成页面、人员贡献与8条通知。腾讯抓取脚本、6—9月标准历史和10月实抓已在Grok验证；最新腾讯版已构建／组包，尚无本次activation回执，不能把原服务上线记录当成新版发布状态。当前范围见 [管理说明](../../../dashboard_product/management/README.md)与[同步说明](../../../SYNC.md)。

每日来源由独立双仓生产者负责；看板日更不重复抓源，只消费当天联合成功的当前两仓并发布。双仓回执缺失、失败或身份不一致时阻断新发布。原P3/P4/P5于2026-10-03完成，过程记录保留在历史施工说明。

本地发布组包演练入口：

```bash
SHARED_RESULT=<本批次>/shared_result.json \
  bash dashboard_product/deploy/publish_management_dashboard.sh --dry-run
```

该入口校验共同结果身份和引用哈希，仅封装4页及其资源（共18个公开文件）；dry-run不读凭据、不联网。通用组包与投递适配已在P3演练并用于P5正式激活。本地dry-run不触发上传、真实发送或页面切换。发送适配说明见[监控模块](../../../monitoring_product/README.md)，构建产物说明见[管理融合看板](../../../dashboard_product/management/README.md)。

`dashboard_product/management/` 为当前唯一管理看板构建入口，涵盖市场总览、预备高中、大学、线上平台、人员产能和活动。一次受控取数生成共同事实、静态页面与8条通知payload；新增高中留学个人简报复用高中通道，消息由[monitoring_product](../../../monitoring_product/README.md)消费同批结果。构建命令及输出见[管理看板说明](../../../dashboard_product/management/README.md)，发布/激活及Grok日更见[部署说明](../../../dashboard_product/DEPLOYMENT.md)。

业务口径沿用已验收的[封存记录](../../dashboard-dot-handoff-20261001.md)与当前配置；原始输入、Bridge和Snapshot不因页面重构而改写。留学现金／人头已经接入独立仓；真正未覆盖或缺来源时保持相应缺失状态，已接来源无记录时按已确认规则显示0。负向现金不自动解释为退款。已确认归属和目标更新在相应现有配置维护，部门去重与个人贡献不能混加。

`refresh.py`、`online_team/build.py` 和 `online_team/export.py` 目前只保留管理计算及导出复用的函数，不再提供旧CLI。`online_team/web/` 的3份模板仍生成已验收线上页面，保留；管理5条SQL、共享人员配置和对照合同仍保留。旧主/影子页面生成器、重复发布脚本及独立通知路径已退役，历史说明见[历史目录](.)。
