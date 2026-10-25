# 正式原生 BI 模块

本模块已作为正式BI代码基线，`shadow_bi`名称与P3/P3.5/P4/P5路径保留以兼容现有服务和导入。P1实验启动与历史复现说明见[README-P1](README-P1.md)，不用于生产安装。

正式入口、发布合同、回滚及调度边界见[部署说明](../DEPLOYMENT.md)。`library.py`复用`management/calculation.py`进行业务计算；`p3/build_projection.py`和`p35/`服务现有原生界面；`p4/`负责服务器封存表装载与原子切版；`p5/daily.py`负责现行日更。

HTTPS receiver和固定root发布worker源码已按现网原件收回仓库，分别为`p5/receiver.py`及`p5/deploy/`。本次只归档已部署源码，不安装新版本、不修改权限；状态回执权限缺陷仍列待修。

历史P0—P5验收记录保留，各阶段的“待验收/未上线”只描述当时状态。最新正式决定及未完成项见[正式基线](../../docs/bi-production-baseline-20261025.md)。
