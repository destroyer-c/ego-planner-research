#!/usr/bin/env bash
# 预览准备：确保 ROS 环境与工作区构建就绪。
# 真正的环境安装/修复/编译逻辑复用 scripts/setup_rosenv.sh。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

exec bash "$SCRIPT_DIR/setup_rosenv.sh"
