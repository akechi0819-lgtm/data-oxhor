# 影子 BI：P1 本地技术验证（历史索引）

P1 是早期隔离实验，不是当前原生 BI 产品或生产入口。阶段结论、证据与限制见 [P1 验证记录](../../docs/archive/shadow-bi-p1-validation-20261022.md)；当前部署、发布与恢复入口见[正式 BI 部署说明](../DEPLOYMENT.md)。

P1 实验代码已从当前 `main` 清理。若需复现当时的本地验证，必须从清理前提交 `c0f43e8f` 取得源码，并按该提交对应的阶段回执准备隔离环境；此页不再提供旧启动命令、端口或环境路径。保留的 `requirements-p1*.txt` / `requirements-p1*.lock` 文件仍供当前 P4 环境依赖使用，不表示 P1 实验服务仍可按旧说明启动。

P1 当时验证了只读业务投影、Superset 原生页面交互和受控 API/页面证据；它使用独立本地实验配置，不修改旧看板规则或客户 Snapshot。后续原生工作台验证见 [P3.5 原生验收记录](../../docs/archive/shadow-bi-p35-native-validation-20261023.md)，生产产品和服务器职责以[部署说明](../DEPLOYMENT.md)为准。
