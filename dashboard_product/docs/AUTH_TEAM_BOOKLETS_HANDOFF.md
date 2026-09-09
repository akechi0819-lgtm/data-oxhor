# 看板账号与板块分册 · 验收合同（派牛马力工）
状态：用户交密码本并点名施工（2026-09-07）  
定合同/验收：许家印  
施工：牛马力工（grok build）  
许家印不施工、不贴密码。

## 真源密码本（C 层）
- 本机用户交：`/Users/akechi/Desktop/工作簿4.xlsx`
- 云侧副本（600）：`dashboard_product/deploy/secrets/password-book-20260907.xlsx`
- 列：用户名 / 密码 / 权限。密码只从该文件读，**禁止贴聊天、禁止进公开仓、禁止写进 RUN 明文**。

## 权限语义（用户纠正）
权限按**团队板块**切，不按业务组（留学预备/高中/大学）。

| 密码本「权限」 | 对应现有 team_id | 分册建议文件 |
|---|---|---|
| `all` | 全部团队 | `full.html` |
| `虚拟人` | `online_private`（线上私域/虚拟人团队） | `xuniren.html` 或 `online_private.html` |
| `平台` | `online_platform`（线上平台） | `pingtai.html` 或 `online_platform.html` |
| `线下`（本表未出现，预留） | `offline_market` | `xianxia.html` / `offline_market.html` |

本表账户（脱敏）：
- `shaoyifan` → 权限 `all` → 分册 `full`
- `chenyue` → 权限 `虚拟人` → 分册 `online_private`
- `sunyue` → 权限 `平台` → 分册 `online_platform`
- `yangxu` → 权限 `all` → 分册 `full`
- `liumingzhi` → 权限 `all` → 分册 `full`
- `qinzhenxu` → 权限 `all` → 分册 `full`
- `zhangyuqing` → 权限 `all` → 分册 `full`

## 相对当时现状的变化（2026-09-07 已完成）
当时线上分册是按业务组：`full/liuxue/gaozhong/daxue` + 旧演示账号。  
已改为按团队板块裁剪 artifact 再渲染。旧业务组分册已从运行时、发布白名单和 Nginx 删除，不再保留兼容入口。  
`market_total`：仅 `full`/`all` 可见；板块分册不含市场总计（避免拼出全量）。

## 施工要点
1. 用密码本重建 htpasswd + user→booklet map（替换 demo 账号 admin/liuxue/… 或并存策略在 RUN 写清；默认以密码本为准，移除未在密码本的演示号）。
2. render/publish：refresh 一次 → 按团队板块渲分册 → 批量上传；更新 Nginx map 与 location 白名单。
3. 日更脚本与 AUTH_BOOKLETS_RUN / 许家印例程若路径名变更，同步改文档（许家印可随后改例程文案）。
4. 安装后自检：各用户登录只见本板块数据；跨册 403；anon 401；healthz 200；密码不进日志。

## 验收清单
1. 密码本 7 人均可登录对应分册。
2. `虚拟人` 账号页面数据仅含 `online_private`（无线下/平台团队汇总与人员）。
3. `平台` 账号仅含 `online_platform`。
4. `all` 账号可开 full（含各团队）。
5. 跨板块路径 403；匿名打不开全量；artifact.json 不公网。
6. secrets/htpasswd/map 权限正确；密码本仍在 secrets 且未进 Git。
