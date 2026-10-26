# 正式 BI 看板

正式用户界面为 Superset 原生看板，见[正式入口](https://dashboard.apinova.cn/superset/dashboard/shadow-bi-native/?standalone=1)。首页及原四个 HTML 入口跳转新版，18个原账号沿用原密码和已授权只读范围。

当前代码入口：

- 日更：`python3 -m dashboard_product.shadow_bi.p5.daily --workspace customers/shadow_bi_daily`。此命令会采集和发布，不能当作只读检查。
- 共同业务计算：`management/calculation.py`；业务库构建：`shadow_bi/library.py`；原生投影：`shadow_bi/p3/build_projection.py`；页面与原生数据集：`shadow_bi/p35/`。
- 服务器：`shadow_bi/p4/`，现行仅从封存表重建业务 DuckDB；完整原始历史仓与计算迁到服务器的工作已暂停，不能声称已完成。
- HTTPS接收与固定发布worker：`shadow_bi/p5/receiver.py`、`shadow_bi/p5/deploy/`；固定raw三Excel接收、受限计算和root发布已另有部署回执，真实raw新包正式发布仍待验收，见[raw合同](../docs/server-raw-pipeline-contract.md)。
- 本地来源完整性门禁：计算预检、候选封口/复用及固定发布前复核同一受保护证明；无证明不构建，变化不发布。见[完整性合同](../docs/server-source-completion-candidate.md)。这轮只在本地整合，尚未部署，也未切换唯一生产者。

`shadow_bi`、`p3`、`p35` 等保留为稳定导入和部署路径；名称不再表示等待上线的实验版本。旧P1/P3试验说明只用于复现历史。

`management.build` 和静态模板保留为共同计算、通知及恢复兼容入口。`run_management_daily.sh` 默认只生成同批通知所需结果和指针，不再自动发布静态网页；旧静态发布/激活命令在非dry-run时要求显式恢复开关。外部Grok是否已安装此版本、任务是否已切换，须现场核对，Git合并不代表任务接管。

当前运行与恢复见[部署说明](DEPLOYMENT.md)，本地整合与测试见[10月26日收口记录](../docs/local-project-alignment-20261026.md)；[10月25日正式基线](../docs/bi-production-baseline-20261025.md)保留当时证据。旧静态说明归档于`docs/history/dashboard/static-*-through-20261025.md`，不再作为当前发布流程。
