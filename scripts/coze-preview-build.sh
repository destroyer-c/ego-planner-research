#!/usr/bin/env bash
# 预览准备：确保 ROS 环境与工作区构建就绪，并校验预览所需的外部命令。
# 真正的环境安装/修复/编译逻辑复用 scripts/setup_rosenv.sh。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

for cmd in ffmpeg Xvfb; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "预览需要命令 $cmd，但当前沙箱里找不到。" >&2
    exit 1
  fi
done

exec bash "$SCRIPT_DIR/setup_rosenv.sh"
