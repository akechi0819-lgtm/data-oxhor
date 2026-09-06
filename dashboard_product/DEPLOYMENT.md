# 静态看板发布

本地登录参数可放在未纳入 Git 的 `.env.server`（模板见 `.env.server.example`）。该文件仅供人工/本地部署工具读取，权限应保持为 `600`；不要复制到服务器或提交到 Git。

## 当前数据流

你的电脑保存项目、客户工作区当前 Snapshot、Saved Query registry 和配置；服务器只保存最终 HTML。刷新、计算和 Snapshot 更新全部在本地完成，再通过 SCP 上传单个静态文件：

1. 本地 `refresh` 读取显式 `current_snapshot_id`，通过 Data Platform `run-saved-query` 查询并生成 artifact。
2. 本地 `render` 生成 HTML，人工验收后上传到服务器临时文件。
3. 服务器将临时文件原子替换为 `/var/www/dashboard/current.html`。
4. Nginx 通过 `dashboard.apinova.cn` 公开这个静态文件。

服务器不接触 DuckDB、`Input/`、`Work/Runs/`、客户凭据或整个 `customers/` 目录，也不需要 Python、Data Platform 或 systemd 刷新任务。

## 服务器与自动化状态

服务器静态部署已完成：Nginx 已安装，静态文件位于 `/var/www/dashboard/current.html`，并以 `dashboard.apinova.cn` 的 HTTP 虚拟主机提供。DNSPod 的 A 记录指向 `38.76.161.233`；`/` 与 `/healthz` 已验证为 HTTP 200。服务器不执行刷新、计算或 Snapshot 更新。

## 公开入口

当前访问地址为 `http://dashboard.apinova.cn`。该站点仅供内部使用，按当前决定不配置 TLS；刷新脚本不接触域名或证书配置。服务器只接受并提供最终 HTML。

## 本地发布

每次本地刷新完成后，上传新的 HTML（推荐先传临时文件，再远端 `mv` 原子替换）：

```bash
scp -P 22 customers/bi_operations/Output/Dashboard/<run_id>/artifact.html root@<server>:/tmp/dashboard-current.html
ssh -p 22 root@<server> 'install -m 0644 /tmp/dashboard-current.html /var/www/dashboard/current.html'
```

生产环境建议改用 SSH key，避免在命令行或脚本中传密码。

## 每日自动发布（Codex）

`deploy/publish_static_dashboard.sh` 会在本地依次运行 `refresh`、`render`，再只上传最终 HTML 到服务器。凭据从被 Git 忽略且权限为 `600` 的 `.env.server` 读取。

Codex 中已创建唯一自动化“每日刷新并发布全量看板”，每天 10:00（Asia/Shanghai）运行，失败时通知。它直接调用上述脚本，发布三个团队的全量看板；不再使用 macOS `launchd` 或服务器 `systemd`。自动化暂停/修改/删除请在 Codex 的自动化管理中操作。

## 失败与回滚行为

刷新或渲染失败不会上传文件，访问者继续看到上一次成功版本；新的本地 run 目录保留用于排查。上传后服务器通过临时文件加 `mv` 原子替换 `current.html`。每次首次发布或排障后应检查：`http://dashboard.apinova.cn/healthz`、首页 HTTP 200、`artifact.json` 的 `snapshot_id` 和 Codex 自动化状态。

## 运行前提

本地必须能完成数据采集、Snapshot 更新、`refresh` 和 `render`；服务器只需 Nginx 和 SSH。数据刷新失败时不要上传新文件，服务器会继续提供上一次成功版本。
