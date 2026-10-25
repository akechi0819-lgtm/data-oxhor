# 正式 BI 看板

正式用户界面为 Superset 原生看板，入口 https://dashboard.apinova.cn/superset/dashboard/shadow-bi-native/?standalone=1 。首页及原四个 HTML 入口跳转新版，18个原账号沿用原密码和已授权只读范围。

当前代码入口：

- 日更：`python3 -m dashboard_product.shadow_bi.p5.daily --workspace customers/shadow_bi_daily`。此命令会采集和发布，不能当作只读检查。
- 共同业务计算：`management/calculation.py`；业务库构建：`shadow_bi/library.py`；原生投影：`shadow_bi/p3/build_projection.py`；页面与原生数据集：`shadow_bi/p35/`。
- 服务器：`shadow_bi/p4/`，现行仅从封存表重建业务 DuckDB；完整原始历史仓与计算迁到服务器的工作已暂停，不能声称已完成。
- HTTPS接收与固定发布worker：`shadow_bi/p5/receiver.py`、`shadow_bi/p5/deploy/`；只接收现行成品表合同，未改为原始导出合同。

`shadow_bi`、`p3`、`p35` 等保留为稳定导入和部署路径；名称不再表示等待上线的实验版本。旧P1/P3试验说明只用于复现历史。

`management.build` 和静态模板保留为共同计算、通知及恢复兼容入口。`run_management_daily.sh` 默认只生成同批通知所需结果和指针，不再自动发布静态网页；旧静态发布/激活命令在非dry-run时要求显式恢复开关。外部Grok是否已安装此版本、任务是否已切换，须现场核对，Git合并不代表任务接管。

当前运行与恢复见[部署说明](DEPLOYMENT.md)，合并、口径清理及未完成项见[正式基线](../docs/bi-production-baseline-20261025.md)。旧静态说明归档于`docs/history/dashboard/static-*-through-20261025.md`，不再作为当前发布流程。
