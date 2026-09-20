# 静态看板发布

> 2026-09-16 模块切换：人员进度与钉钉推送已迁至 `monitoring_product/`，看板不再承担发送。新入口要求 workspace、snapshot-id、run-id、as-of-date、data-through-date；正式发送另需显式 env-file。共享花名册在 `workspace_modeling/operations/people.json`。本地迁移完成不代表云端任务已切换；详见项目根目录 `monitoring_product/README.md`。

本地登录参数可放在未纳入 Git 的 `.env.server`（模板见 `.env.server.example`）。该文件仅供人工/本地部署工具读取，权限应保持为 `600`；不要复制到服务器或提交到 Git。htpasswd、用户→分册映射和初始密码在 `deploy/secrets/`（C 层，目录 700 / 文件 600），同样不进 Git。

## 当前数据流

你的电脑保存项目、客户工作区当前 Snapshot、Saved Query registry 和配置；服务器只保存四分册 HTML 与线上团队特供 HTML。刷新、计算和 Snapshot 更新全部在本地完成，再通过 SCP 批量上传静态文件：

1. 本地 `refresh` 读取显式 `current_snapshot_id`，通过 Data Platform `run-saved-query` 查询并生成 **一份**全量 `artifact.json`。
2. 本地按**团队板块** `render`：`full.html`（全部团队，含 `market_total`）、`online_private.html`（虚拟人）、`online_platform.html`（平台）、`offline_market.html`（线下，预留）。过滤在写入 HTML 前做完，板块分册源码不含其他团队与 `market_total`。旧业务组分册不再日更。
3. 人工/日更脚本将四分册传到服务器临时目录，全部 `install` 到 `.tmp` 后再 `mv` 原子替换；失败的分册不覆盖上一成功文件。
4. Nginx 对业务页做 basic auth，按用户映射到对应分册。`/healthz` 匿名 200。匿名 `/` 不会落到全量。

线上团队特供看板不进入上述四分册日更链路。它读取显式的影子 Snapshot，输出 `online_market_special.html`；独立发布脚本会和带入口的 `full.html` 一起原子替换。主数仓当前指针和四个旧分册不被刷新或替换。

**不要**把 `artifact.json` 放到 `/var/www/dashboard/` 或任何公网目录。服务器不接触 DuckDB、`Input/`、`Work/Runs/`、客户凭据或整个 `customers/` 目录，也不需要 Python、Data Platform 或 systemd 刷新任务。

钉钉人员进度把 `people.png` 和 `details.xlsx` 放到 `/var/www/dashboard/notify/<token>/<team_id>/`。路径匿名可读（钉钉拉图不会登录），目录不可列出。不要上传 `artifact.json`、HTML 或 webhook。首次启用跑 `./monitoring_product/deploy/install_notify_nginx.sh`（只改 Nginx，不动看板密码）。日更脚本不自动群发。

云电脑独立发送钉钉时，应通过 C 层单独提供正式凭据文件，并在发送命令中显式指定；当前合同见 [监控说明](../monitoring_product/README.md)。本次目录整理不检查密钥内容，也不声称任何通道当前已配置。不得把凭据包与普通日志、代码或历史文档合并。

## 部署约定与历史运行记录

静态部署已从单文件 `current.html` 匿名全量改为四分册 + htpasswd。样例配置为 `deploy/nginx-dashboard-http.conf`。DNSPod 的 A 记录指向 `38.76.161.233`。服务器不执行刷新、计算或 Snapshot 更新。

## 公开入口与 TLS

当前访问地址为 `http://dashboard.apinova.cn`。业务页需登录；`/healthz` 可匿名探活。

**本轮若未上 TLS：HTTP + basic auth 会把用户名密码以 Base64 在网上传输，等同裸奔。** 内部试用可先这样顶；对公或经不信任网络前应上 TLS。刷新脚本不接触域名或证书配置。

## 本地发布

每次本地刷新完成后，上传四分册（先传临时目录，远端全部落 `.tmp` 再 `mv`）：

```bash
python3 -m dashboard_product.refresh render --artifact <artifact.json> --all-booklets
scp -P 22 full.html online_private.html online_platform.html offline_market.html root@<server>:/tmp/dashboard-booklets/
ssh -p 22 root@<server> 'dest=/var/www/dashboard; for f in full.html online_private.html online_platform.html offline_market.html; do install -m 0644 /tmp/dashboard-booklets/$f $dest/.$f.tmp; done; for f in full.html online_private.html online_platform.html offline_market.html; do mv -f $dest/.$f.tmp $dest/$f; done'
```

不要 scp `artifact.json`。生产环境建议改用 SSH key，避免在命令行或脚本中传密码。

### 线上团队特供看板

先在本地完成影子 Snapshot、`online_market_refresh` 和 `online_market_render`，确认目标表、平台表和现金实际待接入状态后，再单独发布：

```bash
ARTIFACT_JSON=/abs/path/online_market_artifact.json \
FULL_HTML=/abs/path/full.html \
  ./dashboard_product/deploy/publish_online_market_dashboard.sh
```

该脚本只上传 `full.html` 和 `online_market_special.html`，不上传影子 warehouse、工单文件或 artifact；`online_platform.html` 由既有四分册发布链提供，特供页可从总看板和内嵌语培页正常打开。

## 每日自动发布

`deploy/publish_static_dashboard.sh` 会在本地依次运行一次 `refresh`、四分册 `render`，再只上传 HTML。凭据从被 Git 忽略且权限为 `600` 的 `.env.server` 读取。跳过 refresh 时设 `ARTIFACT_JSON`。禁止 `bash -x` 运行（会把服务器密码打到终端）。

已有运行记录为云电脑宿主每天 10:00（Asia/Shanghai）调用上述脚本、本机定时停用；本次没有重新核验远端定时状态。钉钉不在该脚本内。发布日志默认写入项目 `.local/logs/dashboard/`。

### SSH/SCP 登录方式

服务器凭据未变化时，普通沙箱里的直接 `ssh` 可能仍返回 `Permission denied (password)`。不要因此轮换密码或连续重试。应从已授权的提升执行环境调用 `deploy/publish_static_dashboard.sh` 或 `deploy/install_dashboard_auth.sh`；脚本会从本机 `.env.server` 读取凭据，并通过 `/usr/bin/expect` 的 PTY 完成 SSH/SCP 密码交互。该方式已在 2026-09-06 成功发布并通过服务器 HTTP 校验。密码不写入脚本、文档或日志。

## 失败与回滚行为

刷新或渲染失败不会上传文件，访问者继续看到上一次成功分册。上传阶段先写 `.tmp` 再 `mv`：某个分册在 `install` 失败时，该册线上文件保持上一成功版本。每次首次发布或排障后应检查：`http://dashboard.apinova.cn/healthz` 匿名 200、未登录访问 `/` 为 401、对应账号只能打开自己的分册、`artifact.json` 的 `snapshot_id` 仍只在本地。

## 运行前提

本地必须能完成数据采集、Snapshot 更新、`refresh` 和 `render`；服务器只需 Nginx、htpasswd 文件和 SSH。数据刷新失败时不要上传新文件。

## 团队账号与分册操作

权限按 `team_id` 板块切分，不按业务组切分。账号使用 htpasswd 发放，不提供自助注册。

| 密码本权限 | 分册 | 页面 |
|---|---|---|
| `all` | `full` | `/full.html` |
| `虚拟人` | `online_private` | `/online_private.html` |
| `平台` | `online_platform` | `/online_platform.html` |
| `线下` | `offline_market` | `/offline_market.html` |

板块分册不含 `market_total`，匿名访问 `/` 应为 401，跨册应为 403，`/healthz` 保持匿名 200。默认上传和 Nginx 白名单只含上述四册。

以下命令均从项目根目录执行。密码本为 C 层 `dashboard_product/deploy/secrets/password-book-20260907.xlsx`，列为用户名、密码、权限；本说明只给路径，不核验当前账户或密码内容。

```bash
python3 dashboard_product/deploy/generate_dashboard_auth.py --force
```

生成 `deploy/secrets/htpasswd` 与 `user-booklets.map`，目录权限 700、文件 600。只有确需本机密码副本时才加 `--write-initial-passwords`，不要将该文件上传、提交或写入日志。更新账户时改密码本后重新生成；已有输出须使用 `--force` 明确覆盖。密码通过独立通道交付。

已有 artifact 的渲染与发布：

```bash
python3 -m dashboard_product.refresh render --artifact <artifact.json> --all-booklets
ARTIFACT_JSON=/abs/path/artifact.json ./dashboard_product/deploy/publish_static_dashboard.sh
```

单册使用 `--booklet online_private`；分册与 artifact 位于同一输出目录。验收板块源码中不存在其他团队或 `market_total` 数据。只上传 HTML。

服务器已有四分册后，安装或更新鉴权：

```bash
./dashboard_product/deploy/install_dashboard_auth.sh
```

安装仅上传哈希 htpasswd、用户映射及 Nginx 配置，不上传密码本与 `initial-passwords`。服务器权限为 `640 root:www-data`；模板为 `deploy/nginx-dashboard-http.conf` 与 `deploy/user-booklets.map.example`。执行后验证 Nginx 配置、账户隔离、匿名响应与探活，不把密码打入日志。禁止 `bash -x` 执行凭据相关脚本。

若安装失败，按实际存在的 `/etc/nginx/sites-available/dashboard.bak.pre-booklets` 恢复配置后验证并 reload；不要把旧单文件全量入口或旧业务组分册重新放回 web 根。历史验收事实见 [团队分册历史记录](../docs/history/dashboard/AUTH_TEAM_BOOKLETS_HANDOFF.md)，不代表本次已执行远端验收。
