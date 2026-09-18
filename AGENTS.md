# AGENTS.md

## 项目概述
本工作区是浙江大学 FAST-Lab（高飞团队）开源的 **EGO-Planner** —— 面向四旋翼无人机的
「无 ESDF 的梯度式局部轨迹规划器」（RA-L 论文配套实现）。

- 来源：`https://github.com/ZJU-FAST-Lab/ego-planner`（upstream 远端）
- 克隆基线 commit：`bfda51284c8c1b476043255a8145ef925a3778a5`（2025-03-08）
- 补充说明：官方推荐同时考虑其演进版 EGO-Swarm（`ZJU-FAST-Lab/ego-planner-swarm`），
  单机场景把 `drone_id` 设为 `0` 即可；ROS2 版本也在该仓库的 `ros2_version` 分支。
- 注意：`origin` 指向使用者自己的仓库（`destroyer-c/ego-planner-research`），
  日常提交推 `origin`，同步上游用 `git fetch upstream`。

## 技术栈
- 语言：C++（原版 C++11/14，**本工作区已统一提升到 C++17**，见「兼容性改动」）
- 构建：**ROS1 catkin**（`catkin_make`），顶层 `src/CMakeLists.txt` 是指向
  `/opt/ros/<distro>/share/catkin/cmake/toplevel.cmake` 的符号链接，属正常结构
- 依赖：ROS（roscpp / std_msgs / geometry_msgs / tf / pcl_ros / cv_bridge / rviz 等）、
  Eigen3、PCL、Armadillo（uav_simulator 需要）；可选 CUDA（local_sensing 渲染深度图）
- 运行形态：ROS 节点 + rviz 可视化，**无 HTTP 服务、无前端**

## 目录结构
```
src/
├── CMakeLists.txt          # catkin toplevel 软链，勿动（每次 catkin_make 会被重写）
├── planner/                # 规划器核心
│   ├── plan_manage/        # 入口节点与状态机：ego_planner_node / ego_replan_fsm /
│   │                       #   planner_manager / traj_server；launch 文件在此
│   ├── plan_env/           # 栅格地图与 raycast（无 ESDF 的关键）
│   ├── path_searching/     # 动力学 A*（dyn_a_star）
│   ├── bspline_opt/        # B 样条优化（含 LBFGS-Lite 头文件）
│   └── traj_utils/         # 轨迹与可视化工具
└── uav_simulator/          # 仿真环境（map_generator / mockamap / local_sensing /
                            #   so3_control / so3_quadrotor_simulator / Utils）
```
- launch 共 9 个，主要入口：
  - `src/planner/plan_manage/launch/rviz.launch`（可视化与交互）
  - `src/planner/plan_manage/launch/run_in_sim.launch`（仿真跑规划器，flight_type=1，需给目标点）
  - `src/planner/plan_manage/launch/simple_run.launch`（3 分钟快速上手，flight_type=2，含 rviz）

## 关键入口 / 核心模块
- 规划主流程：`ego_planner_node.cpp` → `ego_replan_fsm.cpp`（状态机）→
  `planner_manager.cpp` → `bspline_opt` 优化
- 地图与避障：`plan_env/grid_map.cpp` + `raycast.cpp`（以 raycast 代价替代 ESDF 构建）
- 前端搜索：`path_searching/dyn_a_star.cpp`

## 运行与预览

### 本地 ROS 环境（conda / RoboStack，已装好）
不用系统 apt 装 ROS，全部走 conda，环境在 `/workspace/projects/.deps/rosenv`：

```bash
source /workspace/projects/.deps/ros-env.sh   # 激活 ROS Noetic 环境 + source devel/setup.bash
```
- 依赖全部落在工作区内的 **`.deps/`**，**已被 `.gitignore` 忽略**（不进仓库）。
  放这里是为了沙箱重建时不被清除——`/workspace` 下项目外的目录曾整体丢失过：
  - conda 环境：`.deps/rosenv`（ROS Noetic + compilers/cmake/armadillo，约 5.4 G）
  - micromamba：`.deps/micromamba`；`MAMBA_ROOT_PREFIX`：`.deps/mamba-root`（缓存，可丢）
  - 激活脚本：`.deps/ros-env.sh`
- ROS 发行版：Noetic（`ROS_DISTRO=noetic`），编辑器为 conda-forge GCC 15.3
- 已显式降级 `empy` 到 **3.3.4**（ROS1 消息生成不兼容 empy 4.x，会报
  `module 'em' has no attribute 'RAW_OPT'`）
- 手动激活等价写法：
  `export MAMBA_ROOT_PREFIX=/workspace/projects/.deps/mamba-root;`
  `eval "$(/workspace/projects/.deps/micromamba shell hook -s bash)";`
  `micromamba activate /workspace/projects/.deps/rosenv`
- **环境丢失后的重建**：`.deps/` 若被清掉，按下面命令重装（约 10 分钟，1 G 下载）：
  ```bash
  .deps/micromamba create -y -p .deps/rosenv -c robostack-staging -c conda-forge \
    ros-noetic-desktop compilers cmake make ninja pkg-config \
    ros-noetic-cmake-modules ros-noetic-pcl-ros ros-noetic-cv-bridge \
    ros-noetic-image-transport ros-noetic-laser-geometry ros-noetic-nodelet \
    ros-noetic-dynamic-reconfigure ros-noetic-tf armadillo
  .deps/micromamba install -y -p .deps/rosenv -c conda-forge 'empy=3.3.4'
  ```
  重建后必须 `rm -rf build devel install` 再 `catkin_make`：旧的 `devel/setup.bash`
  指向失效的旧环境路径，会让激活后的 `PATH` 异常。

### 构建
```bash
source /workspace/projects/.deps/ros-env.sh
cd /workspace/projects
catkin_make -DCMAKE_BUILD_TYPE=Release -DCMAKE_POLICY_VERSION_MINIMUM=3.5
```
- `-DCMAKE_POLICY_VERSION_MINIMUM=3.5` **必须带**：conda 的 CMake 4.x 已移除对
  `cmake_minimum_required(VERSION 2.8.3)` 的兼容，不带会直接配置失败。
- 首次完整构建约 5 分钟（4 核）。产物在 `build/`、`devel/`（已 gitignore）。
- `catkin_make` 会重写 `src/CMakeLists.txt` 软链指向 conda 的 catkin toplevel，
  **这是本地行为，不要提交该文件**（每次构建都会再变）。

### 运行（本沙箱已验证可跑）
无头仿真（不需要显示器）：
```bash
source /workspace/projects/.deps/ros-env.sh
roslaunch ego_planner run_in_sim.launch
```
该 launch 不带 rviz，`flight_type=1` 需要外部给目标点：
```bash
rostopic pub -1 /move_base_simple/goal geometry_msgs/PoseStamped \
  '{header: {frame_id: "world"}, pose: {position: {x: 15.0, y: 0.0, z: 1.0}, orientation: {w: 1.0}}}'
```
带 rviz 可视化（沙箱无 X server，用 Xvfb 跑）：
```bash
source /workspace/projects/.deps/ros-env.sh
xvfb-run -a -s "-screen 0 1280x1024x24" roslaunch ego_planner simple_run.launch
```
有真实图形界面时按 README 开两个终端分别跑 `rviz.launch` 与 `run_in_sim.launch` 即可。

### 预览 / 部署
- 平台预览不可用（`preview_enable = "disabled"`）：产物是 ROS 节点 + rviz GUI，
  预览链路只面向 web/小程序/App 类产物，不适用。`.coze` 不写 `[dev]`、不生成 `.preview`。
- 平台部署不支持：仓库没有任何可支撑部署的入口（无 HTTP 服务、无 package.json /
  requirements.txt 等），故 `.coze` 不写 `[deploy]`。
- `.coze`：`project_type = ""`（ROS/C++ 桌面仿真工程，不属于已支持的 web/小程序/App/后端类型）；
  单层结构，`[subprojects].path = ["."]`，根 `.coze` 兼子项目 `.coze`。

## 兼容性改动（让 2020 年代的代码在 conda 现代工具链上编译）
以下改动是为了在 GCC 15 / CMake 4 / PCL 1.15 / Ogre 1.12+ / 新 libstdc++ 下能编过，
不属于业务逻辑变更：
1. **C++ 标准 `-std=c++11/14` → `-std=c++17`**：改了 14 个包的 `CMakeLists.txt`。
   原因：conda-forge PCL 1.15 在 `pcl_config.h` 里硬性要求 `__cplusplus >= 201703L`。
2. `src/uav_simulator/Utils/multi_map_server/CMakeLists.txt:167`：
   `add_dependencies` 引用了不存在的目标 `multi_map_server_messages_cpp`，
   改为真实的 `multi_map_server_generate_messages_cpp`（否则 CMake 4 生成阶段报错）。
3. `src/planner/bspline_opt/include/bspline_opt/gradient_descent_optimizer.h`：
   `int iter_limit_{1e10}` 大括号初始化存在 double→int 窄化（C++11 起是硬错误），
   改为 `std::numeric_limits<int>::max()`（补 `#include <limits>`）。
4. `src/uav_simulator/mockamap/src/ces_randommap.cpp`：补 `#include <deque>`
   （新 libstdc++ 不再传递包含，报 `'deque' does not name a type`）。
5. `src/uav_simulator/Utils/rviz_plugins/src/{probmap,aerialmap,multi_probmap}_display.cpp`：
   补 `#include <OGRE/OgreTechnique.h>`（Ogre 1.12+ 不再传递包含 `Ogre::Technique`）。

## 用户偏好与长期约束
- 保持上游仓库原貌，不做无关的重构或目录改造；需要改动时按 catkin 包结构就地修改。
- 包管理器约定：Node 侧用 `pnpm`、Python 侧用 `uv`；本仓库 C++ 侧依赖统一走 conda（不用 apt 装 ROS）。

## 常见问题和预防
- `src/CMakeLists.txt` 是软链，若在 Windows/无 ROS 环境解压会变成断链或空文件；
  `catkin_make` 会自动重写它，报错时先确认 conda 里 `share/catkin/cmake/toplevel.cmake` 存在。
- `catkin_make` 必须在仓库根执行，构建产物 `build/`、`devel/` 已加入 `.gitignore`，不要提交。
- `catkin_make` 报 `Compatibility with CMake < 3.5 has been removed` → 忘记加
  `-DCMAKE_POLICY_VERSION_MINIMUM=3.5`。
- 消息生成阶段报 `module 'em' has no attribute 'RAW_OPT'` → empy 被升级到 4.x 了，
  重新 `micromamba install -p /workspace/projects/.deps/rosenv -c conda-forge 'empy=3.3.4'`。
- `local_sensing/package.xml` 里声明了 `svo_msgs` / `vikit_ros`，但代码和 CMake 都没用到
  （历史残留），当前不影响 catkin_make；如遇相关依赖报错可确认后忽略。
- `local_sensing` 默认 CPU 版；启用 GPU 需改其 `CMakeLists.txt` 中 `set(ENABLE_CUDA true)`
  并同步调整 `CUDA_NVCC_FLAGS` 的 arch/code，改动前先确认本机 CUDA 版本。
- 磁盘：conda 环境约 5.4 G（`/workspace/projects/.deps/rosenv`）。空间紧张时用
  `/workspace/projects/.deps/micromamba clean -a -y` 清包缓存。
