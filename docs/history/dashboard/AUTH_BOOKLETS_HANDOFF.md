> 历史存档：原路径 `dashboard_product/docs/AUTH_BOOKLETS_HANDOFF.md`，于 2026-09-18 目录整理时归档。以下状态、命令、版本与凭据配置描述仅代表记录当时，不是当前操作入口。当前项目状态见 [DEVELOPMENT.md](../../../DEVELOPMENT.md)；看板现行操作见 [DEPLOYMENT.md](../../../dashboard_product/DEPLOYMENT.md)。

> **已过时（2026-09-07 后）**：业务组分册 `liuxue/gaozhong/daxue` 已下线。当前按团队板块裁剪，合同见 [`AUTH_TEAM_BOOKLETS_HANDOFF.md`](AUTH_TEAM_BOOKLETS_HANDOFF.md)，运行见 [`AUTH_TEAM_BOOKLETS_RUN.md`](AUTH_TEAM_BOOKLETS_RUN.md)。下文只保留当时拍板记录，不再作为日更口径。

# 看板授权升级 · 分册 HTML + htpasswd（验收合同）

状态：用户拍板 A（2026-09-07）
定合同/验收：许家印
施工：牛马力工（用 grok build 写代码与联调）
传话/验收协调：赵高

许家印本轮**不**改服务器、不写实现代码、不直接调发布脚本做本需求。

## 目标
- 公网不再匿名打开全量看板。
- 按业务组预渲染分册 HTML；账号用 htpasswd 发放，映射到对应分册。
- 不做自助邀请码注册页、不做小网关、不做 SSO。

## 分册
日更仍 `refresh` 一次全量 `artifact.json`，再多份 `render`（服务端裁进页面，禁止只藏 tab）：

| 文件 | 范围 |
|---|---|
| `full.html` | 全团队 + 全业务组（仅管理员账号） |
| `liuxue.html` | 业务组=留学预备 |
| `gaozhong.html` | 业务组=高中 |
| `daxue.html` | 业务组=大学 |

路径建议：`/var/www/dashboard/` 下上述文件；匿名 `/` 不得落到全量。

## 门口
- Nginx `auth_basic` + `htpasswd`（C 层，mode 600，不进公开仓、不贴聊天）。
- 用户名 → 允许访问的分册（可用 `map` 或分 location）。
- 「邀请」= 人工发账号+初始密码；不做自助注册。

## 日更
- 顺序保持：仓更新后 → refresh → 多 render → 批量上传分册。
- `/healthz` 仍可匿名 200。
- 失败不覆盖上一成功分册。

## 红线
- 全量 `artifact.json` 不进公网目录。
- 不改 saved query / 指标口径。
- 遵守 `/home/box/oxhor/SYNC.md` §5；密钥单独通道。
- 建议顺带上 TLS（HTTP + basic auth 会裸奔密码）；若本轮不做 TLS，须在交付说明里写明风险。

## 验收清单
1. 未登录访问业务页 → 401/登录框；看不到全量数。
2. 高中账号只能打开 `gaozhong` 对应内容；页面源码无大学/留学预备汇总与明细。
3. 大学、留学预备账号同理。
4. 管理员账号可开 `full`。
5. 日更脚本能一次产出并上传四分册；`healthz` 正常。
6. htpasswd/映射文件权限正确，未进公开 Git。

## 参考现状
- 代码：`/home/box/oxhor/dashboard/dashboard_product/`（`render_template.py` / `refresh.py` / `deploy/`）
- 现网：`http://dashboard.apinova.cn`，Nginx 现为单文件 `current.html`
- 服务器与 `.env.server`：施工方可自行在云目录与部署说明中查看，勿把密码贴回聊天
