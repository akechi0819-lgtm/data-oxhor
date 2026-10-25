# 工作树归属核查（2026-10-23）

用户要求旧版与新版两条工作线。总线程及独立子智能体核对实际文件后，未发现需要从主目录迁移到c373的P0—P3.5施工文件，因此未执行重复复制或覆盖。

| 工作线 | 目录 | 分支与内容 |
|---|---|---|
| 旧版主线 | /Users/akechi/Desktop/manager -CowH | main；保留既有学校排序修改及前期服务器方案 |
| 新版影子看板 | /Users/akechi/.codex/worktrees/c373/manager -CowH | codex/shadow-bi-plan-20261022；P0—P3.5源码、规则库、阶段文档、独立数据与审计证据 |

主目录现有DEVELOPMENT.md、SYNC.md、management/README.md、management/web/flat-tables.js及server-warehouse-bi-plan-20261022.md均为旧有修改/前期方案，应原地保留。主目录不存在shadow_bi源码、business_library实现、heads.py、calculation.py或shadow-bi阶段文档；这些文件及P0/P1/P2/P3审计产物均在c373。

另有cba8 detached工作树，与主目录同起点、五个变更文件逐字节相同，没有影子施工源码；未确认聊天归属，未删除或搬动，不作为第三施工线。

## 聊天归属问题

总验收聊天当前cwd为c373，已通过attach_worktree正式附加该工作树。P0—P3.5此前用原项目local创建，默认cwd仍指向原目录；实际施工以显式workdir/绝对路径落在c373。文件归属正确不代表聊天绑定正确。

当前工具没有将任意已有聊天cwd改到指定共享工作树的操作；handoff会迁移Git状态，不能作为单纯改目录标签使用；CUA对Codex应用的操作被工具安全策略拒绝，未绕过。已要求P3.5显式指定c373并尝试附加已有工作树，仍需验证聊天cwd才算绑定修复。后续阶段从c373同目录fork并核验cwd，不能再用原项目local创建后仅靠提示词指定目录。

本次仅登记工作树、核查文件及记录组织规则，未改业务代码、移动数据、重启服务、提交或发布。
