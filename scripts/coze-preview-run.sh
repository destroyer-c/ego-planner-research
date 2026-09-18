#!/usr/bin/env bash
# 预览服务入口：在 Xvfb 里跑起仿真 + rviz，再用预览桥在 5000 端口提供画面与鼠标交互。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

export PORT=5000
export DISPLAY=:99
SCREEN_W=1024              # 软件渲染下分辨率直接决定 CPU 开销，够看清轨迹即可
SCREEN_H=768
RVIZ_FPS=10                # rviz 默认 30fps；无 GPU 时这是最大的 CPU 消耗项
LOG_DIR="$PROJECT_DIR/.deps/preview-logs"
RVIZ_CFG="$PROJECT_DIR/.deps/rviz-preview.rviz"

# 幂等：每次执行都先清掉上一次的预览残留。只动 5000，绝不碰 9000。
_clear_port_5000() {
  local pids
  pids="$(ss -lptnH 'sport = :5000' 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u || true)"
  [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true
}
_clear_port_5000
pkill -x Xvfb >/dev/null 2>&1 || true
pkill -f "roslaunch ego_planner" >/dev/null 2>&1 || true
sleep 1

# ROS 的激活脚本不是 nounset 安全的（会引用未定义的 CONDA_BUILD 等），source 期间先关掉 -u
set +u
# shellcheck disable=SC1091
source "$PROJECT_DIR/.deps/ros-env.sh"
set -u

mkdir -p "$LOG_DIR"

# 由仓库里的 default.rviz 生成预览专用配置：只把渲染帧率降下来，不改动仓库文件
SRC_RVIZ="$(rospack find ego_planner)/launch/default.rviz"
sed "s/^\( *\)Frame Rate: .*/\1Frame Rate: ${RVIZ_FPS}/" "$SRC_RVIZ" > "$RVIZ_CFG"

Xvfb "$DISPLAY" -screen 0 "${SCREEN_W}x${SCREEN_H}x24" >"$LOG_DIR/xvfb.log" 2>&1 &
sleep 2

roslaunch ego_planner run_in_sim.launch >"$LOG_DIR/sim.log" 2>&1 &
sleep 8

# rviz 是纯可视化，降优先级让规划器/仿真先吃饱 CPU（4 核无 GPU，软件渲染会抢满）
nice -n 10 rviz -d "$RVIZ_CFG" >"$LOG_DIR/rviz.log" 2>&1 &
sleep 3

exec python3 "$SCRIPT_DIR/preview_bridge.py" \
  --display "$DISPLAY" --width "$SCREEN_W" --height "$SCREEN_H" --fps 10 --port "$PORT"
