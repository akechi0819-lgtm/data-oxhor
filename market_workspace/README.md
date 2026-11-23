# 市场工作区

以后新建市场任务时，选择这个文件夹：

`/Users/akechi/Desktop/manager -CowH/market_workspace`

你可以直接提出市场分析、写报告、生成小程序等需求，Agent 按本目录的 `AGENTS.md` 执行。数据只读引用主目录正式数仓 `/Users/akechi/Desktop/manager -CowH/customers/shadow_bi_daily/`，不新建公司、不在市场工作区复制数仓，也不更改口径。

留学官方记分卡同样只读，实际来源为 `/Users/akechi/Desktop/manager -CowH/customers/shadow_bi_daily/Input/Reference/留学板块-官方记分卡.md` 和 `/Users/akechi/Desktop/manager -CowH/customers/shadow_bi_daily/Input/Reference/留学板块-官方记分卡.json`；不得修改、入仓或写入 Bridge。

| 目录 | 用途 | 清理方式 |
|---|---|---|
| `Programs/` | 生成的程序与工具 | 不再使用时删除对应任务目录 |
| `Scratch/` | 临时脚本、草稿、缓存 | 按任务清理；正式成果不依赖这里 |
| `Reports/` | 正式交付及必要附件 | 按成果保留，不当临时目录清理 |
| `Evidence/` | 查询结果、SQL、来源回执 | 保留被正式报告引用的运行记录 |
| `Notes/` | 参考资料与工作笔记 | 按业务需要维护 |

`oxhor`、`tools/` 和四份入口文档是固定设施，不放生成的业务小程序。上述五个内容目录已从 Git 排除，避免临时产物和经营数据进入代码仓库；没有给数仓或源码创建目录软链，清理本地任务不会沿链接进入数仓。

## 两个聊天的落盘位置

| 使用场景 | 放置位置 | 收尾时保留 |
|---|---|---|
| 开发线程改 SQL、代码、合同 | 项目根目录对应模块；本机验收写 `.local/audits/<任务>/` | 代码、现行说明和验收回执 |
| 牛马经理做报告、PPT、HTML、导表 | 在 `Scratch/<任务>/` 制作，最终交付到 `Reports/<任务>/` | 一个可打开的最终版本及所需附件；各期按业务日期区分 |
| 牛马经理查数或维护登记表 | 查询证据写 `Evidence/<run_id>/`；持续同步工具及登记状态写 `Programs/<任务>/` | 报告引用的证据、持续使用的程序与状态 |
| 日更建仓、发布及通知 | 客户工作区的 `Work/`、`Output/` 与 SQL 指针指定的候选目录 | 当前主本、发布身份、必要回执及恢复输入 |

在聊天里交付链接直接指向 `Reports/<任务>/` 内的成品。同一任务再次修订沿用原目录，制作工程、逐页渲染与打包暂存留在 Scratch，验收后清理。新任务无需在项目根 `outputs/` 或 `Reports/projects/` 再建一套目录。

## 使用

在本目录运行 `./oxhor status` 可以核对数据状态。接口说明见 [INTERFACES.md](INTERFACES.md)，读写范围见 [ACCESS.md](ACCESS.md)。你不需要自己填写 SQL 或内部 ID，这些由 Agent 依据当前状态处理。

这里是日常市场工作入口；系统架构维护仍在项目根目录，看板和监控维护进入各自模块。此工作区依赖相邻项目源码及其 `.venv`，不是可脱离项目单独复制的安装包；不要只移动这个文件夹后继续使用原绑定。
