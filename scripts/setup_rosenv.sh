#!/usr/bin/env bash
# EGO-Planner 本地 ROS 环境一键安装 / 恢复
#
# 做四件事：
#   1. 在工作区内的 .deps/ 下准备好 conda(RoboStack) ROS Noetic 环境
#      （.deps/ 被 .gitignore 忽略，不进仓库）
#   2. 核对环境完整性：文件缺失就就地 --force-reinstall 修复，环境没了才重新创建
#   3. 修复 ROS1 消息生成所需的 empy 版本（必须是 3.3.x）
#   4. 默认清掉失效的构建产物并重新 catkin_make
#
# 三种状态都能一条命令恢复：
#   环境完好            -> 秒过
#   环境被清掉一部分    -> 只重装缺失的包（沙箱回收常清掉 site-packages）
#   环境整个没了        -> 完整重建（约 10 分钟 / 1 G 下载）
#
# 磁盘：沙箱总容量只有 ~9.8 G，写满会让沙箱停止工作。本脚本是磁盘消耗最大的操作，
#       因此内置了每步动手前的磁盘预检（不足直接中止）和装完后的包缓存回收。
#
# 用法：
#   bash scripts/setup_rosenv.sh              # 装环境 + 编译
#   bash scripts/setup_rosenv.sh --no-build   # 只装环境，不编译
#   bash scripts/setup_rosenv.sh --force      # 删掉现有环境重装
#
# 装好后激活环境：
#   source .deps/ros-env.sh

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DEPS_DIR="$PROJECT_DIR/.deps"
PREFIX="$DEPS_DIR/rosenv"
MAMBA="$DEPS_DIR/micromamba"
ENV_SCRIPT="$DEPS_DIR/ros-env.sh"
export MAMBA_ROOT_PREFIX="$DEPS_DIR/mamba-root"

CHANNELS=(-c robostack-staging -c conda-forge)
PACKAGES=(
  ros-noetic-desktop
  compilers cmake make ninja pkg-config
  ros-noetic-cmake-modules ros-noetic-pcl-ros ros-noetic-cv-bridge
  ros-noetic-image-transport ros-noetic-laser-geometry ros-noetic-nodelet
  ros-noetic-dynamic-reconfigure ros-noetic-tf
  armadillo
)
EMPY_VERSION='empy=3.3.4'

DO_BUILD=1
FORCE=0

usage() {
  sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

for arg in "$@"; do
  case "$arg" in
    --no-build) DO_BUILD=0 ;;
    --force)    FORCE=1 ;;
    -h|--help)  usage; exit 0 ;;
    *) echo "未知参数：$arg（用 --help 看用法）" >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
die()  { echo "错误：$1" >&2; exit 1; }

# 沙箱磁盘总容量只有 ~9.8 G，写满会直接让沙箱停止工作。
# conda 是本项目最大的磁盘消耗方，所以每一步动手前都先算余量。
avail_mib() { df -Pk "$1" | awk 'NR==2 {print int($4/1024)}'; }
require_disk() { # $1=所需 MiB  $2=要干的事
  local have; have="$(avail_mib "$PROJECT_DIR")"
  if [ "$have" -lt "$1" ]; then
    die "磁盘可用仅 ${have} MiB，不足「$2」所需的 ${1} MiB。把磁盘写满会导致沙箱停止工作。
     先清理后重试：rm -rf build devel install、\$MAMBA clean -a -y、清空 /workspace/logs/*.log"
  fi
  echo "磁盘可用 ${have} MiB，满足「$2」（需 ${1} MiB）"
}

# ---------- 0. 确保 .deps/ 不被 git 追踪 ----------
mkdir -p "$DEPS_DIR"
if ! grep -qx '\.deps/' "$PROJECT_DIR/.gitignore" 2>/dev/null; then
  printf '\n# 本地依赖（conda ROS 环境等），放在工作区内以免沙箱重建被清除\n.deps/\n' >> "$PROJECT_DIR/.gitignore"
  echo "已把 .deps/ 追加到 .gitignore"
fi

# ---------- 1. micromamba ----------
if [ ! -x "$MAMBA" ]; then
  step "下载 micromamba"
  command -v curl >/dev/null || die "需要 curl 来下载 micromamba"
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  curl -fsSL https://micro.mamba.pm/api/micromamba/linux-64/latest -o "$tmp/mm.tar.bz2" \
    || die "micromamba 下载失败（检查网络）"
  tar -xjf "$tmp/mm.tar.bz2" -C "$DEPS_DIR" --strip-components=1 bin/micromamba \
    || die "micromamba 解包失败"
  rm -rf "$tmp"; trap - EXIT
fi
echo "micromamba: $("$MAMBA" --version)"

# ---------- 2. conda 环境 ----------
CREATED=0
if [ "$FORCE" = 1 ] && [ -d "$PREFIX" ]; then
  step "删除现有环境（--force）"
  rm -rf "$PREFIX"
fi

# 沙箱回收会清掉环境里的**部分**文件（实测 `lib/python3.12/site-packages/` 整个目录被清，
# 108321 个文件里丢了 19262 个 / 17.8%，涉及 199 个包）。只判断目录是否存在会漏掉这种
# “半损”状态——环境看着在、命令能跑，但 empy/rospy/rospkg 全 import 不了。
# 所以按 conda-meta 各包的 files 清单逐个核对真实文件。
damaged_packages() { # 输出文件缺失的包名，每行一个
  [ -x "$PREFIX/bin/python" ] || return 0
  local py; py="$(command -v python3 || echo "$PREFIX/bin/python")"
  "$py" - "$PREFIX" <<'PY' 2>/dev/null || true
import json, glob, os, sys
os.chdir(sys.argv[1])
for f in glob.glob('conda-meta/*.json'):
    d = json.load(open(f))
    files = d.get('files') or []
    if files and any(not os.path.lexists(p) for p in files):
        print(d['name'])
PY
}

if [ -x "$PREFIX/bin/python" ] && [ -f "$PREFIX/setup.bash" ]; then
  DAMAGED="$(damaged_packages)"
  N_DAMAGED="$(printf '%s' "$DAMAGED" | grep -c . || true)"
  if [ "$N_DAMAGED" -gt 0 ]; then
    step "环境有 $N_DAMAGED 个包的文件缺失（沙箱回收常清掉 site-packages），就地修复"
    require_disk 4000 "修复环境"
    # shellcheck disable=SC2086
    "$MAMBA" install -y -p "$PREFIX" "${CHANNELS[@]}" --force-reinstall $DAMAGED
    CREATED=1
    REMAIN="$(damaged_packages | grep -c . || true)"
    [ "$REMAIN" = 0 ] \
      || die "修复后仍有 $REMAIN 个包文件缺失，请重装：bash scripts/setup_rosenv.sh --force"
    echo "环境已修复且完整"
  else
    echo "conda 环境已存在且完整：$PREFIX"
  fi
else
  step "创建 conda 环境（约 10 分钟 / 1 G 下载）"
  require_disk 7000 "创建 conda 环境"
  "$MAMBA" create -y -p "$PREFIX" "${CHANNELS[@]}" "${PACKAGES[@]}"
  CREATED=1
fi

# ---------- 3. empy 必须是 3.3.x ----------
# empy 是纯 Python 包，优先用 pip 装：比走 conda 求解快得多，也不会卡在 conda-forge
# 分片索引上（实测 conda 那条路会长时间停在 Fetching and Parsing Packages' Shards）。
empy_ok() { "$PREFIX/bin/python" -c 'import em,sys; sys.exit(0 if em.__version__.startswith("3.") else 1)' 2>/dev/null; }
if empy_ok; then
  echo "empy: $("$PREFIX/bin/python" -c 'import em; print(em.__version__)')"
else
  step "把 empy 降到 3.3.4（empy 4.x 会让 ROS1 消息生成报 RAW_OPT 错误）"
  require_disk 3000 "降级 empy"
  if [ -x "$PREFIX/bin/pip" ]; then
    "$PREFIX/bin/pip" install -q --disable-pip-version-check --root-user-action=ignore 'empy==3.3.4'
    # pip 装的 empy 会覆盖 conda 那份，conda 的文件清单就对不上了；删掉 conda 的 empy
    # 元数据，免得下面的完整性核对把它误判成"文件缺失"而反复触发修复。
    rm -f "$PREFIX"/conda-meta/empy-*.json
  else
    "$MAMBA" install -y -p "$PREFIX" "${CHANNELS[@]}" "$EMPY_VERSION"
    CREATED=1
  fi
  empy_ok || die "empy 降级失败，请检查网络后重试"
  echo "empy: $("$PREFIX/bin/python" -c 'import em; print(em.__version__)')"
fi

# 包缓存会临时占掉与整个环境相当的空间，装完立刻回收
if [ "$CREATED" = 1 ]; then
  step "清理 conda 包缓存"
  before="$(avail_mib "$PROJECT_DIR")"
  "$MAMBA" clean -a -y >/dev/null
  echo "回收 $(($(avail_mib "$PROJECT_DIR") - before)) MiB，当前可用 $(avail_mib "$PROJECT_DIR") MiB"
fi

# ---------- 4. 激活脚本 ----------
cat > "$ENV_SCRIPT" <<EOF
#!/usr/bin/env bash
# 由 scripts/setup_rosenv.sh 生成，勿手工修改
# 用法： source .deps/ros-env.sh
export MAMBA_ROOT_PREFIX="$DEPS_DIR/mamba-root"
eval "\$("$MAMBA" shell hook -s bash)"
micromamba activate "$PREFIX"
if [ -f "$PROJECT_DIR/devel/setup.bash" ]; then
  source "$PROJECT_DIR/devel/setup.bash"
fi
EOF
chmod +x "$ENV_SCRIPT"
echo "激活脚本：$ENV_SCRIPT"

# ---------- 5. 构建 ----------
if [ "$DO_BUILD" = 1 ]; then
  STALE=0
  if [ ! -f "$PROJECT_DIR/build/CMakeCache.txt" ]; then
    STALE=1
  elif ! grep -qF "$PREFIX" "$PROJECT_DIR/build/CMakeCache.txt"; then
    STALE=1
  fi

  if [ "$CREATED" = 1 ] || [ "$STALE" = 1 ]; then
    step "清理失效构建产物并 catkin_make"
    require_disk 2000 "catkin_make"
    # 这一步必须做：旧的 devel/setup.bash 指向已消失的旧环境，source 它会把 PATH 洗掉
    rm -rf "$PROJECT_DIR/build" "$PROJECT_DIR/devel" "$PROJECT_DIR/install"
    # shellcheck disable=SC1090
    source "$ENV_SCRIPT"
    ( cd "$PROJECT_DIR" && catkin_make -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -j"$(nproc)" )
  else
    echo "构建产物对应当前环境，跳过编译"
  fi
fi

# ---------- 6. 自检 ----------
step "自检"
( set +e
  source "$ENV_SCRIPT"
  echo "ROS_DISTRO = $ROS_DISTRO"
  echo "rospack    = $(command -v rospack || echo '未找到')"
  echo "ego_planner= $(rospack find ego_planner 2>/dev/null || echo '未找到')"
  echo "empy       = $("$PREFIX/bin/python" -c 'import em; print(em.__version__)' 2>/dev/null)"
  if [ -x "$PROJECT_DIR/devel/lib/ego_planner/ego_planner_node" ]; then
    echo "可执行文件  = devel/lib/ego_planner/ego_planner_node 已就绪"
  fi
)

cat <<EOF

完成。接下来：

  source $ENV_SCRIPT
  cd $PROJECT_DIR
  roslaunch ego_planner run_in_sim.launch

该 launch 不带 rviz，需要另发目标点触发飞行：

  rostopic pub -1 /move_base_simple/goal geometry_msgs/PoseStamped \\
    '{header: {frame_id: "world"}, pose: {position: {x: 15.0, y: 0.0, z: 1.0}, orientation: {w: 1.0}}}'

要 rviz 可视化（沙箱无 X server 时）：

  xvfb-run -a -s "-screen 0 1280x1024x24" roslaunch ego_planner simple_run.launch
EOF
