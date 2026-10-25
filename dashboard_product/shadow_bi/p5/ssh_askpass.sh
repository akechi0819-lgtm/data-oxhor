#!/bin/sh
# OpenSSH读取已授权服务器私有凭据，不进入命令参数或日志。
exec cat "$SHADOW_SSH_PASSWORD_FILE"
