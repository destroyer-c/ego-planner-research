#!/usr/bin/env python3
"""预览桥：把 Xvfb 里 rviz 的画面推给浏览器，并把浏览器里的鼠标动作回灌到 Xvfb。"""

import argparse
import ctypes
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

JPEG_SOI = b"\xff\xd8"
JPEG_EOI = b"\xff\xd9"


def find_ffmpeg(explicit=None):
    """挑一个支持 x11grab 的 ffmpeg。

    conda 环境里的 ffmpeg 不带 x11grab（会报 Unknown input format: 'x11grab'），
    所以优先用系统的 /usr/bin/ffmpeg，再退回到 PATH 上的其它候选。
    """
    for candidate in ([explicit] if explicit else ["/usr/bin/ffmpeg", "ffmpeg"]):
        if not candidate:
            continue
        try:
            probe = subprocess.run([candidate, "-hide_banner", "-devices"],
                                   capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            continue
        if "x11grab" in probe.stdout:
            return candidate
    raise RuntimeError("找不到支持 x11grab 的 ffmpeg（conda 自带的 ffmpeg 不支持，需要系统 /usr/bin/ffmpeg）")

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>EGO-Planner 仿真预览</title>
<style>
html,body{margin:0;height:100%;background:#0d0d0d;overflow:hidden;
  font:12px/1.5 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;color:#9aa0a6}
#bar{height:28px;display:flex;align-items:center;gap:14px;padding:0 12px;
  background:#1a1a1a;border-bottom:1px solid #2c2c2c;white-space:nowrap}
#bar b{color:#e8eaed}
#st{margin-left:auto;color:#7c8cf8}
#wrap{position:absolute;top:28px;left:0;right:0;bottom:0;display:flex;align-items:center;justify-content:center}
#v{max-width:100%;max-height:100%;cursor:crosshair;box-shadow:0 0 0 1px #2c2c2c}
</style></head>
<body>
<div id="bar">
  <span>EGO-Planner 仿真</span>
  <span>先点画面里 rviz 工具栏的 <b>2D Nav Goal</b>，再点地图即可发目标点</span>
  <span>左键拖拽＝旋转，中键拖拽＝平移，滚轮＝缩放</span>
  <span id="st">连接中…</span>
</div>
<div id="wrap"><img id="v" alt="等待画面…"></div>
<script>
const v = document.getElementById('v'), st = document.getElementById('st');
const SW = __W__, SH = __H__;
let dragging = 0, fails = 0;

function toScreen(ev) {
  const r = v.getBoundingClientRect();
  return [(ev.clientX - r.left) * SW / r.width, (ev.clientY - r.top) * SH / r.height];
}
function send(params) {
  fetch('/input?' + new URLSearchParams(params), {cache: 'no-store'}).catch(() => {});
}
function tick() {
  const img = new Image();
  img.onload = () => { v.src = img.src; fails = 0; st.textContent = '实时画面'; };
  img.onerror = () => { fails++; st.textContent = '等待仿真画面…'; };
  img.src = '/frame.jpg?t=' + Date.now();
}
setInterval(tick, 400); tick();

v.addEventListener('contextmenu', e => e.preventDefault());
v.addEventListener('mousedown', e => {
  e.preventDefault();
  const [x, y] = toScreen(e);
  dragging = e.button + 1;
  send({t: 'down', x: x, y: y, b: dragging});
});
window.addEventListener('mousemove', e => {
  if (!dragging) return;
  const [x, y] = toScreen(e);
  send({t: 'move', x: x, y: y});
});
window.addEventListener('mouseup', e => {
  if (!dragging) return;
  const [x, y] = toScreen(e);
  send({t: 'up', x: x, y: y, b: dragging});
  dragging = 0;
});
v.addEventListener('wheel', e => {
  e.preventDefault();
  const [x, y] = toScreen(e);
  send({t: 'wheel', x: x, y: y, d: e.deltaY < 0 ? 1 : -1});
}, {passive: false});
</script></body></html>
"""


class WindowFitter(threading.Thread):
    """Xvfb 里没有窗口管理器，rviz 的窗口不会占满屏幕（周围一圈黑边）。

    这里把最大的顶层窗口拉到整屏，预览里就只剩画面本身。
    """

    def __init__(self, display, width, height, delay=6, interval=3, attempts=12):
        super().__init__(daemon=True)
        self.display_name, self.width, self.height = display, width, height
        self.delay, self.interval, self.attempts = delay, interval, attempts

    def run(self):
        time.sleep(self.delay)
        x11 = ctypes.CDLL("libX11.so.6")
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XDefaultRootWindow.restype = ctypes.c_ulong
        x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        x11.XFlush.argtypes = [ctypes.c_void_p]
        x11.XQueryTree.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
            ctypes.POINTER(ctypes.c_uint)]
        x11.XGetGeometry.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]
        x11.XMoveResizeWindow.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
            ctypes.c_uint, ctypes.c_uint]

        display = x11.XOpenDisplay(self.display_name.encode())
        if not display:
            return
        root = x11.XDefaultRootWindow(display)
        for _ in range(self.attempts):
            window = self._largest(x11, display, root)
            if window:
                x11.XMoveResizeWindow(display, window, 0, 0, self.width, self.height)
                x11.XFlush(display)
                return
            time.sleep(self.interval)

    @staticmethod
    def _largest(x11, display, root):
        root_ret, parent_ret = ctypes.c_ulong(), ctypes.c_ulong()
        children, count = ctypes.POINTER(ctypes.c_ulong)(), ctypes.c_uint()
        if not x11.XQueryTree(display, root, ctypes.byref(root_ret), ctypes.byref(parent_ret),
                              ctypes.byref(children), ctypes.byref(count)):
            return None
        best, best_area = None, 0
        for i in range(count.value):
            window = children[i]
            r, x, y = ctypes.c_ulong(), ctypes.c_int(), ctypes.c_int()
            w, h = ctypes.c_uint(), ctypes.c_uint()
            bw, depth = ctypes.c_uint(), ctypes.c_uint()
            if not x11.XGetGeometry(display, window, ctypes.byref(r), ctypes.byref(x), ctypes.byref(y),
                                    ctypes.byref(w), ctypes.byref(h), ctypes.byref(bw), ctypes.byref(depth)):
                continue
            if w.value > 200 and h.value > 200 and w.value * h.value > best_area:
                best, best_area = window, w.value * h.value
        return best


class FrameGrabber:
    """常驻一个 ffmpeg 抓 X11 画面，把最新一帧 JPEG 留在内存里给 HTTP 取用。"""

    def __init__(self, display, width, height, fps, ffmpeg=None):
        self.cmd = [
            find_ffmpeg(ffmpeg), "-loglevel", "error", "-f", "x11grab",
            "-video_size", f"{width}x{height}", "-i", display,
            "-r", str(fps), "-f", "mjpeg", "-q:v", "5", "-",
        ]
        self._lock = threading.Lock()
        self._frame = None
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            proc = subprocess.Popen(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            buf = b""
            try:
                while True:
                    chunk = proc.stdout.read1(65536)
                    if not chunk:
                        break
                    buf += chunk
                    while True:
                        start = buf.find(JPEG_SOI)
                        if start < 0:
                            buf = buf[-1:]
                            break
                        end = buf.find(JPEG_EOI, start + 2)
                        if end < 0:
                            buf = buf[start:]
                            break
                        frame = buf[start:end + 2]
                        with self._lock:
                            self._frame = frame
                        buf = buf[end + 2:]
            finally:
                proc.kill()
                proc.wait()
            time.sleep(0.5)

    def latest(self):
        with self._lock:
            return self._frame


class Pointer:
    """通过 XTEST 在目标 X display 上合成鼠标事件。"""

    WHEEL_UP, WHEEL_DOWN = 4, 5

    def __init__(self, display, width, height):
        self.width, self.height = width, height
        self.x11 = ctypes.CDLL("libX11.so.6")
        self.xtst = ctypes.CDLL("libXtst.so.6")
        self.x11.XOpenDisplay.restype = ctypes.c_void_p
        self.x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x11.XFlush.argtypes = [ctypes.c_void_p]
        self.xtst.XTestFakeMotionEvent.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
        self.xtst.XTestFakeButtonEvent.argtypes = [
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        self.display = self.x11.XOpenDisplay(display.encode())
        if not self.display:
            raise RuntimeError("无法打开 X display: " + display)
        self._lock = threading.Lock()

    def _clamp(self, x, y):
        return (max(0, min(self.width - 1, int(x))), max(0, min(self.height - 1, int(y))))

    def move(self, x, y):
        x, y = self._clamp(x, y)
        with self._lock:
            self.xtst.XTestFakeMotionEvent(self.display, -1, x, y, 0)
            self.x11.XFlush(self.display)

    def button(self, button, down):
        with self._lock:
            self.xtst.XTestFakeButtonEvent(self.display, button, 1 if down else 0, 0)
            self.x11.XFlush(self.display)

    def click(self, button):
        self.button(button, True)
        self.button(button, False)


class BridgeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    grabber = None
    pointer = None
    page = b""

    def log_message(self, *args):
        pass

    def _reply(self, code, ctype, body, cache=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if cache:
            self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/":
            self._reply(200, "text/html; charset=utf-8", self.page, "no-store")
        elif url.path == "/frame.jpg":
            frame = self.grabber.latest()
            if frame is None:
                self._reply(503, "text/plain; charset=utf-8", b"no frame yet", "no-store")
            else:
                self._reply(200, "image/jpeg", frame, "no-store")
        elif url.path == "/healthz":
            self._reply(200, "text/plain; charset=utf-8", b"ok")
        elif url.path == "/input":
            self._handle_input(parse_qs(url.query))
        else:
            self._reply(404, "text/plain; charset=utf-8", b"not found")

    def _handle_input(self, query):
        try:
            kind = query.get("t", [""])[0]
            x = float(query.get("x", ["0"])[0])
            y = float(query.get("y", ["0"])[0])
            button = int(query.get("b", ["1"])[0])
        except ValueError:
            self._reply(400, "text/plain; charset=utf-8", b"bad request")
            return

        if kind == "move":
            self.pointer.move(x, y)
        elif kind == "down":
            self.pointer.move(x, y)
            self.pointer.button(button, True)
        elif kind == "up":
            self.pointer.move(x, y)
            self.pointer.button(button, False)
        elif kind == "wheel":
            self.pointer.move(x, y)
            delta = int(query.get("d", ["1"])[0])
            self.pointer.click(Pointer.WHEEL_UP if delta > 0 else Pointer.WHEEL_DOWN)
        else:
            self._reply(400, "text/plain; charset=utf-8", b"unknown input type")
            return
        self._reply(200, "text/plain; charset=utf-8", b"ok")


def main():
    parser = argparse.ArgumentParser(description="EGO-Planner 仿真预览桥")
    parser.add_argument("--display", default=":99")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--fps", type=int, default=4)
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--ffmpeg", default=None, help="指定支持 x11grab 的 ffmpeg 路径")
    parser.add_argument("--no-fit-window", action="store_true", help="不把最大窗口拉到整屏")
    args = parser.parse_args()

    BridgeHandler.grabber = FrameGrabber(args.display, args.width, args.height, args.fps, args.ffmpeg)
    if not args.no_fit_window:
        WindowFitter(args.display, args.width, args.height).start()
    BridgeHandler.pointer = Pointer(args.display, args.width, args.height)
    BridgeHandler.page = PAGE.replace("__W__", str(args.width)).replace("__H__", str(args.height)).encode()

    server = ThreadingHTTPServer((args.host, args.port), BridgeHandler)
    server.daemon_threads = True
    print("预览桥已就绪: http://%s:%d (display=%s %dx%d @%dfps)"
          % (args.host, args.port, args.display, args.width, args.height, args.fps), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
