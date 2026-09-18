#!/usr/bin/env bash
# 预览服务入口：在 Xvfb 里跑起仿真 + rviz，再用预览桥在 5000 端口提供画面与鼠标交互。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

export PORT=5000
export DISPLAY=:99
SCREEN_W=1280
SCREEN_H=1024
LOG_DIR="$PROJECT_DIR/.deps/preview-logs"

# 幂等：每次执行都先清掉上一次的预览残留。只动 5000，绝不碰 9000。
# 沙箱里没有 fuser，用 ss 取出占用 5000 的 pid 再杀。
for pid in $(ss -lptnH 'sport = :5000' 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u); do
  kill "$pid" >/dev/null 2>&1 || true
done
pkill -x Xvfb >/dev/null 2>&1 || true
pkill -f "roslaunch ego_planner" >/dev/null 2>&1 || true
sleep 2

# ROS 的激活脚本不是 nounset 安全的（会引用未定义的 CONDA_BUILD 等），source 期间先关掉 -u
set +u
# shellcheck disable=SC1091
source "$PROJECT_DIR/.deps/ros-env.sh"
set -u

mkdir -p "$LOG_DIR"

Xvfb "$DISPLAY" -screen 0 "${SCREEN_W}x${SCREEN_H}x24" >"$LOG_DIR/xvfb.log" 2>&1 &
sleep 2

roslaunch ego_planner run_in_sim.launch >"$LOG_DIR/sim.log" 2>&1 &
sleep 8

roslaunch ego_planner rviz.launch >"$LOG_DIR/rviz.log" 2>&1 &
sleep 3

exec python3 "$SCRIPT_DIR/preview_bridge.py" \
  --display "$DISPLAY" --width "$SCREEN_W" --height "$SCREEN_H" --port "$PORT"
