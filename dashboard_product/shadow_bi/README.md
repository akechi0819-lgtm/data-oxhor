# 影子 BI：P1 本地技术验证

这是隔离实验，不是新生产看板。阶段结论与真实缺口见 [P1 验证记录](../../docs/shadow-bi-p1-validation-20261022.md)。没有修改旧看板规则或客户 Snapshot。

- `build_projection.py`：只读 P0 的 `shared_result.json` / `details.json`，建立独立 DuckDB 投影，拒绝覆盖已有库。
- `bootstrap.py`：创建专用 Superset 数据源、8 个代表图表及独立控件，拒绝覆盖已有 dashboard。人员四态来自 P0 已计算视图，两个原生筛选列只拆分状态编码；P2 尚未整理规则。
- `activity.html` / `extension.py`：唯一补充交互组件，只调用 Superset 原生查询 API，临时投入留在标签页 `sessionStorage`，没有写回接口。后者还记录本地私有请求证据，不记录 Cookie/认证头。
- `verify_api.py`：向实际运行服务发出23次查询并断言分页、独立人数、日期金额、窗口及状态。
- `verify_evidence.py`：核对保存的实际请求/页面观察及 P0 摘要，只写自己的验证结果。
- `superset_config.py`：只供 loopback 实验。SQLite 元数据库、内存缓存和开发 Web 服务不能作为生产部署方案；P4另验权限、文件隔离和稳定运行。

## 当前环境启动

以下命令必须在指定工作树 `/Users/akechi/.codex/worktrees/c373/manager -CowH` 执行。凭据仅在私有 runtime 内，不进入文档、Git 或命令参数。

```bash
export SUPERSET_CONFIG_PATH="$PWD/dashboard_product/shadow_bi/superset_config.py"
export SUPERSET_HOME="$PWD/.local/audits/shadow-bi-p1-20261022/runtime/home"
export FLASK_APP=superset
.local/audits/shadow-bi-p1-20261022/runtime/venv/bin/superset run --host 127.0.0.1 -p 18088 --with-threads
```

原生页：`http://127.0.0.1:18088/superset/dashboard/shadow-bi-p1/`；活动组件：`http://127.0.0.1:18088/p1/activity/`。已登录浏览器可直接查看。服务用 Ctrl+C 停止；不重启任何旧服务。

## 从空 P1 环境复现

保留现有证据；只在明确的新实验目录/副本中重建，不删除当前环境来重跑。需要本项目 P0 原样封存输出，Python 3.11，以及 uv。项目核心 Python 环境不参与安装。

```bash
python3 dashboard_product/shadow_bi/initialize.py
uv venv --python 3.11 .local/audits/shadow-bi-p1-20261022/runtime/venv
uv pip sync --python .local/audits/shadow-bi-p1-20261022/runtime/venv/bin/python dashboard_product/shadow_bi/requirements-p1.lock
# 设置上节三个环境变量后：
.local/audits/shadow-bi-p1-20261022/runtime/venv/bin/superset db upgrade
.local/audits/shadow-bi-p1-20261022/runtime/venv/bin/superset init
.local/audits/shadow-bi-p1-20261022/runtime/venv/bin/python dashboard_product/shadow_bi/build_projection.py
.local/audits/shadow-bi-p1-20261022/runtime/venv/bin/python dashboard_product/shadow_bi/bootstrap.py
```

启动服务后运行 `.../venv/bin/python dashboard_product/shadow_bi/verify_api.py`。重跑API结果写入新的 `evidence/api-runs/<UTC时间>/`，不覆盖已验收的 `api-final/`。UI证据必须重新真实操作获取，验证脚本不会生成浏览器成功回执。`verify_evidence.py` 需要施工保存的 P0-before 和实际 UI 文件，不能凭新建空环境宣称它通过。

官方来源：[Superset PyPI 安装](https://superset.apache.org/user-docs/6.0.0/installation/pypi/)、[6.1.0 发布包](https://pypi.org/project/apache-superset/6.1.0/)、[6.1.0 官方依赖锁](https://github.com/apache/superset/blob/6.1.0/requirements/base.txt)。`requirements-p1.lock` 固定本次实际安装的完整组合；上游代码保留在安装包及 Apache 许可证内，项目没有修改上游 Superset 源码。
