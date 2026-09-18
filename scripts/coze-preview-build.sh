#!/usr/bin/env bash
# 预览准备：确保 ROS 环境与工作区构建就绪。
# 真正的环境安装/修复/编译逻辑复用 scripts/setup_rosenv.sh。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# .preview 声明预览端口，它是 gitignore 的（平台按本文件决定对外暴露哪个端口）。
# 沙箱重建后它会丢，而它又是预览链路的前提，所以每次准备时都确保它存在。
PORT="${PORT:-5000}"
if [ ! -f "$PROJECT_DIR/.preview" ]; then
  printf '[preview.port]\nexpose_port = %s\n' "$PORT" > "$PROJECT_DIR/.preview"
  echo "已生成 .preview（expose_port = $PORT）"
fi

exec bash "$SCRIPT_DIR/setup_rosenv.sh"
