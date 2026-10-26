# 10月26日本地代码、文档与工作树收口

## 范围与结果

按用户确认，仅整理本地代码、文档和Git工作树。`main` 收录10月26日手动日更/通知记录，合入 `codex/raw-coverage-evidence` 两个独有提交，并补齐固定publisher的完成证明复核。未推送远端、未部署服务器、未改服务/权限/日程、未触发采集、正式发布或通知。

服务器原有部署与本地代码整合分别记录，不能把测试通过写成生产门禁已经生效。原Mac `p5.daily` 路径和c373数据/证据保留；raw真实新包正式发布和唯一生产者切换仍待另行验收。

## 工作树与分支

| 原对象 | 核对结果 | 本次处理 |
|---|---|---|
| 主目录 main | 工作区原本干净，为整合基线 | 保留并提交本次整合 |
| c373 / shadow-bi-plan | 与原main同提交，三份未提交文档记录10月26日日更和投递；有私有数据、证据与Superset环境 | 三份文档收录main；保留稳定目录和全部忽略数据，源码对齐最终main，以detached HEAD保留，删除重复分支 |
| cba8 / detached | 学校排序脚本与main字节相同，所有新增文档内容已被main收录 | 备份patch/完整修改文件/新增文件和逐文件hash清单后移除工作树；不恢复旧“不设1500门槛”经营人头描述 |
| publish-source / raw-fixed-publisher | 与原main完全一致，无独有修改；忽略文件仅为可再生成字节码 | 留存逐文件清单，移除工作树及已合入分支 |
| coverage-source / raw-coverage-evidence | 两个独有提交，与main后来的固定发布/通知修复分叉 | 合入并补齐证明衔接，验证通过后移除工作树及已合入分支 |

收口后保留主目录和c373两个必要工作目录，本地分支只保留main。c373保留原路径，不修改外部任务配置；不会随着未来main提交自动移动，后续源码同步需明确按已验证提交执行。

## 代码与口径

- 最大记录日与经验证完整截止分离；raw缺受保护昨日完成证明时以coverage_unverified停止，完整零业务日无需伪造交易。
- 同一证明贯穿计算前、39表封口、prepared复用、failed候选维护复验和root固定发布。取消缺decision/证明仍接纳旧prepared或recheck的兼容分支。
- publisher重建前核对证明与metadata，P4重建及下一批基线预检后、激活前再次复核；变更或撤销已被最终复核发现就拒绝激活，失败保留原current。审批运维须持有同一发布锁；不假设能防止绕过锁的root任意改写文件，详见[完整性合同](server-source-completion-candidate.md)。
- 语培经营人头维持1500元班级金额门槛/报名人次规则，个人业绩与产能各自资格不变；未修改Pack/Bridge、留学官方记分卡或通知接收通道。

## 文档收口

README、开发状态、架构、接入/运维/使用指南、同步边界、看板/监控模块与Agent入口已对齐原生BI、raw固定能力和release通知。当前状态从历史施工记录中分离；10月25日基线和具日期验收保留作历史证据。今天手动日更截至10月25日，与更早失败raw包截至10月24日分别表述，HTTP unknown与先前8条sent也不混写。

## 验证

- 完整核心回归：`sh tools/run_tests.sh -q -rs -p no:cacheprovider`，859 passed、198 subtests passed、1 skipped。唯一skip为需独立Superset环境的认证模块；MCP协议测试已在本地现有环境实际执行。
- 固定Superset环境独立认证：`python -B -m unittest tests.test_shadow_bi_legacy_auth -v`，6项通过。沿用c373既有环境，无安装或服务操作。
- 原有缺证据/权限/hash/窗口/日界/零业务日验证，加本次旧候选拒绝和发布衔接测试；测试均使用合成输入/审批/39张fixture表及本地Flask，不冒充真实来源完整证明或生产发布。
- 7个CLI冒烟（Data Platform、Pack validate、workspace modeling、management build、release notifications、P5 daily、raw compute）退出0。`git diff --check`及受影响Markdown本地链接检查通过。
- 回归保留两项已有警告：MCP旧ping方法弃用、反馈包篡改测试故意重复ZIP成员；均非本次失败。

本地备份、前后Git清单、删除对象逐文件size/hash、测试与CLI日志位于 `.local/audits/project-alignment-20261026/`，不进入Git或公开发布。c373客户数据、登录状态、必要运行环境、查询证据和通知状态未清理。最终提交与工作树身份见该目录 `final-state.json`。
