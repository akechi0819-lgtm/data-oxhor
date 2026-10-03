# 固定看板

2026-10-02迁移状态：本地 a224be6 管理看板及7条共同结果产物已验收；P3已在 Grok 现有云电脑完成源码核对、真实 management.build 和只读发布/投递演练（61个文件SHA一致，build exit 0，7条消息和18个公开文件检查通过）。通用 `dashboard_product.management.publication`、`monitoring_product.shared_delivery` 和 `monitoring_product.delivery_transport` 保留。P4旧源码与生产入口已清理，P5正式页面已于2026-10-03激活；生产日常运行继续沿用 Grok 云电脑。Pawsy 全量迁移和上传前置已取消，不重做业务或版式验收。

阶段顺序：P3 Grok 接入 → P4旧入口清理 → P5正式上线均已完成。

本地发布组包演练入口：

```bash
SHARED_RESULT=<本批次>/shared_result.json \
  bash dashboard_product/deploy/publish_management_dashboard.sh --dry-run
```

该入口校验共同结果身份和引用哈希，仅封装4页及其资源（共18个公开文件）；dry-run不读凭据、不联网。通用组包与投递适配已在P3演练并用于P5正式激活。本地dry-run不触发上传、真实发送或页面切换。发送适配说明见[监控模块](../monitoring_product/README.md)，构建产物说明见[管理融合看板](./management/README.md)。

`dashboard_product/management/` 为当前唯一管理看板构建入口，涵盖市场总览、预备高中、大学、线上平台、人员产能和活动。一次受控取数生成共同事实、静态页面与7条通知payload；消息由[monitoring_product](../monitoring_product/README.md)消费同批结果。构建命令及输出见[管理看板说明](./management/README.md)，发布/激活及Grok日更见[部署说明](./DEPLOYMENT.md)。

业务口径沿用已验收的[封存记录](../docs/dashboard-dot-handoff-20261001.md)与当前配置；原始输入、Bridge和Snapshot不因页面重构而改写。留学现金/人头未接入时保留未接入状态，负向现金不自动解释为退款。已确认归属和目标更新在相应现有配置维护，部门去重与个人贡献不能混加。

`refresh.py`、`online_team/build.py` 和 `online_team/export.py` 目前只保留管理计算及导出复用的函数，不再提供旧CLI。`online_team/web/` 的3份模板仍生成已验收线上页面，保留；管理5条SQL、共享人员配置和对照合同仍保留。旧主/影子页面生成器、重复发布脚本及独立通知路径已退役，历史说明见[历史目录](../docs/history/dashboard/)。
