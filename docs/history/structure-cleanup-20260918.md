# 2026-09-18 物理结构整理记录

状态：本机整理已完成并验证；云端已建立 Grok 自管工作区并接收迁移包，最终云端保护哈希与例行路径回执待回传。Mac 锁屏阻断了 Grok 界面的后续操作，不能据预检将云端实施标为已验收。

## 本机结果

- 删除空占位 analysis_product 及打包/模块声明，删除两个空任务目录、空旧运行目录和可重建缓存。
- 根 ROLE 与 docs/oxhor 中角色材料移入忽略 Git 的 grok_workspace，自管说明和隔离边界为仅有的受跟踪入口；重复 warehouse 角色说明合并，独有 BI 说明保留。
- 项目交接、结束的架构计划、看板历史记录和旧同步合同共 19 份归入 docs/history；当前状态与操作分别归 DEVELOPMENT、模块 README/DEPLOYMENT。
- 根 runs、outputs、看板历史 outputs、同步收发和备份、发布日志迁入 .local；客户数据与市场工作区位置不变。密钥类历史中转材料单独移入 .local/private。
- 共核验 1094 个迁移文件；39 份与保留压缩包逐字节一致的重复源码被清理，其余 1055 个文件内容不变。旧路径未设置别名或兼容软链。
- 两份 Bridge 参考 JSON 原样迁入 tests/fixtures/company_bridge；它们是测试资产，不是业务当前 Bridge 指针。

## 计算与文件完整性

27 份看板/监控计算模块、业务 SQL、规则配置与既有 BI 代码均与迁移前 SHA-256 相同。发布脚本仅修改默认日志目录；所有发布与计算命令保持原样。用户关闭文档后迁移 outputs，Excel/PPT 字节一致，三个 Office 文件均无外部工作簿或本地文件依赖关系。

`sh tools/run_tests.sh`：180 项通过、无跳过（主测试 131、看板 30、监控 19）。Bridge、Casebook、Project Intelligence 定向 58 项通过。Markdown 链接和 shell 语法检查通过。

既有 Project Intelligence 托管进程已用原脚本重载；健康/ready 正常，实际工具返回不再包含 analysis_product 或根 ROLE。没有新增允许目录、服务或凭据权限。

## Grok 边界

本机 grok_workspace 和云端 /home/box/oxhor/grok_workspace 是角色笔记、临时代码和试验工作面。核心模块不依赖其中代码，不默认回灌或打包。现有稳定运行目录和共享代码软链保留；这不是 OS 级安全沙箱。

云端只允许移动已核明自管材料，修改对应路径；SQL、计算、人员目标与例行频率不得改变。无法确认的大包、会话材料和客户数据不在本次云端搬迁范围。

## 证据

本机 `.local/audits/structure-20260918/` 保存迁移映射、前后哈希、重复清理记录、Office 链接检查、测试日志和本机验收摘要。云端回执目标为 `.local/sync/inbox/structure-20260918/`；以最终回执为准，不使用旧路径或口头完成替代验收。
