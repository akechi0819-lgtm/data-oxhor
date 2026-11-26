# 路径与授权边界

以下均相对本目录解析；当前绝对根目录为 `/Users/akechi/Desktop/manager -CowH/market_workspace`。市场数据只读绑定到主目录正式数仓 `/Users/akechi/Desktop/manager -CowH/customers/shadow_bi_daily/`。本表定义 Agent 的任务范围，不能替代宿主沙箱或 OS 权限。

| 路径 | 允许操作 | 说明 |
|---|---|---|
| `Programs/`、`Scratch/` | 按任务读写、清理 | 生成程序、依赖环境、临时脚本放各自任务子目录 |
| `Reports/`、`Evidence/`、`Notes/` | 按任务读写 | 正式成果、证据、参考资料，不自动批量删除 |
| `/Users/akechi/Desktop/manager -CowH/customers/shadow_bi_daily/Work/workspace.json` | 只读 | 正式数仓的数据身份和当前 Snapshot 指针的唯一来源 |
| `/Users/akechi/Desktop/manager -CowH/customers/shadow_bi_daily/Input/` | 按需只读 | 不修改源文件，不将整目录读入上下文 |
| `/Users/akechi/Desktop/manager -CowH/customers/shadow_bi_daily/Input/Reference/留学板块-官方记分卡.md`、`/Users/akechi/Desktop/manager -CowH/customers/shadow_bi_daily/Input/Reference/留学板块-官方记分卡.json` | 只读 | 官方业务确认事实；不修改、不入仓、不写入 Bridge |
| `/Users/akechi/Desktop/manager -CowH/customers/shadow_bi_daily/Work/Runs/` | 仅受控查询 | 不直接连接 DuckDB，不扫描历史运行猜状态 |
| `/Users/akechi/Desktop/manager -CowH/customers/shadow_bi_daily/Work/SavedQueries/` | 执行明确 ID/版本的已确认查询 | 不修改或晋升 SQL |
| `/Users/akechi/Desktop/manager -CowH/customers/shadow_bi_daily/Output/Dashboard/` | 按明确 run_id 只读 | 只用于核对，不按修改时间选产物 |
| `../workspace_modeling/operations/` | 按需只读 | 共享人员规则与花名册，不直接编辑 |
| `../interfaces/`、`../data_platform/`、`../workspace_modeling/`、`../.venv/` | 读取和调用现有工具 | 不在市场自由编辑中改核心实现或安装依赖到共享 venv |
| `../.agents/skills/biz-analysis/SKILL.md` | 按需读取 | 自由分析流程 |
| `../dashboard_product/`、`../monitoring_product/` | 必要时只读定位 | 无刷新、发布、推送授权 |
| 各 `.env`、登录态、云端密钥、其他工作区 | 默认不访问 | 不因“能读到”视为已授权 |

需要修改共享模块、刷新数仓或发送消息时，按用户明确的新任务范围处理。本入口不包含初始化、导入、发布、案例写入或推送命令。
