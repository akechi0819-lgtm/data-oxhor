# 原始Excel服务器候选验证回执（2026-10-25）

结论：候选已到`prepared`，`published:false`。这不是生产自动链路上线；生产current始终为`daily-20261025_184644t`。raw HTTP路由未注册，没有扩大token、服务账号、目录ACL或通知权限，没有修改Mac bi-2/Grok任务。

## 实际链路与对账

候选根：`/var/lib/shadow-bi/warehouse-validation/raw-pipeline-20261025-task4`。使用服务器已有明确三Excel组包/接收，复用原BI六个月合并及腾讯当月替换，生成新的不可变双Snapshot、通过联合配对与受控quality门禁，执行共同计算、39表JSONL及typed业务库。来源基线与接收原件最后再验hash保持不变。

首轮入仓604.303秒，随后因过长业务run_id被原校验拒绝，未误记成功。修正为有后缀空间的短ID后，显式复用已通过双源回执的Snapshot续算，**没有重复导入**；计算及39表封存529.525秒。严格原参考对账正确阻断来源身份变化；独立证据闭合后通过`raw_compute recheck`仅复验现有产物，不重新构建。

完整39表核对结果：

- 25表完整逻辑摘要与原参考直接相同。
- 13表只存在明确的`source_sha256`、`snapshot_id`、`ingest_batch_id`旧值→新值变化，包括JSON字符串嵌套的同一字段。通过受控业务库查询比较完整行SHA256及重复次数，未删列、未抽样代替全量。
- 余下`scoped_team_periods`只有`主动/Q1/total`一行的21个`grades_by_line.training[*].cash_share`浮点末位差，最大`2.7755575615628914e-17`。对应各年级现金及其精确十进制合计完全相同；旧/新所有比例分别由相差1个ULP的共同浮点分母**逐项精确重现**。源代码`breakdowns._grade_rows`按插入顺序对浮点分母求和，解释了差异；未改公式。四位百分比小数显示相同。该21项逐项记录，并非使用通用误差容忍隐藏未知字段。
- 以上明确变化后，全部行hash与重复次数一致，其他业务字段无差异；612项关键实际指标严格相同，39表物理行数与文件hash通过。不能把此结论改写成“原39表未经任何身份调整即字节完全相同”。

证据：候选根的`provenance-proof-final.json`、`provenance-replayed-reference-final.json`、`comparison-evidence/`、`provenance-evidence/`及`computed/raw-20261025-task4a/prepared.json`。原参考和失败回执均保留，没有改写。

## 内存、失败恢复与界限

实际封存cgroup峰值3,221,225,472 bytes（达到3GiB配额），最大进程RSS2,205,704 KiB（约2.10GiB）。systemd为普通`exit-code`、退出码1；完整39表写完后明确在参考比较处抛出异常，内核日志无OOM记录，非OOM/截断冒充成功。已退出cgroup的`memory.events`没有被保存，不能伪报其计数为0。3GiB内含文件缓存，正式服务仍需保持限额和空间预检。

真实进程组超时测试使用合成小Excel，将业务worker替换为休眠进程：约1.002秒后终止，状态`timed_out`且current不变。

隔离P4演练复用现有`p4.activate`：在候选文件系统命名空间进行真实current软链切换、注入烟测失败、恢复当时旧current，再成功切候选；旧/新业务库均通过真实受控查询验证批次。生产systemctl、页眉刷新和HTTP烟测被mock，未重启生产服务；**没有验证独立完整Superset实例的服务重启/浏览器/UI烟测**。该限制必须保留，不能称生产切换已演练完成。回执为`rollback-rehearsal.json`。

仅保最新策略：生产发布仍未接线；必须先验收新版本、原子切current及真实应用烟测成功，再按明确无引用清单清理旧成品。失败保住当时current，不假称已经删除的历史previous可回滚。原始历史、通知资产/状态和日志不进入成品清理。

## 测试覆盖

共享c373工作树完整回归：**711 passed、10 skipped、198 subtests passed**。新输入合同、路径/ZIP/体积/hash/双源/日期、幂等、失败/超时、短ID、恢复门禁与默认不注册raw路由均覆盖。原采集和业务库、看板与通知回归保持。

10个skip具体为：缺少可选`mcp==2.2.0`的9个Project Intelligence协议测试，以及未在固定Superset环境执行的认证测试模块1项；没有把skip算成通过。

另专跑既有通知合同、receiver HTTP、shared_delivery、release_notifications与成品receiver，连同上述skip核查：**60 passed、10 skipped、26 subtests passed**。通知请求校验、同批约束、状态/去重/失败恢复、预览与发送边界均保留回归；外部发送为mock，未发钉钉。未覆盖真实通知再次发送、真实raw HTTPS安装/鉴权扩展、固定队列consumer上线、唯一生产者切换或完整隔离Superset UI验收。

候选源码与本次生产计算版本分别留有明确hash；封存时实际运行的源码保存在候选根`sealed-build-source-v2`，后续recheck工具版本不冒充当时计算版本。权限差异与未部署能力见[输入合同](server-raw-pipeline-contract.md)。
