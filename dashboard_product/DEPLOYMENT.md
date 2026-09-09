# 静态看板发布

本地登录参数可放在未纳入 Git 的 `.env.server`（模板见 `.env.server.example`）。该文件仅供人工/本地部署工具读取，权限应保持为 `600`；不要复制到服务器或提交到 Git。htpasswd、用户→分册映射和初始密码在 `deploy/secrets/`（C 层，目录 700 / 文件 600），同样不进 Git。

## 当前数据流

你的电脑保存项目、客户工作区当前 Snapshot、Saved Query registry 和配置；服务器只保存四分册 HTML。刷新、计算和 Snapshot 更新全部在本地完成，再通过 SCP 批量上传静态文件：

1. 本地 `refresh` 读取显式 `current_snapshot_id`，通过 Data Platform `run-saved-query` 查询并生成 **一份**全量 `artifact.json`。
2. 本地按**团队板块** `render`：`full.html`（全部团队，含 `market_total`）、`online_private.html`（虚拟人）、`online_platform.html`（平台）、`offline_market.html`（线下，预留）。过滤在写入 HTML 前做完，板块分册源码不含其他团队与 `market_total`。旧业务组分册不再日更。
3. 人工/日更脚本将四分册传到服务器临时目录，全部 `install` 到 `.tmp` 后再 `mv` 原子替换；失败的分册不覆盖上一成功文件。
4. Nginx 对业务页做 basic auth，按用户映射到对应分册。`/healthz` 匿名 200。匿名 `/` 不会落到全量。

**不要**把 `artifact.json` 放到 `/var/www/dashboard/` 或任何公网目录。服务器不接触 DuckDB、`Input/`、`Work/Runs/`、客户凭据或整个 `customers/` 目录，也不需要 Python、Data Platform 或 systemd 刷新任务。

钉钉人员进度把 `people.png` 和 `details.xlsx` 放到 `/var/www/dashboard/notify/<token>/<team_id>/`。路径匿名可读（钉钉拉图不会登录），目录不可列出。不要上传 `artifact.json`、HTML 或 webhook。首次启用跑 `./dashboard_product/deploy/install_notify_nginx.sh`（只改 Nginx，不动看板密码）。日更脚本不自动群发。

云电脑要独立发送钉钉，必须把本机 `dashboard_product/.env.server`（C 层，mode 600）CopyToBox 到 `/home/box/oxhor/dashboard/dashboard_product/.env.server`。该文件含服务器 SSH 密码和 `DINGTALK_WEBHOOK_*` / `DINGTALK_SECRET_*`。禁止进公开 Git、禁止贴聊天、禁止写进文档明文。缺某个通道的 webhook 时，`notify send` 会跳过该通道而不是伪造发送。2026-09-09 本机已填线下青少/高中；线上私域、线上平台、线下大学仍空。



分册命令、发账号和切 Nginx 见 [`docs/AUTH_TEAM_BOOKLETS_RUN.md`](docs/AUTH_TEAM_BOOKLETS_RUN.md)。验收合同见 [`docs/AUTH_TEAM_BOOKLETS_HANDOFF.md`](docs/AUTH_TEAM_BOOKLETS_HANDOFF.md)。

## 服务器与自动化状态

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

## 每日自动发布

`deploy/publish_static_dashboard.sh` 会在本地依次运行一次 `refresh`、四分册 `render`，再只上传 HTML。凭据从被 Git 忽略且权限为 `600` 的 `.env.server` 读取。跳过 refresh 时设 `ARTIFACT_JSON`。禁止 `bash -x` 运行（会把服务器密码打到终端）。

例行「看板日更」每天 10:00（Asia/Shanghai）由许家印在云电脑调用上述脚本。本机 Codex 定时已停。钉钉不在该脚本内。

## 失败与回滚行为

刷新或渲染失败不会上传文件，访问者继续看到上一次成功分册。上传阶段先写 `.tmp` 再 `mv`：某个分册在 `install` 失败时，该册线上文件保持上一成功版本。每次首次发布或排障后应检查：`http://dashboard.apinova.cn/healthz` 匿名 200、未登录访问 `/` 为 401、对应账号只能打开自己的分册、`artifact.json` 的 `snapshot_id` 仍只在本地。

## 运行前提

本地必须能完成数据采集、Snapshot 更新、`refresh` 和 `render`；服务器只需 Nginx、htpasswd 文件和 SSH。数据刷新失败时不要上传新文件。
