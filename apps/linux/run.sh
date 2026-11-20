#!/bin/sh
# 从源码直接运行时账 Timebook（不安装）
# 用法: ./run.sh [--page today|focus|stats|timeline|forfeit]
cd "$(dirname "$0")" || exit 1
exec python3 -m timebook.main "$@"
