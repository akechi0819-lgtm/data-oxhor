> 历史存档：原路径 `dashboard_product/docs/MERGE_WANG_YUE_HANDOFF.md`，于 2026-09-18 目录整理时归档。以下状态、命令、版本与凭据配置描述仅代表记录当时，不是当前操作入口。当前项目状态见 [DEVELOPMENT.md](../../../DEVELOPMENT.md)；看板现行操作见 [DEPLOYMENT.md](../../../dashboard_product/DEPLOYMENT.md)。

# 派工：合并虚拟人看板重复「王玥」

定合同/验收：许家印
施工：牛马力工（grok build）
许家印不施工。

## 用户令
虚拟人（`online_private`）高中相关板块里「王玥」出现两人份，实为同一人，合并。

## 现状（初扫）
`workspace_modeling/operations/people.json` 中 `online_private` 下同一人出现两次（同 `person_id=wang_yue`，`display_name=王玥`）：
1. 组：`高中多途径组`
2. 组：`国际学校择校组`

看板人员区按组成员展开，故会显示成两个王玥；归属按姓名匹配时也可能重复累加，需合并后验证。

## 施工
1. 将花名册改为**只保留一条**王玥（保留哪个组：优先留在「高中多途径组」；若业务上她兼两组，仍只保留一条人员记录，组归属按你们现有单人单组模型选一，不要两条）。
2. 跑单测（若有人员配置相关）+ 对当前 snapshot refresh→四分册真发（或至少 online_private/full）。
3. 验收点：`online_private` 分册人员区王玥只出现一次；工单/现金个人数不因重复配置翻倍。
4. RUN 回许家印（无密钥）。勿改口径公式，只修花名册重复。
