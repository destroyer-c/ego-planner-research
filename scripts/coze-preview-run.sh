#!/usr/bin/env bash
# 预览服务入口：无头跑起仿真，再用 Web 可视化服务在 5000 端口提供交互界面。
# 不走 rviz / Xvfb / 图像传输——只传 JSON 数据，由浏览器 Canvas 绘制。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

export PORT=5000
LOG_DIR="$PROJECT_DIR/.deps/preview-logs"

# 幂等：清掉上一次的预览残留。只动 5000，绝不碰 9000。
pids="$(ss -lptnH 'sport = :5000' 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u || true)"
if [ -n "$pids" ]; then kill -9 $pids 2>/dev/null || true; fi
pkill -f "roslaunch ego_planner" >/dev/null 2>&1 || true
sleep 1

# ROS 的激活脚本不是 nounset 安全的（会引用未定义的 CONDA_BUILD 等），source 期间先关掉 -u
set +u
# shellcheck disable=SC1091
source "$PROJECT_DIR/.deps/ros-env.sh"
set -u

mkdir -p "$LOG_DIR"

roslaunch ego_planner run_in_sim.launch >"$LOG_DIR/sim.log" 2>&1 &

# 等 ROS master 就绪：冷启动时 roscore 起来可能要十几秒，
# 而 Web 服务要先 init_node，master 没起来会一直阻塞、导致 5000 端口迟迟不监听。
for _ in $(seq 1 60); do
  if timeout 2 rosnode list >/dev/null 2>&1; then break; fi
  sleep 1
done

exec python3 "$SCRIPT_DIR/sim_web_bridge.py" --port "$PORT"
