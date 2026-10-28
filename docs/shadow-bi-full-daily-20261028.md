# 完整日更接入状态（2026-10-28）

用户指定每天 Asia/Shanghai 09:30、所有可获取来源更新后统一发布。腾讯广告语培是已确认待接入项；腾讯留学不能据旧失败记录排除。SEM通常前一日18:00更新，但整月预置零不能证明昨日已完成。

## 本轮代码范围

`dashboard_product.shadow_bi.p5.full_daily` 是待接入下载器的批次验收/计算/发布入口，尚不是已完成的自动采集器。它接收宿主本次实际下载的广告捕获清单，复用现有广告解析、双仓采集及 `p5.daily` 的构建、发布和验版。没有本次捕获回执时返回 blocked，不能拿旧输入冒充采集完成。

现有命令 `python3 -u -m dashboard_product.shadow_bi.p5.daily --workspace customers/shadow_bi_daily` 默认行为保持原样，不自动刷新广告、不发送通知。

候选完整命令（必须已有本次真实捕获；不是当前可直接无人值守的命令）：

```bash
python3 -u -m dashboard_product.shadow_bi.p5.full_daily \
  --workspace customers/shadow_bi_daily \
  --capture-receipt /absolute/path/to/current-capture.json
```

该命令会先取得与旧日更相同的生产锁。独立 `.private/full-daily-sources.json` 的 `expected_sources` 指定必要来源、账户、窗口及解析来源ID；本轮没有在客户工作区创建生产配置。回执中的来源集合必须与它一致，已知腾讯广告语培缺口不按零、不作为必要来源。

捕获清单包含 `manifest_path`、`sources`。每来源必须声明 `source_id/status/captured_at/start_date/through_date/account_ids/files/evidence/completion`；原件及证据逐份绑定SHA256。时间必须带时区且为上海当天，范围截至昨日；密集账户日报/SEM逐配置账户或叶表核对每天；项目日报仍保留稀疏原始行，不补造零。SEM还要求来源自身完成标志，不能以下载时刻或一般填报时点代替。

成功解析后才会刷新业务双仓；同批输入、来源身份、当前费用清单及显式计算源码在上传与切换前复核。相同真实输入仅复查已发布版本；同日费用或业务字节改变允许新批次。失败会保留回执，尚未发布则不改变线上current；若发布请求结果不确定，回执明确记录uncertain，必须核对服务器后续跑，不盲目重发。

## 尚未完成，禁止按测试成功启用定时

- 抖音、小红书、SEM、腾讯留学的真实跨日下载器尚未接入该命令；本轮未构造或伪造捕获回执。
- 10月28日核实Chrome腾讯营销及小红书星火均停在正常登录页，已请求用户完成登录；腾讯页面的微信快捷登录尝试仍等待平台完成。留学账户74749810新原件尚未取得，尚不能新增腾讯解析或确定其与旧微信/腾讯费用替代关系。
- 原业务线程仍占有生产锁、双仓批次 `run_shadow_daily_20261028_104710` passed，正计算发布；未并发启动完整日更。
- 本环境是durable线程，本机automation工具不支持；CUA也明确拒绝操作Codex应用，不绕过。需要local项目线程实读bi-2及相关任务，再在真实完整日更验收成功后收口为唯一09:30任务。表格ID同步、17:50巡检不动。当前未创建、启用或修改任何任务，不能承诺10月29日已安排。
- 不恢复Dot/raw及Dot钉钉任务，不发送钉钉/微信，不新建凭据或持续访问。

隔离测试使用临时文件和真实小红书解析器，采集/发布替身；通过不代表真实采集、服务器发布或定时触发通过。
