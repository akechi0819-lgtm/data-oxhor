# 巨量正常授权请求采集

当前整批费用入口为[费用日更入口](dashboard-advertising-costs.md)中的 `prepare_full_daily`。下文是2026-10-29在本机 Desktop main 完成的独立连接器验收记录；固定日期、导出数字和审计目录均属历史回执，不是当前日更窗口。

## 2026-10-29独立连接器验收（历史）

专用正常HTTPS登录→保存本机专用状态→关闭浏览器→独立Python请求7个已确认账户。未绑定旧扩展或访问被拒的bytedance自定义主机；没有读取普通Chrome数据库、更改调试端口或安全权限。

真实原生导出协议是POST `/api/lamp/pc/v2/statistics/data/statQuery?advid=<账户>`。网页查询完整数据后在本地Blob生成XLSX，没有创建/轮询服务端导出任务。实际观察的PageParams是Limit=1000、Offset=0、IsDownload=false。网页明细v3接口的10条分页在同日同费用排序行间实测重复，已停止将其用于全量导出；没有增加猜测的排序字段。

脚本保留平台响应JSON为权威原件，另生成 `api-projection.xlsx` 供现行18列解析器读取。该文件明确标注为API投影，不能冒称网页下载原件。9/1—10/27的7账户投影与各自原生XLSX逐自然键、金额完全相同；6个非空账户1829条406416.25元，一个原生空账户。9/1—10/28新请求1858条416158.52元，7个账户总计约5秒，不启浏览器。

```sh
python3 -m data_acquisition.connectors.advertising.ocean_requests \
  --workspace customers/shadow_bi_daily \
  --start 2026-09-01 --through 2026-10-28 \
  --output-dir .local/audits/full-daily-20261029-simulation/ocean
```

以上目录已存在，禁止再次创建或覆盖；新采集使用新的作业目录和真实上海昨日。已验证数据不能把固定历史截止日当作每日更新。`--account <已确认ID>`可只验单账户；全7账户成功才生成完整巨量候选片段。

同现有授权机制，优先受保护Cookie/已观察CSRF请求头，仅缺失、明确过期或HTTP401才开一个正常登录窗口并刷新状态一次。403、业务拒绝、超时不触发登录或更换权限。登录恢复代码有隔离验证；真实过期恢复尚未实测。状态仅位于工作区 `data_acquisition/storage/auth_sessions/ocean/`，目录0700、文件0600，不进入代码或报表日志。

现原生单次取数上限1000；超过此已观察范围会阻断，不猜分页。重复自然键、窗口外记录、原始金额总和不符、账户新出现费用但未有业务映射均阻断。根verification、逐账户verification及原始JSON一同进入候选冻结，正式来源清单不变。

实际登录列表还有1880190728515692（天津国际_有道智为_天津校区01）。本轮已正常请求封存返回，9/1—10/28的TotalCount=0、stat_cost=0；业务组未确认，单列并排除费用候选，不伪造业务归属。1813785787039897亦保持原未映射空账户，不给它虚构语培组。

证据：`.local/audits/ocean-http-20261029-seven-accounts-native-export/component-validation.json`；`.local/audits/full-daily-20261029-simulation/ocean/verification.json`、candidate-validation.json、capture.json。当前整批流程见[完整日更说明](archive/shadow-bi-full-daily-20261028.md)。
