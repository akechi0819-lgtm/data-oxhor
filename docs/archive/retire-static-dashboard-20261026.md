# 旧静态看板退出与服务器职责对齐（2026-10-26）

## 本次决定

用户确认正式原生BI已上线，旧看板兼容/恢复代码不再保留；同时补充数仓和聚合脚本大头已迁入服务器。现行说明据此与已存在的部署回执对齐，不再写成“服务器只能装载成品表”“聚合仍只在采集端”或“数仓迁移暂停”。

服务器已有root只读历史基线、raw三Excel接收、受限双Snapshot/quality/共享计算worker和固定publisher。10月26日真实三Excel批次已完成双Snapshot和quality、运行到39表构建，最终因截止门禁失败而未发布；这不能否认数仓与聚合已在服务器落地，也不能代替有效新包正式发布、持续日更及唯一生产者收口的验收。来源完整性新门禁上一轮只合入本地，未在此次清理中部署。详见[部署说明](../../dashboard_product/DEPLOYMENT.md)。

## 删除与保留

本地删除31个旧站源码/资产/测试文件：

- `management/web/` 与 `online_team/web/` 的静态页面、JS和CSS；`management.build` 页面构建器、`online_team.export` HTML打包器、`management.publication` 静态release组包器。
- 旧静态日更、上传、激活、Nginx模板和静态认证安装脚本；原 `deliver_management_batch.sh` 旧批次指针投递入口。不保留恢复开关或转发兼容壳。
- 只为旧静态渲染、组包、发布/激活和兼容consumer服务的测试；数据接入生产者的两项测试保留。

原生P4 Nginx本地模板移除旧HTML跳转、静态JSON/CSS/JS白名单与旧站root；主页仍指向原生BI，保留原生代理及现有通知附件路径。通知渲染删除团队→旧HTML的地址映射，直接使用调用方传入的完整原生BI URL，真实release通知入口不变。

保留原生BI当前使用的共同业务规则、人员与费用计算、受控查询、原始输入/双仓和证据、原账号认证、通知图片/表格与DeliveryState。`online_team.build` 是现有共享计算/query helper，`refresh.py` 仍提供当前归属与历史对照算法，并非旧站兼容入口。聚合模型隐私/身份校验从已删HTML导出器移至 `management.validation`，新增原生模型边界测试。

Project Intelligence仅将已删构建器的精确只读入口改为当前calculation/validation，不扩张到整个目录。README、开发状态、架构、接入/运维指南、部署/同步和各模块入口同步更新；历史日期回执不被改写为当前状态。删除前逐文件size/hash及完整清单保存在本地审计目录，Git提交 `04a21013` 保留清理前源码，当前不提供恢复运行入口。

## 验证

- 完整回归：`sh tools/run_tests.sh -q -rs -p no:cacheprovider`，847 passed、198 subtests passed；核心唯一skip为Superset认证模块，已在既有独立Superset环境另测6项通过。数量下降对应删除旧站专属测试，并非跳过现行业务验证。
- 原生通知链接及release通知专项29项通过；新的聚合模型测试覆盖正常身份、缺失批次/日期、嵌套私人事实/查询证据及空/错误模型。旧站入口不再有任何运行代码或恢复开关引用。
- 7个当前CLI冒烟退出0，`git diff --check`及受影响Markdown本地链接检查通过。
- 本机无nginx可执行文件，未运行nginx实机配置测试；仅审查本地模板删除，未安装、reload或修改现网配置。

## 本地与现网边界

本轮只提交本地源码与文档，未推送、未部署服务器、未改任何日程、未触发采集/正式发布/通知，未清理客户数据、凭据、原始输入或历史证据。现网旧地址配置不会因本地删除自动改变，不能把此提交写成服务器已下线旧资源。

`main`为本地基线；c373保留既有数据、证据和稳定路径，以detached HEAD对齐本次已验证提交。私有文件用lstat元数据前后比对，不读取凭据内容。审计、测试日志、CLI和最终Git身份位于 `.local/audits/retire-static-dashboard-20261026/`。
