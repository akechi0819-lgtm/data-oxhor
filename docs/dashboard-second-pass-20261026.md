# 看板第二轮本地复查（2026-10-26）

复查基线 `c0f43e8f`。范围为受版本控制的看板/监控/项目上下文源码、Agent及现行文档；不进入客户数据、凭据、业务查询、服务器或外部日程。只在本地修正确定残留，不以历史关键词批量删除已验收规则或证据。

## 本轮发现与处理

1. `online_team/build.py` 仍有只被旧P1测试调用的training_facts、study_facts、classify_team、abroad_eligible、is_ssc、allocate_targets、training_target及专属text/helper/import。现行事实已走management各自模块，删除这组死代码及专属测试，保留当前使用的期间、金额、study_target、渠道/学校维度与受控查询helpers。
2. 8个纯P1实验文件仍可生成旧投影、创建loopback元数据或登录旧18088端口；与当前P4→P3/P3.5、raw worker和release通知无调用关系。删除根目录下P1的activity.html、bootstrap.py、build_projection.py、extension.py、initialize.py、superset_config.py、verify_api.py、verify_evidence.py。清理前源码留于Git基线，私有实验环境及历史证据不动。
3. `calculation.calculate` 仍默认写旧DashboardManagement目录；唯一现行caller原本已显式写ShadowBI。取消过时参数，统一原生BI输出路径；新增输出身份先于查询的回归测试，未改变聚合公式。
4. Project Intelligence集成图仍报static_server静态发布目标。改为bi_server，描述原生BI、服务器双数仓/共享聚合与固定发布；仍明确document_declared、live_status=not_verified，不探测服务器/调度。增加该只读边界回归。
5. workspace_setup Agent残留Grok旧时间表；deploy README落后于raw/通知扩展并仍将已修状态权限列为缺陷；P1/P3 README仍给过时临时启动命令。已按当前源码校准，分别解释成品HTTP、Mac直接SSH+P4、raw和通知队列，不将它们混成同一路径。P2/P3作为历史阶段索引，现行操作统一指向部署说明。
6. P4 TLS配置注释仍引用旧静态站状态，仅修正理由，不改变任何配置值。素材README指向未复制的制作记录、仍称“待导出”，已按当前素材路由和实际文件校准；上游许可原文与LICENSE不改，明确其中6条相对链接属于上游仓库而非本项目。

## 明确保留的现行依赖

- 原18账号的htpasswd认证与维护程序、release通知、通知附件HTML/PNG/XLSX、DeliveryState和私有证据；不能因legacy或index.html命名当作旧站删除。
- management现行事实、归属、聚合、人员与费用规则，refresh的当前归属/历史对照；不修改Pack/Bridge、官方记分卡或指标资格。
- P3 bootstrap/extension仍由P3.5/P4使用；requirements-p1.txt仍被P4依赖文件引用，lock保留依赖版本证据。它们不等于纯P1启动服务。
- 原生Nginx主页跳转、/p3应用及通知资产路由；上一轮已移除本地模板旧HTML/数据白名单。本轮未修改或验证现网Nginx状态。

服务器已承载历史数仓基线、双Snapshot/quality与聚合39表计算，不能因某raw批次截止门禁失败改写成“未迁移”。来源完整性新门禁仅本地已合未部署；持续日更/有效新包发布/唯一生产者安排以独立回执核对。本轮不增加关于服务器当前健康或调度启停的结论。

## 验证和边界

- 完整回归：840 passed、198 subtests passed、1 skipped；唯一skip是Superset认证模块，已在既有独立Superset环境另测6项通过。测试下降来自删除死代码专属测试，不是跳过现行业务测试。
- 现行共享helper/聚合专项198 passed、69 subtests；输出身份及Project Intelligence边界专项20 passed、5 subtests；7个CLI冒烟退出0。
- 内部import目标静态检查无缺失，支持现有namespace package；现行文档本地链接检查无失效入口。6条上游许可相对链接作为原文保留，由素材README说明引用语境。
- `git diff --check`通过。删除对象均有基线源码及size/hash清单；源码清理改变代码/规则摘要，新批次重新封存，不回写历史manifest、输入或业务结果。

详细日志及前后Git/文件清单放 `.local/audits/dashboard-second-pass-20261026/`。收尾时发现c373有其他工作的未提交服务器清理记录，因此未覆盖或切换该工作树；保留其原HEAD与新增文件，只将带日期回执收录main并更新现行文档入口。原记录记载raw已暂停、保留Mac更新；本轮不据此执行任何服务器或调度操作。并发工作原状态与新增文件size/hash已在审计目录保留，不读取凭据内容。服务器、调度、通知、现网配置与远端仓库均未改动。
