# 日常监控云端部署验收（2026-09-16）

状态：已完成代码部署、真实数据预览、看板无发布刷新验证、角色分工与权威 Routine 读回。未在迁移过程中真实发送或补发钉钉；未来按既有例行授权执行。

## 角色与排期

| 角色 | 职责 | 例行 |
|---|---|---|
| 孙悟空 | 数仓更新 | 原 09:30 不变 |
| 许家印 | 固定看板刷新与发布 | 原 10:00 不变 |
| 魏忠贤 | 人员监控与钉钉日推 | 原 10:30 Asia/Shanghai |
| 牛马力工 | 同步、接线与部署验证 | 本轮施工 |
| 赵高 | 跨角色协调与验收 | 本轮协调 |

监控 cwd 为 `/home/box/oxhor/monitor`，入口 `python -m monitoring_product.notify send`，使用 warehouse venv。只读查询数仓、只读查看看板，只写本次监控输出；不写仓、不刷新或发布看板。这是 Agent 运行合同，不宣称新增 OS 硬隔离。

权威 Routine ID：`5937c316-103d-5e32-8684-f103cbc82db3`，魏忠贤名下「线下+虚拟人钉钉日推」，已启用。`automation-1789007238456` 仅为历史本地目录名，后续更新须用权威 ID。实读确认只有一条启用日推。通道保持线下青少、高中、大学及线上私域，未加入线上平台。

截止日期只接受当前 Snapshot 的受控查询，或明确 run_id 且同 Snapshot 的凭据；禁止按修改时间和模糊目录选择。查询失败整批阻断。

## 代码与验收

- A 层包已于 2026-09-20 清理本机同步中转目录；本记录保留其 70,698 bytes、31 文件和 SHA256 `fb6f54df7d6c58d65afad93ba1d01802d892ae1c5565e803b7a30efa4e52942e` 摘要，不作为运行入口。不含 B/C 层。
- 监控安装到 `monitor/monitoring_product/`。共享规则与花名册唯一落在 `warehouse/workspace_modeling/operations/`，供看板与监控引用；旧通知和临时兼容软链已删除。
- 云 refresh 的体积差异来自尚未抽出的共享函数。AST 等价核对后采用包版，SHA256 `e16b88cbfae9f455b74b7aba851c9a6e1541ca75ff74c4fdc58034826ea987c2`。
- 云 pyproject 保留既有 ppt optional dependency，仅增加监控包和共享配置声明。云文件仅回写 inbox，未覆盖本机其他任务的依赖修改。
- 云监控测试 19/19、看板所选三组测试 27/27。
- 真实 Snapshot：`snapshot_bi_operations_20260916_m6merge2`。
- 监控预览：`run_monitor_20260916_152131_dry`，as-of 2026-09-16，数据截止 2026-09-15；四通道与同 Snapshot 旧通知对照，进度及落后名单一致，PNG 字节一致。
- 看板真实刷新验证：`run_dashboard_20260916_pkgrefresh_153504`，未发布、未发送通知。
- 权威任务从实际 automation_status 读回，已核对新入口、时间、通道和唯一性。早期仅修改本地影子配置的遗漏已纠正。

原始回执已于 2026-09-20 清理；`deployment-20260916.json`、`ROUTINE_READBACK.json` 和 `LOCAL_VERIFIED_SUMMARY.json` 的结论只保留在本记录中。早期 `ROUTINE_PROMPT_SUGGESTED.txt` 不是运行入口，不得用于重建任务。

密钥留在原云端位置，正式例行通过显式 env-file 引用，本轮未复制或打印。后续同步继续遵守 SYNC 分层与本机真源约定。
