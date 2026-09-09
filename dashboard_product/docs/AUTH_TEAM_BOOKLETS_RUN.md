# 团队板块分册 HTML + htpasswd · 运行说明

权限按 **team_id 板块** 切，不按业务组（留学预备/高中/大学）。日更仍 `refresh` **一次**全量 `artifact.json`，再 `render` 四分册。全量 JSON **不**上传公网。账号用 htpasswd 发放，不做自助注册。密码只从 C 层密码本读，**禁止贴聊天、禁止进公开仓、禁止写进本文件明文**。

## 路径

| 角色 | 分册 | 权限（密码本） | 文件 |
|---|---|---|---|
| 全量 | `full` | `all` | `/full.html` |
| 虚拟人 | `online_private` | `虚拟人` | `/online_private.html` |
| 平台 | `online_platform` | `平台` | `/online_platform.html` |
| 线下（预留） | `offline_market` | `线下` | `/offline_market.html` |
| 探活 | — | — | `/healthz`（匿名 200） |

板块分册**不含** `market_total`。匿名 `/` 不会落到全量：未登录是 401；已登录只看到自己的分册。跨册路径 403。

旧业务组分册 `liuxue` / `gaozhong` / `daxue` 已从默认 `BOOKLET_IDS`、日更上传和 Nginx 白名单移除。日更不再发布它们。

## 本机 C 层密钥（600，不进 Git、不贴聊天）

密码本（只读）：`dashboard_product/deploy/secrets/password-book-20260907.xlsx`，列：用户名 / 密码 / 权限。

```bash
export PATH=/home/box/oxhor/warehouse/.venv/bin:$PATH
cd /home/box/oxhor/dashboard
python3 dashboard_product/deploy/generate_dashboard_auth.py --force
```

默认读上述密码本，写出 `dashboard_product/deploy/secrets/`（目录 700）：

- `htpasswd` — 哈希，可装到服务器 `/etc/nginx/dashboard.htpasswd`
- `user-booklets.map` — 用户名 → 分册
- `initial-passwords` — 默认**不**写；需要本机 TSV 副本时加 `--write-initial-passwords`（仍是 600，不要上传 web 根、不要提交、不要写进日志）

发账号时只说用户名和分册，密码走单独通道。已有 htpasswd/map 时必须加 `--force` 才会覆盖。演示号 `admin` / `liuxue` / `gaozhong` / `daxue` 不在密码本中，生成时不会写入。

映射：`all`→`full`；`虚拟人`→`online_private`；`平台`→`online_platform`；`线下`→`offline_market`。本表账户（无密码）：

- `shaoyifan` `yangxu` `liumingzhi` `qinzhenxu` `zhangyuqing` → `full`
- `chenyue` → `online_private`
- `sunyue` → `online_platform`

加人：改密码本后在本机重跑生成脚本，再跑安装脚本（或等价 scp），然后 `nginx -t && systemctl reload nginx`。

## 本地从已有 artifact 试渲（不 refresh）

```bash
export PATH=/home/box/oxhor/warehouse/.venv/bin:$PATH
cd /home/box/oxhor/dashboard
ART=customers/bi_operations/Output/Dashboard/<run_id>/artifact.json
python3 -m dashboard_product.refresh render --artifact "$ART" --all-booklets
```

产出与 `artifact.json` 同目录的 `full.html` `online_private.html` `online_platform.html` `offline_market.html`。不要把 `artifact.json` 拷到服务器。

单册：`--booklet online_private`。不带 `--booklet` 时仍写 `artifact.html`（全量，兼容旧命令）。预留下线分册即使密码本暂无对应账号也要能渲、能发。

隔离自检：`online_private.html` 源码不得含 `online_platform` / `offline_market` / `market_total` 的团队数据。

## 日更真发

```bash
./dashboard_product/deploy/publish_static_dashboard.sh
```

顺序：refresh 一次 → 渲新四分册（含预留下线）→ 先全部落到服务器 `.tmp` 再 `mv`。任一册失败则该册线上文件保持上一成功版本。成功后删除线上遗留的 `liuxue.html` / `gaozhong.html` / `daxue.html`。日志只记路径与时间，不含密码。

已有 artifact、跳过 refresh：`ARTIFACT_JSON=/abs/path/artifact.json ./dashboard_product/deploy/publish_static_dashboard.sh`

凭据只从 `dashboard_product/.env.server`（600）读。禁止 `bash -x` 跑发布/安装脚本。禁止 `echo` 密码。

## 服务器切 Nginx（一次，或账号/分册变更后）

先保证 `/var/www/dashboard/` 上已有新四分册 HTML，再装门口：

```bash
./dashboard_product/deploy/install_dashboard_auth.sh
```

会上传 **哈希 htpasswd + map + nginx 样例**（**不**上传密码本、**不**上传 `initial-passwords`），服务器权限为 `640 root:www-data`（nginx worker 要读，不能对本机 600 原样照搬）。旧 `current.html` 挪到 web 根之外；旧业务组 HTML 从 web 根删除。`/healthz` 保持匿名。

样例配置：`deploy/nginx-dashboard-http.conf`。map 模板：`deploy/user-booklets.map.example`。location 白名单：`full|online_private|online_platform|offline_market`。用户分册 map 为 `$dashboard_booklet`；URI 与分册配对后由 `$dashboard_booklet_file` + `try_files` 放行（避免 rewrite 阶段 `if` 抢在 basic auth 前变成 403）。

安装后自检：对应用户登录只见本板块；跨册 403；匿名 401；`/healthz` 200；密码不进日志。

## 风险（本轮若未上 TLS）

当前站点是 **HTTP + basic auth**。浏览器发送的是 Base64 用户名密码，链路没有加密，等同密码裸奔。内部试用可先顶上；对公或经不信任网络前应上 TLS。本轮脚本不改证书。

## 回滚

把 `/etc/nginx/sites-available/dashboard.bak.pre-booklets` 拷回并 reload。不要把 `current.html` 或旧业务组分册重新放回 web 根。
