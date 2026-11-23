# 市场工作区

这里是当前公司市场工作的独立入口。默认处理市场自由分析、报告、工具和临时程序；不进入全项目架构维护。直接打开本目录即可开展任务，首次先读本文，不预读所有模块说明。

## 数据与接口

- 数据固定绑定到主目录正式数仓 `/Users/akechi/Desktop/manager -CowH/customers/shadow_bi_daily/`，工作角色为市场；沿用其 `operations` 端口、现行 Pack/Bridge 与当前 Snapshot。数据、Bridge 和记分卡只读，不修改数据工作区配置，也不在市场工作区复制或移动数仓。
- 开始业务分析先运行 `./oxhor status`。只有 `next_step=analyze` 才继续；读取返回的显式 Snapshot、Pack 与 Bridge 路径。状态异常转工作区初始化/对齐流程，不绕过。
- 通过 `./oxhor describe|quality|query|saved-query|cases|verify-case` 调用现有受控接口，每次显式传入 status 返回的 `--snapshot-id` 和唯一 `--run-id`。禁止直接连接 DuckDB。
- 查询结果、SQL 与回执统一写 `Evidence/<run_id>/`；同一 run 不覆盖。历史结果不替代当前 Snapshot；Casebook 只提供方法线索。
- 当前留学经营的明细、拆解和对账使用 `customers/shadow_bi_daily/Work/StudyAbroad/current.json` 显式绑定的独立留学 Snapshot，从项目根目录通过 `python3 -m dashboard_product.management.study_abroad_query` 受控查询，输出位于客户工作区 `Output/StudyAbroad/`；命令见 `../docs/integration-guide.md` 第 2.2 节。原 BI 仓仅用于工单归因或明确标注的历史复算；正式看板对账须使用同批 SQL 发布口径。
- 留学线上/线下完成值与 FY27 目标以 `/Users/akechi/Desktop/manager -CowH/customers/shadow_bi_daily/Input/Reference/留学板块-官方记分卡.md` 为准，置信度高于数仓；本目录 `Notes/留学板块-官方记分卡.md` 只是只读指针。数仓用于明细和对账，冲突时不得覆盖记分卡。
- 详细参数按需读 `INTERFACES.md`；授权路径见 `ACCESS.md`。业务分析方法按需读 `../agents/ad_hoc_analysis/AGENT.md` 和对应 Skill，不展开其他模块。

## 写入位置与清理

- `Programs/<任务名>/`：生成的程序、小工具及各自依赖；需要长期使用的工具也先落在这里。
- `Scratch/<任务名>/`：临时脚本、草稿 SQL、缓存、一次性实验，可以按任务整目录删除。
- `Reports/<任务名>/`：正式报告、表格、PPT、交付网页及其必要附件，不放在 Scratch。
- `Evidence/<run_id>/`：正式结论引用的查询证据，不随临时脚本一起清理。
- `Notes/`：市场参考资料和持续工作笔记。
- 执行[根入口的任务文件与收尾规则](../AGENTS.md#任务文件与收尾)：同一聊天修订同一成果沿用同一任务目录，在 `Scratch/<任务名>/` 制作 PPT、HTML、截图与压缩包，显式指定工具工程及输出也在该目录。交付时仅将最终文件及必要附件放入 `Reports/<任务名>/`，正式交付不得依赖 Scratch。
- 当前聊天的任务目录即可作为收尾清理范围，无须用户再次指定；其他任务仅在用户明确指定时处理。保留人工原稿、正式依赖和查询证据，不批量清理父目录。

## 职责边界

本目录内的自由编辑与生成代码允许进行；核心代码、数仓、Bridge、花名册、看板、监控、云端任务与密钥默认只读或不访问。要修改其他模块，先定位相应板块，并按用户明确的修改范围工作，不借自由编辑扩大授权。

看板可只读核对；不得自行刷新、发布或发送钉钉。PPT 仅在用户需要时调用宿主全局 `ppt-master`，使用已验证证据，不预加载制作规则。当前数字必须可回查；负向现金不自动称退款。

目录隔离与本文是 Agent 工作约束，不是操作系统沙箱；实际权限以宿主和系统为准。调用相邻接口是复用工具，不表示需要读取整个源码目录的文档。

## 线上产出周报固定约束

制作市场周报、双周报、各项目线上产出汇报或重跑投流ROI／素材反馈时，先调用项目 Skill：`.agents/skills/market-online-report/SKILL.md`。在填入周报／双周报前，按该次已确认周期跑一轮各项目报表作为素材参考，无需用户另外提出“跑表”。遵循其中逐项目“图片＋正式配文”的交付方式。

用户当轮修改优先；不据此创建定时任务、刷新数仓或对外发送。旧 `Notes/线上产出周报长期规范.md` 已改为 Skill 指针，避免多份冲突规则。

凡是制作、续写或修改新媒体双周报，默认调用项目内 `../.agents/skills/new-media-biweekly-report/SKILL.md` 统筹交付。上面的套图是第一阶段，不代替双周报正文；用户已确认本期套图时直接复用，不重复跑表。
