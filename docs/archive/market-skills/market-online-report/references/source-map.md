# 来源导航与复用边界

路径均相对市场工作区，身份与当前快照以本次 `./oxhor status` 为准。这里的旧证据只帮助定位和复现，不能回答下一期当前数字。

## 受控接口

- `INTERFACES.md`：describe、query等参数；SQL及回执进入独立Evidence目录。
- 语培工单与现金结构：用当前describe发现关系，不猜新表名。历史关系为 `landing.br_work_orders__sheet_1f0596db9f25`、`landing.br_cash__sheet_39b8dee2e4b3`。
- 留学独立当前指针：绑定数据工作区的 `Work/StudyAbroad/current.json`。使用现有Data Platform受控服务及显式snapshot/run，不直接连接其warehouse文件。
- 留学资源表历史关系：`landing.study_abroad_market__resources`，归属条线 `business_line`。`study_abroad_facts` 的国家映射line不是完整业务条线替代，曾遗漏中外合作办学。
- 学术中心签约需核查contracts的日期、资源ID、合同关联及去重；不能因资源数量0直接填签约0。

## 素材与反馈

腾讯文档：`https://docs.qq.com/sheet/DVHN6SHNaRW94cndC`，只读。

- 内容产出流水 `df815v`：素材ID、业务板块、产品／人群、内容主题／标题、内容用途、交付日期。
- 数据反馈流水 `fpkxtp`：素材ID、平台、内容用途、消耗费用、工单量、所属项目。
- 工单反馈明细 `0apMZH`：ID、录入日期、重点资源意向、工单跟进情况、素材ID、渠道／顾问等。
- 表内业务说明和表头不一定在第1行，读取时确认实际表头；未编号业务行不能丢弃。不要把现在的状态或累计值冒称统计截止日的历史快照。

## SEM费用

从正式 `Input/AdvertisingCosts/sources.json` 读取明确文件及哈希，检查原文件日期。曾发现声明结束日期更新了但仍指向10月表。11月在线表是独立文档，不能通过旧文件推断当月没有费用。

2026年11月只读核对入口：`https://alidocs.dingtalk.com/i/nodes/2Amq4vjg89gqYOOdTYwb6yExV3kdP0wQ`。后续周期按实际表名和目录确认，不能盲用本链接代表新月份。GEO费用当时无明确标签，仍需实际对应关系。

## 本轮已确认交付与旧程序

- 最终图片/HTML/TXT：`Reports/各项目线上产出周报_20261101-1113/`。以去掉制作状态后的版本为样式参考。
- `Programs/weekly_project_reports/build.py`、`render.py` 是本期复现程序，硬编码旧日期/来源，不是通用数据刷新器。先为新期生成独立配置和证据，再复用计算与排版；不能直接运行旧程序冒称已重跑新期。
- 本轮主要证据：`Evidence/run_weekly_template_20261115_01/`、`Evidence/run_geo_abroad_20261115_01/`、`Evidence/run_academic_line_values_20261115_01/`、`Evidence/run_academic_line_dates_20261115_01/`。
- 不把客户工单、手机号、整包原始数据复制进Skill；只保存规则、结构、样式与来源路径。
