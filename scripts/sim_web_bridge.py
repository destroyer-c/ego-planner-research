#!/usr/bin/env python3
"""EGO-Planner 仿真的纯 Web 可视化服务。

只向浏览器传 JSON 数据（点云 / 位姿 / B 样条轨迹），由浏览器用 Canvas 做 3D 投影绘制；
没有图像编码与传输，也不依赖 rviz / Xvfb。

数据来源：
  /visual_slam/odom            nav_msgs/Odometry      无人机位姿（200Hz，仅保留最新）
  /map_generator/global_cloud  sensor_msgs/PointCloud2 全局地图点云（0.5Hz，体素降采样后缓存）
  /planning/bspline            ego_planner/Bspline     规划轨迹（自定义消息，按 .msg 定义解析原始字节）
  /move_base_simple/goal       geometry_msgs/PoseStamped 目标点（同时也是本服务的发布目标）
"""

import argparse
import json
import os
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import numpy as np
import rospy
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Odometry
from sensor_msgs.msg import PointCloud2


class World:
    """把仿真话题聚合成 Web 端需要的世界快照。"""

    def __init__(self, map_topic, voxel, max_points):
        self._lock = threading.Lock()
        self.pose = None
        self.vel = [0.0, 0.0, 0.0]
        self.goal = None
        self.traj = []
        self.points = []          # 体素降采样后的地图点，单位为厘米的整数（省带宽）
        self.bounds = None
        self._voxel = voxel
        self._max_points = max_points
        self._hz = 0.0
        self._ticks = 0
        self._t0 = time.time()

        self._pub_goal = rospy.Publisher("/move_base_simple/goal", PoseStamped, queue_size=1)
        rospy.Subscriber("/visual_slam/odom", Odometry, self._on_odom, queue_size=1)
        rospy.Subscriber("/move_base_simple/goal", PoseStamped, self._on_goal, queue_size=1)
        rospy.Subscriber("/planning/bspline", rospy.AnyMsg, self._on_bspline, queue_size=1)
        rospy.Subscriber(map_topic, PointCloud2, self._on_map, queue_size=1)

    # ---------- 话题回调 ----------
    def _on_odom(self, msg):
        p = msg.pose.pose.position
        v = msg.twist.twist.linear
        with self._lock:
            self.pose = [p.x, p.y, p.z]
            self.vel = [v.x, v.y, v.z]
            self._ticks += 1
            dt = time.time() - self._t0
            if dt > 1:
                self._hz = self._ticks / dt
                self._ticks = 0
                self._t0 = time.time()

    def _on_goal(self, msg):
        p = msg.pose.position
        with self._lock:
            self.goal = [p.x, p.y, p.z]

    def _on_bspline(self, msg):
        """ego_planner/Bspline 是本仓库的自定义消息，而本环境的 catkin 没有生成它的 Python 类，
        因此按 .msg 定义直接解析原始字节（ROS 消息紧凑小端、无对齐填充）：

            int32 order | int64 traj_id | time start_time
            float64[] knots | geometry_msgs/Point[] pos_pts | float64[] yaw_pts | float64 yaw_dt

        只需要 pos_pts（B 样条控制点），取到即止。"""
        try:
            raw = msg._buff
            off = 4 + 8 + 8                    # order + traj_id + start_time(secs,nsecs)
            n_knots, = struct.unpack_from("<I", raw, off)
            off += 4 + n_knots * 8
            n_pts, = struct.unpack_from("<I", raw, off)
            off += 4
            pts = np.frombuffer(raw, dtype="<f8", count=n_pts * 3, offset=off).reshape(-1, 3)
        except (struct.error, ValueError, AttributeError):
            return
        with self._lock:
            self.traj = np.round(pts, 2).tolist()

    def _on_map(self, msg):
        xyz = self._cloud_xyz(msg)
        if xyz.size == 0:
            return
        pts = self._voxel_downsample(xyz, self._voxel, self._max_points)
        cm = np.round(pts * 100).astype(np.int32)
        bounds = [float(xyz[:, 0].min()), float(xyz[:, 1].min()),
                  float(xyz[:, 0].max()), float(xyz[:, 1].max())]
        with self._lock:
            self.points = cm.tolist()
            self.bounds = bounds

    @staticmethod
    def _cloud_xyz(msg):
        """按 point_step 直接做 numpy 视图解析；字段不匹配时退回通用解析。"""
        if msg.point_step == 16 and msg.width:
            a = np.frombuffer(msg.data, dtype=np.float32)
            if a.size >= msg.width * 4:
                return a[: msg.width * 4].reshape(-1, 4)[:, :3]
        import sensor_msgs.point_cloud2 as pc2
        rows = [[p[0], p[1], p[2]] for p in
                pc2.read_points(msg, field_names=("x", "y", "z"), skip_nans=True)]
        return np.asarray(rows, dtype=np.float32).reshape(-1, 3)

    @staticmethod
    def _voxel_downsample(xyz, voxel, max_points):
        """3D 体素降采样：每格留一个点，保证密度均匀；超过上限再等间隔抽样。"""
        key = np.floor(xyz / voxel).astype(np.int64)
        key -= key.min(axis=0)
        flat = (key[:, 0] * 4096 + key[:, 1]) * 4096 + key[:, 2]
        _, idx = np.unique(flat, return_index=True)
        pts = xyz[idx]
        if len(pts) > max_points:
            step = int(np.ceil(len(pts) / max_points))
            pts = pts[::step]
        return pts

    # ---------- HTTP 访问 ----------
    def snapshot(self):
        with self._lock:
            return {
                "p": self.pose,
                "v": self.vel,
                "goal": self.goal,
                "traj": self.traj,
                "hz": round(self._hz, 1),
            }

    def map_dump(self):
        with self._lock:
            return {"voxel": self._voxel, "bounds": self.bounds, "pts": self.points}

    def set_goal(self, x, y, z):
        msg = PoseStamped()
        msg.header.stamp = rospy.Time.now()
        msg.header.frame_id = "world"
        msg.pose.position.x = float(x)
        msg.pose.position.y = float(y)
        msg.pose.position.z = float(z)
        msg.pose.orientation.w = 1.0
        self._pub_goal.publish(msg)
        with self._lock:
            self.goal = [float(x), float(y), float(z)]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    world = None
    page_path = None

    def log_message(self, *args):
        pass

    def _reply(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        try:
            if url.path == "/":
                with open(self.page_path, "rb") as f:
                    self._reply(200, "text/html; charset=utf-8", f.read())
            elif url.path == "/state":
                self._reply(200, "application/json",
                            json.dumps(self.world.snapshot(), separators=(",", ":")).encode())
            elif url.path == "/map":
                self._reply(200, "application/json",
                            json.dumps(self.world.map_dump(), separators=(",", ":")).encode())
            elif url.path == "/goal":
                q = parse_qs(url.query)
                x = float(q["x"][0]); y = float(q["y"][0]); z = float(q.get("z", ["1.0"])[0])
                self.world.set_goal(x, y, z)
                self._reply(200, "application/json",
                            json.dumps({"ok": True, "goal": [x, y, z]}).encode())
            elif url.path == "/healthz":
                self._reply(200, "text/plain; charset=utf-8", b"ok")
            else:
                self._reply(404, "text/plain; charset=utf-8", b"not found")
        except (KeyError, ValueError):
            self._reply(400, "text/plain; charset=utf-8", b"bad request")
        except FileNotFoundError:
            self._reply(500, "text/plain; charset=utf-8", b"page missing")


def main():
    parser = argparse.ArgumentParser(description="EGO-Planner 仿真 Web 可视化")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--map-topic", default="/map_generator/global_cloud")
    parser.add_argument("--voxel", type=float, default=0.3, help="地图体素边长(米)")
    parser.add_argument("--max-points", type=int, default=26000, help="传给浏览器的地图点数上限")
    parser.add_argument("--page", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                       "sim_web_page.html"))
    args = parser.parse_args()

    rospy.init_node("sim_web_bridge", anonymous=True, disable_signals=True)
    Handler.world = World(args.map_topic, args.voxel, args.max_points)
    Handler.page_path = args.page

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    print("Web 可视化已就绪: http://%s:%d" % (args.host, args.port), flush=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    rospy.spin()


if __name__ == "__main__":
    main()
