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
- 语言：C++（C++11/14，Release 构建 `-O3`）
- 构建：**ROS1 catkin**（`catkin_make`），顶层 `src/CMakeLists.txt` 是指向
  `/opt/ros/kinetic/share/catkin/cmake/toplevel.cmake` 的符号链接，属正常结构
- 依赖：ROS（roscpp / std_msgs / geometry_msgs / tf / pcl_ros 等）、Eigen3、PCL ≥1.7、
  Armadillo（`libarmadillo-dev`，uav_simulator 需要）；可选 CUDA（local_sensing 渲染深度图）
- 运行形态：ROS 节点 + rviz 可视化，**无 HTTP 服务、无前端**

## 目录结构
```
src/
├── CMakeLists.txt          # catkin toplevel 软链，勿动
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
  - `src/planner/plan_manage/launch/run_in_sim.launch`（仿真跑规划器）
  - `src/planner/plan_manage/launch/simple_run.launch`（3 分钟快速上手）

## 关键入口 / 核心模块
- 规划主流程：`ego_planner_node.cpp` → `ego_replan_fsm.cpp`（状态机）→
  `planner_manager.cpp` → `bspline_opt` 优化
- 地图与避障：`plan_env/grid_map.cpp` + `raycast.cpp`（以 raycast 代价替代 ESDF 构建）
- 前端搜索：`path_searching/dyn_a_star.cpp`

## 运行与预览
- 本工作区**不可预览**（`preview_enable = "disabled"`）：产物是 ROS 节点 + rviz GUI，
  依赖 ROS1 运行时与图形界面，平台预览链路不适用。同时 `.coze` 不写 `[dev]`、不生成 `.preview`。
- 本沙箱内**也暂不具备编译/运行条件**：未安装 ROS、`catkin_make`、CMake（仅存在 `g++`）。
  需要真实运行请在具备 ROS 环境的机器上操作，步骤见 `README.md`：
  ```
  sudo apt-get install libarmadillo-dev
  cd <repo root> && catkin_make -DCMAKE_BUILD_TYPE=Release
  source devel/setup.bash
  roslaunch ego_planner rviz.launch          # 终端 A
  roslaunch ego_planner run_in_sim.launch    # 终端 B
  ```
- `.coze`：`project_type = ""`（ROS/C++ 桌面仿真工程，不属于已支持的 web/小程序/App/后端类型）；
  单层结构，`[subprojects].path = ["."]`，根 `.coze` 兼子项目 `.coze`。

## 用户偏好与长期约束
- 保持上游仓库原貌，不做无关的重构或目录改造；需要改动时按 catkin 包结构就地修改。
- 包管理器约定：Node 侧用 `pnpm`、Python 侧用 `uv`（当前仓库均未涉及）。

## 常见问题和预防
- `src/CMakeLists.txt` 是软链，若在 Windows/无 ROS 环境解压会变成断链或空文件，
  报错时先确认 `/opt/ros/<distro>/share/catkin/cmake/toplevel.cmake` 是否存在。
- `catkin_make` 必须在仓库根执行，且构建产物 `build/`、`devel/` 已加入 `.gitignore`，不要提交。
- `local_sensing` 默认 CPU 版；启用 GPU 需改其 `CMakeLists.txt` 中 `set(ENABLE_CUDA true)`
  并同步调整 `CUDA_NVCC_FLAGS` 的 arch/code，改动前先确认本机 CUDA 版本。
- 不建议在无 ROS 的环境尝试编译本仓库，缺少 ros/roscpp 会导致 CMake 配置阶段直接失败。
