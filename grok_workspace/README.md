# Grok Bot 自管工作区

这里是 Grok Bot 的角色材料、运行笔记、临时程序与试验工作面，与 Data OXHor 核心源码分开维护。只有本文件、AGENTS.md 和 .gitignore 进入核心 Git；其余内容默认忽略，不参与 Python 打包、Project Intelligence 文件发布或例行核心代码覆盖。

## 目录归属

- `roles/`：Grok 各角色的自管说明，初始材料来自原根 ROLE.md 与 docs/oxhor；由 Grok 按实际运行维护，不要求与核心文档逐行一致。
- `programs/`、`scratch/`：自行生成的辅助代码和试验，各任务自己维护依赖，不能成为核心运行的隐含前置。
- `notes/`、`history/`：角色积累和历史派工记录，不作为项目当前架构、SQL或业务口径真源。

核心真源仍是上级项目的 README、AGENTS、DEVELOPMENT 和模块合同。业务数据仍在既有 customers 工作区；市场日常成果仍在 market_workspace。Grok 的自管区不复制数仓，不把临时 SQL 晋升为正式口径，不自行修改核心公式。

## 本机与云端

本机本目录是隔离容器；云端对应 `/home/box/oxhor/grok_workspace/`，允许 Grok 自行组织具体内容。现有 warehouse/dashboard/monitor 稳定运行目录继续保留；岗位工作记录和临时程序逐步转入自管区，不为角色目录调整改变计算规则或例行频率。

代码及数据交换仍遵守 [SYNC](../SYNC.md)。同步中转位置为核心项目 `.local/sync/`；密钥层材料另放 `.local/private/`，不混入常规包。禁止把整个自管区自动回灌到核心 checkout。

这是目录、调用和发布边界，不宣称已经构成操作系统沙箱。需要修改核心时，另按明确任务实施并验证；不通过保留旧路径软链制造双轨。
