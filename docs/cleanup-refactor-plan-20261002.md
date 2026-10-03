# 瘦身后最小改造计划

日期：2026-10-02，最终收口2026-10-03。原计划三项及后续维护源码同步均已完成：看板上线见第32节，项目复查见第33节，BI/安装/名单参数化与上下文源码双端同步见[施工计划第34节](./dashboard-static-rebuild-plan.md)。96个目标/14个重点源码匹配，云端137项定向合成测试通过。以下保留本机施工与当时复查记录；数仓更新由用户按需手动执行，不是本轮待办。

## 原计划复核后的取舍

一级模块划分保留。原计划限定为 **BI更新修复、安装瘦身、迁移后退出旧链** 三件事，按小提交独立完成；代码修改使用现有Git差异、提交和回滚能力。

原报告中三项判断已修正：

- ETL在内存DuckDB中读取Parquet合法；问题是历史缺失时静默丢历史，不要求ETL另走分析查询或生成分析回执。
- Bridge画像已只读校验Snapshot并限制样本；私有接口属于实现耦合，本阶段不单独重构，也不增加审批或读取限制。
- Dashboard使用Monitoring公开的截止日/传输能力合理；旧通知如果将退出，就直接退役，不先翻修其私有导入，不为目录对称搬公共函数。

复核依据见本机[原报告及覆盖结论](../.local/audits/cleanup-20261002/REPORT.md)、[Astra独立评审](../.local/audits/cleanup-20261002/astra-review.md)。这些是本机审计材料，不随产品部署。

## 1. 修BI更新的实际错误

**收益：** 不误删其他来源、不因历史文件缺失截断历史、失败后仍能继续使用原输入和当前Snapshot，成功回执给出可用路径。

范围为 `data_acquisition/jobs/rebuild_bi_warehouse.py`、`bi_window_merge.py`；只在复用现有sync检查时小幅调整 `workspace_modeling/bridge_alignment/workspace.py`。不改工单ID合并、现金窗口替换、业务日期、金额或渠道口径。

具体改动：

1. 删除对全部 `Input/Data` 来源槽位的清空，只更新 `br_work_orders`、`br_cash`。
2. 将现有重复Snapshot、活动对齐会话等sync检查复用到下载/替换前；不再另写一套检查规则。
3. 区分“没有历史的首次导入”和“已有current但历史文件缺失”。后者明确报错；删除推测run目录及glob取首项。按当前Snapshot现有manifest的身份、sources/sheets/target_table和产物路径定位两个来源，不建新registry。
4. 仅对本次被替换的两个BI槽位临时保留原文件，导入或ingest失败时恢复，成功后清理本次临时保留。客户输入被Git忽略，代码回滚不能还原它们，这是该局部恢复步骤的用途；不扩展为通用备份或事务框架。
5. 修正成功后返回的路径：`_bi_downloads`已删除，不再将其路径作为可用产物；回执指向实际Input文件和原导出留存。直接消费者同步更新，删除失效字段或语义，不加兼容分支。

验证使用临时合成工作区：首次导入正常；完整历史正常合并；current存在但landing/某来源缺失时拒绝；重复Snapshot/活动会话时不改输入；第二槽位或ingest失败后两个槽位与指针保持原状态；额外来源保留；成功回执引用文件存在。继续通过既有滚动合并测试，保留现金重复行语义。实现时加能复现这些错误的少量回归，不跑真实BI登录或客户刷新作为开发前置。

主控已复现：合成current指针及warehouse文件存在、landing缺失时，现有合并不报错，历史行数为0，只输出近窗口的新行。[复现回执](../.local/audits/cleanup-20261002/missing-history-reproduction.json)。这是合并阶段的复现，未执行真实sync；“成功sync删除旧run”为现有代码事实。本次不改变成功sync的既有生命周期，也不增加永久Snapshot历史保留系统。

完成后该小任务结束，不顺带迁移清洗规则、改变Bridge或重构数据平台。

## 2. 修安装断点并精简依赖

**收益：** 新环境能按现有命令装起来，减少项目安装中无业务调用的PPT、文档转换、音视频、模型SDK等依赖。

范围为 `pyproject.toml`、`tools/install_runtime.sh`、`workspace_modeling/onboarding/service.py`、`tests/test_onboarding.py`，以及安装/doctor的直接说明和首次部署Skill。

- 删除已过期的 `ppt` extra/profile、`test + ppt`组合和对不存在的 `tools/s4_ppt_preflight.py` 的调用。保留 `core/test/full`，不新增安装profile或替代预检体系。
- 按项目实际import及测试使用确认后，移除无消费者的宿主依赖和对应doctor检查。保留BI、看板、监控实际需要的库；`test`应能运行现有项目测试，而不是借PPT依赖凑环境。
- doctor、extras、安装脚本和说明同步为同一实际支持范围。Project Intelligence保持已说明的源码运行方式，不在此扩展wheel分发或新MCP安装层。
- 不当场拆掉正在使用的 `.venv`；用临时环境验证精简安装，再在正常环境更新时采用。依赖精简前后的安装体积按实际结果记录，不预先承诺节省量。

补证：安装脚本在test/ppt/full安装后调用已不存在的S4检查文件。现有 `test_doctor_checks_runtime_and_pack` 也已失败：测试期待DuckDB/openpyxl/Pillow/Pack，实际doctor额外检查7项宿主依赖，见[现有测试复现](../.local/audits/cleanup-20261002/doctor-test-reproduction.json)。

验证包括临时环境安装、shell语法、doctor、相关CLI导入/帮助及现有受影响测试。沿用既有测试入口，不新增常驻依赖扫描器或全面部署门禁。

默认在BI修复后做此项；若迁移机器先被安装脚本阻断，可先独立提交脚本快修，两个任务没有顺序依赖。当前已有未提交依赖精简改动，实施时在该工作树上核对并补齐，不覆盖其他任务的修改。

## 3. 沿既有迁移计划直接退出旧链（已完成，2026-10-03）

**收益：** 正式运行只消费共同结果，删除重复取数/计算/发送路径及其无用配置与测试，进一步减小维护范围。

此项沿用既有迁移计划的P3→P4→P5顺序完成，没有新增上线审批或重复业务/版式验收。实际云端接入、旧链退出和正式上线回执见[看板施工计划第32节](./dashboard-static-rebuild-plan.md)。

1. 正式链已切到 `management.build` → 同批共同结果 → 静态发布和 `shared_delivery`；原看板日更调用新版入口，原钉钉例行保持暂停。
2. 旧通知 CLI、独立取数查询、旧页面/影子生成入口，以及仅供这些路径使用的配置、说明和测试已按实际消费者清理。具体退出清单见P4回执。
3. 仍由新版使用的业务函数和独立对照予以保留：`management.facts` 使用 `refresh.remap_tmk_school_agent_team`，`management.build` 使用 `refresh.project` 作基线；共享代码继续由当前管理构建调用。
4. 旧通知SQL和其内嵌花名册退出后，原花名册重复维护已消除。59名历史顾问映射也已改为两条SQL读取现有 `MAPPING` 配置并同批同步Grok，标签与筛选保持等价。不同业务用途的留学个人配置和语培花名册继续分别维护。
5. 官方记分卡的业务确认资料、机器历史对照和产品目标角色已在现有说明中区分。本轮没有数字冲突证据，未自动改数，也未建设同步或版本治理平台。

完成核对沿用现有预览/组包/发送回执、源码消费者检索和受影响测试；实际切换以执行与交付回执确认。未新增切换控制系统。

P4目标环境的旧运行入口和旧页已按对应回执退出。本机迁移包与回执继续作为忽略目录中的历史材料保存，不作为运行入口，也不在本轮文档收口中删除。

## 不列入本阶段

新顶层模块、总控Agent、通用registry、通用事务/备份平台、自动清理服务、Bridge画像专项改造、为包结构统一扩大wheel支持、跨公司产品化、记分卡治理平台、Git历史重写、按年龄批删所有Snapshot。

不要求每次修改复做16,392个文件哈希或全量业务验收。普通源码改动按Git小提交与对应测试处理；仅本次替换的非Git输入做局部恢复。已有Snapshot身份、只读查询和发送去重等正常产品能力继续复用，不围绕它们新增重复检查。

## 施工结果（2026-10-02）

| 项目 | 状态 | 实际结果 |
|---|---|---|
| BI更新修复 | 已完成 | 提前复用sync检查；精确manifest定位；只替换两个来源；失败恢复/状态未知保留本次备份；回执仅含可用路径。首次导入、重复Snapshot、第二槽位失败、ingest失败、发布后异常和恢复失败均有合成回归。 |
| 安装断点及依赖 | 已完成 | core/test/full安装链可用；full直接依赖由21项收敛为6项，test不依赖PPT；doctor检查实际库；测试入口恢复主/看板/监控覆盖，管理测试由现有看板聚合入口纳入。 |
| 旧链退出及名单收口 | Grok旧链退出完成；新增映射收口本机已完成 | 34个旧运行路径和旧3页已退出；09:45看板启用、10:24日推暂停。旧通知SQL中的花名册副本消除。两条活跃SQL中的59人确认映射已参数化读取已有配置；本次增量尚未同步Grok。本轮256项测试通过；剩余BI云端部署与数据回写见第33节。 |

主控用独立源码及虚拟环境实际执行安装脚本：test安装及三组测试通过；随后full安装、doctor、pip check和数据/BI/管理/共同结果发送CLI帮助均通过。最终三组测试为142、123、83项，共339项通过、9项独立MCP协议测试因未安装SDK跳过。没有把skip声明为协议验收；当前项目 `.venv`保留原样，没有卸载原环境。完整新full环境磁盘约215 MiB，未安装浏览器引擎或独立MCP SDK，不把该值等同本机已释放空间。

干净环境还暴露一个旧测试依赖私有客户SavedQuery registry；已让该单测核对源码SQL中的文本工单ID/金额类型，部署registry一致性仍由已有发布流程负责，不靠单测读取客户目录。BI与Bridge定向29项测试通过；Astra复读最终代码和新增错误场景后终审通过。`git diff --check`及shell语法通过。

本机详细记录：[BI实施](../.local/audits/cleanup-20261002/bi-implementation.md)、[安装实施](../.local/audits/cleanup-20261002/runtime-implementation.md)、[Astra实施终审](../.local/audits/cleanup-20261002/astra-implementation-review.md)、[最终验证](../.local/audits/cleanup-20261002/implementation-verification.json)、[退役消费者清单](../.local/audits/cleanup-20261002/retirement-consumers.json)。源码变更保留在当前工作树，本轮没有整体提交其他任务的未提交修改，也未刷新真实客户、发送钉钉、发布页面或改变外部任务。
