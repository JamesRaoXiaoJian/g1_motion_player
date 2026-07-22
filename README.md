# G1 Motion Player

```bash
git clone --recurse-submodules https://github.com/JamesRaoXiaoJian/g1_motion_player.git
cd g1_motion_player
```

已有仓库更新主项目和子模块：

```bash
git pull --recurse-submodules origin main
git submodule update --init --recursive
```

<p align="center">
  <a href="README.md">中文</a> · <a href="README_EN.md">English</a>
</p>

Unitree G1 CSV 动作回放工具。项目提供 ROS 2 Docker、Unitree SDK2 C++ 和 FastAPI 三种使用入口，用于校验、保存和安全回放 G1 上肢动作。

> [!WARNING]
> 真实回放会控制机器人双臂和腰部。执行前必须确保机器人稳定、周围无人和障碍物，并准备好急停。ROS 2 与 SDK2 回放程序不能同时运行。

## 目录

- [项目概览](#项目概览)
- [目录结构](#目录结构)
- [快速开始](#快速开始)
  - [路径一：ROS 2 Docker（推荐）](#路径一ros-2-docker推荐)
  - [路径二：原生 SDK2 C++](#路径二原生-sdk2-c)
  - [路径三：FastAPI](#路径三fastapi)
- [CSV 格式](#csv-格式)
- [回放安全策略](#回放安全策略)
- [测试](#测试)
- [常见问题](#常见问题)
- [扩展文档](#扩展文档)

## 项目概览

当前主分支聚焦 CSV 动作执行：

- **ROS 2 回放**：`csv_replay_ros2` 订阅 `/lowstate`，向 `/arm_sdk` 发布 `unitree_hg/msg/LowCmd`。
- **SDK2 回放**：`csv_replay` 通过 Unitree SDK DDS 直接使用 `rt/arm_sdk`。
- **HTTP 接口**：FastAPI 提供 `POST /api/replay`，接收、校验和保存 CSV，并可调用 SDK2 回放程序。
- **辅助工具**：包含状态记录、连接测试、CSV 校验和示例动作。
- **示例数据**：`assets/wave.csv`、`assets/zuoyi.csv`。

默认行为以安全为先：ROS 2 回放不带 `--execute` 时只校验；HTTP 接口默认 `dry_run=true`。

之前的动作查询、创建、更新及 JSON replay 版本保存在远端分支 `api-json-replay-archive`，主分支不再构建 `json_replay`。

## 目录结构

```text
g1_motion_player/
├── api/
│   ├── main.py                    # FastAPI: POST /api/replay
│   └── csv_motion.py              # CSV 校验与元数据解析
├── assets/                        # 示例和上传的 CSV 动作
├── docker/foxy/                   # ROS 2 Foxy 辅助脚本
├── docs/                          # 部署与接口详细文档
├── src/
│   ├── ros2/csv_replay_ros2.cpp   # ROS 2 回放程序
│   ├── csv_replay.cpp             # SDK2 回放程序
│   ├── state_recorder.cpp
│   └── test_connection.cpp
├── tests/
├── thirdparty/
│   ├── unitree_sdk2/              # Git submodule
│   └── unitree_ros2/              # Git submodule
├── build_foxy_docker.sh
└── run_foxy_docker.sh
```

## 快速开始

本项目有三条独立使用路径。机器人控制开发推荐 ROS 2 Docker；部署已有 SDK2 程序可选原生 C++；只需要上传和校验动作时使用 FastAPI。

### 路径一：ROS 2 Docker（推荐）

Docker 固定使用 Ubuntu 20.04、ROS 2 Foxy 和 CycloneDDS 0.10.2，宿主机不需要安装 Foxy。

#### 1. 安装 Docker

```bash
sudo apt update
sudo apt install -y docker.io
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
newgrp docker
docker version
```

#### 2. 构建镜像和 ROS 2 工作区

```bash
./build_foxy_docker.sh
```

该脚本执行两件事：

1. 构建包含 Foxy、CycloneDDS 和编译工具的 Docker 镜像。
2. 在临时容器中编译 Unitree 消息、示例及 `csv_replay_ros2`，产物保存到宿主机 `.foxy/install/`。

修改 `src/ros2/` 后必须重新编译；`run_foxy_docker.sh` 只加载已有产物，不会自动构建。

#### 3. 启动开发容器

默认通信网卡为 `wlo1`：

```bash
./run_foxy_docker.sh
```

使用其他网卡：

```bash
UNITREE_NET_IFACE=eth0 ./run_foxy_docker.sh
```

#### 4. 检查机器人通信

以下命令在容器内执行：

```bash
ros2 topic list
ros2 topic echo /lowstate unitree_hg/msg/LowState
python3 docker/foxy/measure_lowstate_rate.py --duration 10
python3 docker/foxy/read_upper_body.py --include-waist
```

#### 5. 校验并回放 CSV

先做无控制校验：

```bash
ros2 run g1_motion_player_ros2 csv_replay_ros2 assets/wave.csv
```

确认机器人和环境安全后执行：

```bash
ros2 run g1_motion_player_ros2 csv_replay_ros2 assets/wave.csv --execute
```

自定义帧率：

```bash
ros2 run g1_motion_player_ros2 csv_replay_ros2 \
  assets/wave.csv --fps 50 --execute
```

完整环境配置、增量编译和网络排障见 [ROS 2 Docker 开发指南](docs/ros2_docker.md)。

### 路径二：原生 SDK2 C++

适用于 G1 PC2 或同一机器人网段中的 Ubuntu x86_64/aarch64 主机。

#### 1. 安装依赖

```bash
sudo apt-get update
sudo apt-get install -y \
  git cmake g++ build-essential pkg-config
```

#### 2. 编译

```bash
cmake -S . -B build
cmake --build build -j"$(nproc)"
```

主要产物：

```text
build/csv_replay
build/state_recorder
build/test_connection
```

#### 3. 检查连接并回放

先确认机器人通信网卡：

```bash
ip -brief address
./build/test_connection eth0
```

回放命令：

```bash
./build/csv_replay <csv文件> [fps] [网卡]
```

示例：

```bash
./build/csv_replay assets/wave.csv 50 eth0
./build/csv_replay assets/zuoyi.csv 50 eth0
```

默认回放频率为 50 Hz。若需保持 600 帧动作按 10 秒播放，可指定 `fps=60`。

> [!IMPORTANT]
> `build/csv_replay` 是 SDK2 程序，`.foxy/install/.../csv_replay_ros2` 是 ROS 2 程序。两者使用不同构建环境，但最终都会占用 `arm_sdk` 控制链路，禁止同时启动。

### 路径三：FastAPI

FastAPI 接收请求中的 CSV，完成校验、保存，并根据 `dry_run` 决定是否调用 `build/csv_replay`。使用 API 前需要先完成“原生 SDK2 C++”编译。

#### 1. 创建 Python 环境

要求 Python 3.11+：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

#### 2. 启动服务

仅本机访问：

```bash
python -m uvicorn api.main:app --host 127.0.0.1 --port 8001
```

可信局域网访问：

```bash
python -m uvicorn api.main:app --host 0.0.0.0 --port 8001
```

当前服务没有内置认证，且默认关闭 `/docs`、`/redoc` 和 `/openapi.json`。不要直接暴露到公网。

#### 3. 调用 `POST /api/replay`

默认 `dry_run=true`，只校验和保存：

```bash
curl -X POST http://127.0.0.1:8001/api/replay \
  -F "file=@assets/wave.csv" \
  -F "save_as=wave_upload" \
  -F "fps=50" \
  -F "dry_run=true"
```

确认安全后才可请求真实执行：

```bash
curl -X POST http://127.0.0.1:8001/api/replay \
  -F "file=@assets/wave.csv" \
  -F "save_as=wave_run" \
  -F "fps=50" \
  -F "dry_run=false"
```

接口还支持 JSON 请求体中的 `csv_data` 和 `text/csv` 原始请求。完整字段及响应格式见 [API 文档](docs/api.md)。上传文件保存在 `assets/uploads/`；非法 CSV 会被拒绝且不会留下最终文件。

## CSV 格式

CSV 使用 UTF-8 编码，每行必须包含 36 个有限数值，可带一行标准表头：

| 列范围 | 内容 | 当前是否驱动 |
|---|---|---|
| 0–6 | Root position + quaternion | 否 |
| 7–18 | 下肢 12 关节 | 否 |
| 19–21 | 腰部 3 DOF | 是 |
| 22–28 | 左臂 7 DOF | 是 |
| 29–35 | 右臂 7 DOF | 是 |

回放程序实际控制双臂和腰部共 17 个关节。空行会被忽略；列数错误、非数值和非有限值会被拒绝。

## 回放安全策略

回放程序默认使用 nearest-window 策略：

- 在动作开头约 2 秒窗口内选择最接近机器人当前姿态的入口帧。
- 在动作结尾约 2 秒窗口内选择最接近初始姿态的退出帧。
- Transition 和 Replay 阶段均执行速度钳位。
- ROS 2 程序在退出时渐出控制权并回到初始上肢姿态。

这些策略用于降低首尾姿态突变，但不能替代现场安全检查和急停措施。

## 测试

Python 和规划逻辑测试：

```bash
source .venv/bin/activate
python3 -m compileall -q api tests
python3 -m pytest

g++ -std=c++17 -I. tests/replay_planner_test.cpp -o /tmp/replay_planner_test
/tmp/replay_planner_test
```

ROS 2 通信测试应在 Foxy Docker 内执行，SDK2 连接测试使用 `build/test_connection`。

## 常见问题

### 子模块目录为空

```bash
git submodule update --init --recursive
```

### `csv_replay binary not found`

这是 FastAPI 需要的 SDK2 程序，重新执行：

```bash
cmake -S . -B build
cmake --build build -j"$(nproc)"
```

### 修改 `csv_replay_ros2.cpp` 后没有生效

`.cpp` 不能直接运行。Docker 启动脚本也不会自动编译，需要重新运行：

```bash
./build_foxy_docker.sh
```

然后重新进入容器并检查实际可执行文件：

```bash
ros2 pkg executables g1_motion_player_ros2
```

### Docker socket permission denied

```bash
sudo usermod -aG docker "$USER"
newgrp docker
docker version
```

### 机器人没有动作

依次检查：

- 运行参数是否仍处于校验模式：ROS 2 需要 `--execute`，API 需要 `dry_run=false`。
- `UNITREE_NET_IFACE` 或 SDK2 网卡参数是否与机器人通信网卡一致。
- `/lowstate` 是否持续发布，或 `build/test_connection` 是否连接成功。
- 是否已有其他 `/arm_sdk`、`rt/arm_sdk` publisher 占用控制链路。
- 机器人当前模式、支撑状态和急停条件是否满足执行要求。

### Python 版本不满足要求

若出现 `requires a different Python`，使用 Python 3.11+ 重建虚拟环境：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

## 扩展文档

- [ROS 2 Docker 开发指南](docs/ros2_docker.md)
- [G1 实机部署指南](docs/g1_robot_deployment.md)
- [HTTP API 文档](docs/api.md)
- [远端拉取与部署提示](docs/remote_pull_prompt.md)
- [English README](README_EN.md)
