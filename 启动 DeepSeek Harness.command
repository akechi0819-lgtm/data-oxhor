#!/bin/zsh

set -u

DSH_BIN="/Users/akechi/.local/bin/dsh"
DSH_HOST="127.0.0.1"
DSH_PORT="3080"
DSH_URL="http://${DSH_HOST}:${DSH_PORT}"

if [[ ! -x "${DSH_BIN}" ]]; then
  echo "DeepSeek Harness 命令不存在或不可执行：${DSH_BIN}"
  echo "按任意键关闭窗口。"
  read -k 1
  exit 1
fi

if /usr/bin/curl -fsS --max-time 1 "${DSH_URL}" >/dev/null 2>&1; then
  /usr/bin/open "${DSH_URL}"
  exit 0
fi

(
  for _attempt in {1..40}; do
    if /usr/bin/curl -fsS --max-time 1 "${DSH_URL}" >/dev/null 2>&1; then
      /usr/bin/open "${DSH_URL}"
      exit 0
    fi
    /bin/sleep 0.25
  done
  echo "DeepSeek Harness 未在 10 秒内响应，请检查上方启动日志。"
) &

echo "正在启动 DeepSeek Harness：${DSH_URL}"
echo "请保持此终端窗口打开；需要停止服务时按 Ctrl-C。"
echo

exec "${DSH_BIN}" web --host "${DSH_HOST}" --port "${DSH_PORT}"
