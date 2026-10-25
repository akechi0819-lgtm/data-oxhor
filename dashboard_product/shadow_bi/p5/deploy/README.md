# 已部署receiver源码回收

这些文件从2026-10-25现网指定路径只读取回，保留原样及原权限模型，不含env/凭据。`publish-pending.sh`对应`/usr/local/sbin/shadow-bi-receiver-publish`，systemd文件对应`/etc/systemd/system/`同名文件；不是自动安装脚本。

当前合同接收39张成品JSONL，不接收任意文件/命令。压缩512MiB、展开2GiB、单文件256MiB、2048文件，流式摘要及截止日防倒退保留。服务器根worker仍固定P4流程。

已知缺陷：root worker以UMask0077写last_published与last_published_hash，shadowbi状态读取失败；此前last_failed同类问题可使已排队请求返回400。此次仅收回源码，未修复权限或重发批次。处理此缺陷须先核对实际状态、同批幂等与最小权限，不向全体放开文件，不把HTTP错误等同未执行。
