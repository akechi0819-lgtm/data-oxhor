# 10月26日通知触发与控制回执修复

## 实证来源

正式版daily-20261026_094052和10:00:10先启动的通知，均来自用户手动线程“刷新今日看板和腾讯文档”（01a172aa-0235-7912-bf25-9ab5032d028a）。用户先说“你再刷新一次今天的”，后说“钉钉推送是不是也可以一块做了”。该线程的命令记录分别为exec-6422bfe1-1171-4423-90d5-c4c2cea890e0（Mac p5.daily）及exec-7e28398e-0591-459e-84cb-72ca8f1356e5（SSH固定send-scheduled入口）。本地manual审计日志与服务端10:00:10–10:02:45的通知子服务、8条sent状态一致，固定入口退出0、deduplicated=0。

不是bi-2自动发通知：其prompt明确禁止钉钉，10/26 heartbeat在01:43:07Z因本地代理认证401失败，未产生执行命令。bi-2仍ACTIVE，属于未来看板日更潜在生产者；本线程不停止它。上述手动线程已完成、不是新增定时源。父线程应统一手动与Dot调用时机，不因这次通知重叠误停日更。

## 9cbbb2…原unknown

HTTP job9cbbb2f9bcd6ea474083bd2e694fa291ae262d68adacc1fb732899df71af54e6在10:00:49调度，约0.1秒结束，无新的通知子服务；此前发送仍在运行。旧worker只要调用执行器后发生异常就置network_send_attempted=true，且未保存子进程exitcode，故原job的确切异常无法补造。时间线符合互斥拒绝，但不能把75当原始已记录返回码。

DeliveryState八项全部sent，10:02:35–10:02:45，含资源hash和delivery确认，无pending/sending/unknown/untouched。原transport仅在钉钉errcode=0时记录sent，原始HTTP响应体未保存。不得重发或清state。

## 本次最小修复（不调用真实发送）

- worker在解析结果前保存每次执行器returncode、固定JSON摘要、stdout/stderr摘要和错误类型；不保存或输出凭据、URL、消息内容。Timeout等确有不确定性的情形仍unknown且不重放。
- 固定shell的75只代表入口锁忙，明确blocked、network_send_attempted=false；内部run锁忙也返回绑定请求身份的固定busy报告。允许现有有界显式retry，不新增自动重试或定时。
- 全部deduplicated的已sent结果不再声称有新的HTTP发送。
- 单独no-send对账程序只读当前正式身份及8条同源sent/资源确认，生成notify-control/reconciliations/<job>.json；原results/<job>.json和DeliveryState字节均不变。GET原job保留status=unknown、retryable=false，只附delivery_reconciliation。该附加回执说明通知已由先前执行完成，不伪称本HTTP job发送成功。
- 原群、凭据、时间门禁、业务内容和发送函数不改；没有新的发送操作或权限。

## 发布施工停点

固定raw publish能力提交ab33cee7已部署，774项完整回归及实际权限/负例验证通过；尚无Dot新三Excel包prepared后正式发布。09:54的现网变化是上述Mac手动流程，不算Dot脱机更新。Mac直接SSH日更不受receiver publisher锁保护，正式Dot发布窗仍需父协调唯一生产者。两处旧computed/workspace约4.90GiB可释放，先保留质量、指标、manifest/hash、输入绑定与日志；本线程未删。

本次修复的测试覆盖忙锁不误报发送、真实不确定结果不重放、错误码脱敏持久化、对账拒绝非sent/错批次/错Snapshot/错日期/资源不一致，以及GET不覆盖原unknown。真实修复验收只运行对账，不运行preview、send-scheduled或任何渲染发送入口。

## 实际修复验收

完整回归787 passed、10 skipped、198 subtests；10项仍为9个可选MCP协议依赖和1个锁定Superset认证模块。专项66 passed、20 subtests。部署仅在通知entry/dispatch锁空闲、通知服务inactive且队列为空时进行；通知服务没有重启，没有调用preview/send-scheduled。新控制代码位于`/srv/shadow-bi-notify/releases/a5c44ce258756a16251ed1a8e957cfbc140cf561`。

10:28:41执行独立no-send对账：原unknown结果SHA256仍为829dd04688034b88d9c31305f72975f905b4fbdc030918e27c990339ef349b0a，DeliveryState SHA256仍为97debc0a297c597e26316716c5d2de560859c19736598d3c6670981e2d8e7346，BI current仍daily-20261026_094052。已有HTTP身份实读附加回执成功。GET原job仍status=unknown/retryable=false，并增加delivery_reconciliation.delivery_status=sent、message_status_counts.sent=8、no_send_performed=true；不代表该HTTP job自身进行了发送。

对账回执在notify-control/reconciliations/9cbbb2f9bcd6ea474083bd2e694fa291ae262d68adacc1fb732899df71af54e6.json；原results同名文件未覆盖，另留原unknown只读审计副本。root部署/不变性证据在warehouse-validation/notify-control-repair-20261026-task4/deploy-result.json；本机任务4同名部署结果及manual-notify-origin-20261026.json记录完整来源链。
