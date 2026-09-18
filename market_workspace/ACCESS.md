# 路径与授权边界

以下均相对本目录解析；当前绝对根目录为 `/Users/akechi/Desktop/manager -CowH/market_workspace`。本表定义 Agent 的任务范围，不能替代宿主沙箱或 OS 权限。

| 路径 | 允许操作 | 说明 |
|---|---|---|
| `Programs/`、`Scratch/` | 按任务读写、清理 | 生成程序、依赖环境、临时脚本放各自任务子目录 |
| `Reports/`、`Evidence/`、`Notes/` | 按任务读写 | 正式成果、证据、参考资料，不自动批量删除 |
| `../customers/bi_operations/Work/workspace.json` | 只读 | 数据身份和当前 Snapshot 指针的唯一来源 |
| 上述配置指向的 Pack、Bridge | 只读 | 经确认的业务口径，接口 status 返回具体路径 |
| `../customers/bi_operations/Input/` | 按需只读 | 不修改源文件，不将整目录读入上下文 |
| `../customers/bi_operations/Work/Runs/` | 仅受控查询 | 不直接连接 DuckDB，不扫描历史运行猜状态 |
| `../customers/bi_operations/Work/SavedQueries/` | 执行明确 ID/版本的已确认查询 | 不修改或晋升 SQL |
| `../customers/bi_operations/Output/Dashboard/` | 按明确 run_id 只读 | 只用于核对，不按修改时间选产物 |
| `../workspace_modeling/operations/` | 按需只读 | 共享人员规则与花名册，不直接编辑 |
| `../interfaces/`、`../data_platform/`、`../workspace_modeling/`、`../.venv/` | 读取和调用现有工具 | 不在市场自由编辑中改核心实现或安装依赖到共享 venv |
| `../agents/ad_hoc_analysis/AGENT.md`、`../.agents/skills/business-analysis-routing/SKILL.md` | 按需读取 | 自由分析流程；不加载整个 agents/skills |
| `../dashboard_product/`、`../monitoring_product/` | 必要时只读定位 | 无刷新、发布、推送授权 |
| 各 `.env`、登录态、云端密钥、其他工作区 | 默认不访问 | 不因“能读到”视为已授权 |

需要修改共享模块、刷新数仓或发送消息时，按用户明确的新任务范围处理。本入口不包含初始化、导入、发布、案例写入或推送命令。
