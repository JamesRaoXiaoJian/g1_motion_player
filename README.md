# G1 Motion Player

Unitree G1 人形机器人动作回放工具。项目包含两层：

- C++ 回放层：`csv_replay`、`json_replay` 等二进制程序，通过 Unitree SDK DDS 话题 `rt/arm_sdk` 控制机器人。
- FastAPI 接口层：提供动作查询、创建、更新、校验和回放接口，方便前端或其他服务本地联调。

当前执行策略：

- CSV 动作仍由 `csv_replay` 执行。
- JSON 动作由 API 直接传给 `json_replay --stdin` 执行。
- API 会同时保留 `assets/json/<name>.json` 与 `assets/csv/<name>.csv`，CSV 用于阅读和调试，不再作为 JSON 回放的执行中转。
- 动作默认使用 `nearest_window` 入口/退出策略：入口在动作前 2 秒内选择最接近当前机器人姿态的帧，退出在动作后 2 秒内选择最接近初始姿态的帧。

## 项目结构

```text
g1_motion_player/
├── CMakeLists.txt
├── pyproject.toml
├── api/
│   ├── main.py                # FastAPI 入口
│   └── csv_motion.py          # CSV/JSON 动作解析与校验
├── src/
│   ├── csv_replay.cpp         # CSV 关键帧回放
│   ├── json_replay.cpp        # JSON 关键帧回放，支持 --stdin
│   ├── csv_replay_debug.cpp   # rt/user_lowcmd 调试模式
│   ├── g1_mode_switch.cpp     # FSM 状态切换工具
│   ├── state_recorder.cpp     # 状态录制工具
│   └── test_connection.cpp    # DDS 连接测试
├── assets/
│   ├── csv/
│   │   ├── wave.csv
│   │   └── zuoyi.csv
│   └── json/
│       ├── wave.json
│       └── zuoyi.json
├── docs/
│   ├── api.md
│   └── initial_pose_analysis.md
└── thirdparty/
    └── unitree_sdk2/          # git submodule
```

## 环境要求

推荐环境：

- Ubuntu 20.04 / 22.04
- x86_64 或 aarch64
- GCC 9.4+
- CMake 3.5+
- Python 3.9+
- Unitree G1 与电脑在同一有线网段

安装系统依赖：

```bash
sudo apt-get update
sudo apt-get install -y \
  git cmake g++ build-essential pkg-config \
  libyaml-cpp-dev libeigen3-dev \
  libboost-all-dev libspdlog-dev libfmt-dev \
  python3 python3-venv python3-pip
```

## 获取代码与子模块

首次克隆：

```bash
git clone --recurse-submodules https://github.com/JamesRaoXiaoJian/g1_motion_player.git
cd g1_motion_player
```

如果已经克隆过，或发现 `thirdparty/unitree_sdk2` 目录为空：

```bash
git submodule update --init --recursive
```

确认子模块完整：

```bash
test -f thirdparty/unitree_sdk2/CMakeLists.txt && echo "unitree_sdk2 ok"
```

如果这里没有输出，C++ 编译会在 `add_subdirectory(thirdparty/unitree_sdk2)` 失败。

## Python API 环境

推荐用虚拟环境安装 API 依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

`pyproject.toml` 中的依赖：

- 运行依赖：`fastapi`、`uvicorn[standard]`
- 测试依赖：`httpx`、`pytest`

如果你使用 `uv`，也可以执行：

```bash
uv sync --extra dev
```

## 编译 C++ 回放工具

```bash
cmake -S . -B build
cmake --build build -j"$(nproc)"
```

编译产物：

- `build/csv_replay`
- `build/json_replay`
- `build/test_connection`
- `build/state_recorder`
- `build/csv_replay_debug`
- `build/g1_mode_switch`

`CMakeLists.txt` 会在 `build/` 目录创建 DDS 运行时需要的 `.so.0` 软链接，避免污染 `thirdparty/unitree_sdk2` 子模块。

## 网络配置

查看网卡名：

```bash
ip -br a
```

如果机器人默认地址为 `192.168.123.164`，电脑网卡可以配置同网段地址：

```bash
sudo ip addr add 192.168.123.100/24 dev eno0
ping 192.168.123.164
```

把 `eno0` 替换成你的实际有线网卡名。API 和 C++ 工具默认网卡都是 `eno0`。

## C++ 工具使用

连接测试：

```bash
./build/test_connection eno0
```

CSV 回放：

```bash
./build/csv_replay assets/csv/wave.csv
./build/csv_replay assets/csv/wave.csv 60 eno0
```

JSON 回放：

```bash
./build/json_replay assets/json/wave.json 60 eno0
```

从 stdin 输入 JSON：

```bash
./build/json_replay --stdin 60 eno0 < assets/json/wave.json
```

状态录制：

```bash
./build/state_recorder assets/csv/zuoyi.csv 60 eno0
```

FSM 状态切换：

```bash
./build/g1_mode_switch walk eno0
./build/g1_mode_switch passive eno0
./build/g1_mode_switch standup eno0
./build/g1_mode_switch status eno0
```

调试模式：

```bash
./build/csv_replay_debug assets/csv/zuoyi.csv
```

`csv_replay_debug` 通过 `rt/user_lowcmd` 直接控制全身 29 DOF，通常需要先进入 PASSIVE。当前固件环境下该模式可能不可用，生产回放优先使用 `csv_replay` / `json_replay`。

## 启动 API 服务

前台启动：

```bash
source .venv/bin/activate
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

局域网访问：

```bash
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

后台运行：

```bash
nohup python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 > api.log 2>&1 &
```

## API 认证

默认不启用认证，方便本地联调。

如果设置环境变量 `MOTION_API_KEY`，以下写操作会要求鉴权：

- `POST /api/replay`
- `POST /api/replay/validate`
- `POST /api/motions`
- `PUT /api/motions/{motion}`

启动前设置：

```bash
export MOTION_API_KEY="replace-with-a-long-random-token"
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

请求时二选一：

```bash
curl -H "X-API-Key: replace-with-a-long-random-token" http://127.0.0.1:8000/api/motions
curl -H "Authorization: Bearer replace-with-a-long-random-token" http://127.0.0.1:8000/api/motions
```

读取类接口目前不强制鉴权：`GET /health`、`GET /api/motions`、`GET /api/motions/{motion}`、`GET /api/motions/{motion}/json`。

## API 快速示例

列出动作：

```bash
curl http://127.0.0.1:8000/api/motions
```

查看单个动作元数据：

```bash
curl http://127.0.0.1:8000/api/motions/wave
```

导出动作 JSON：

```bash
curl "http://127.0.0.1:8000/api/motions/wave/json?fps=60"
```

创建动作：

```bash
curl -X POST http://127.0.0.1:8000/api/motions \
  -H "Content-Type: application/json" \
  -H "X-API-Key: replace-with-a-long-random-token" \
  -d '{
    "name": "demo",
    "fps": 60,
    "motion_json": [
      {"time": 0, "poseData": [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]}
    ]
  }'
```

更新动作：

```bash
curl -X PUT http://127.0.0.1:8000/api/motions/demo \
  -H "Content-Type: application/json" \
  -H "X-API-Key: replace-with-a-long-random-token" \
  -d '{
    "fps": 60,
    "motion_json": [
      {"time": 0, "poseData": [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]}
    ]
  }'
```

校验回放请求：

```bash
curl -X POST http://127.0.0.1:8000/api/replay/validate \
  -H "Content-Type: application/json" \
  -H "X-API-Key: replace-with-a-long-random-token" \
  -d '{"motion": "wave", "fps": 60, "net": "eno0", "dry_run": true}'
```

真实回放 CSV 动作：

```bash
curl -X POST http://127.0.0.1:8000/api/replay \
  -H "Content-Type: application/json" \
  -H "X-API-Key: replace-with-a-long-random-token" \
  -d '{"motion": "wave", "fps": 60, "net": "eno0", "dry_run": false}'
```

真实回放 JSON payload：

```bash
curl -X POST http://127.0.0.1:8000/api/replay \
  -H "Content-Type: application/json" \
  -H "X-API-Key: replace-with-a-long-random-token" \
  -d '{
    "motion_json": [
      {"time": 0, "poseData": [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]}
    ],
    "fps": 60,
    "net": "eno0",
    "dry_run": false
  }'
```

完整接口文档见 [docs/api.md](docs/api.md)。

## 数据格式

### 资产目录

- `assets/csv/<name>.csv`：CSV 动作文件，供 `csv_replay` 和动作查询使用。
- `assets/json/<name>.json`：JSON 动作文件，供 `json_replay`、API 创建/更新和调试使用。

动作名必须是简单文件名，不允许路径分隔符，例如 `wave`、`zuoyi`、`demo_01`。

### CSV 格式

每帧 36 列，支持有表头或无表头：

```text
root_pos_x,root_pos_y,root_pos_z,root_quat_x,root_quat_y,root_quat_z,root_quat_w,
left_hip_pitch_joint,left_hip_roll_joint,left_hip_yaw_joint,left_knee_joint,left_ankle_joint,left_ankle_roll_joint,
right_hip_pitch_joint,right_hip_roll_joint,right_hip_yaw_joint,right_knee_joint,right_ankle_joint,right_ankle_roll_joint,
waist_yaw_joint,waist_roll_joint,waist_pitch_joint,
left_shoulder_pitch_joint,left_shoulder_roll_joint,left_shoulder_yaw_joint,left_elbow_joint,
left_wrist_roll_joint,left_wrist_pitch_joint,left_wrist_yaw_joint,
right_shoulder_pitch_joint,right_shoulder_roll_joint,right_shoulder_yaw_joint,right_elbow_joint,
right_wrist_roll_joint,right_wrist_pitch_joint,right_wrist_yaw_joint
```

列含义：

- `0-2`：根节点位置，当前回放忽略。
- `3-6`：根节点四元数，当前回放忽略。
- `7-18`：下肢 12 个关节，回放时保持初始姿态。
- `19-21`：腰部 3 个关节，对应 SDK 12-14。
- `22-28`：左臂 7 个关节，对应 SDK 15-21。
- `29-35`：右臂 7 个关节，对应 SDK 22-28。

### JSON 格式

API 和 `json_replay` 使用帧数组：

```json
[
  {
    "id": 0,
    "time": 0.0,
    "poseData": [36个浮点数],
    "jointValues": {
      "left_shoulder_pitch_joint": 4.975
    }
  }
]
```

字段规则：

- `poseData` 必填，长度必须是 36，单位为弧度。
- `jointValues` 可选，单位为角度；如果提供，会校验它与 `poseData[7:36]` 一致。
- `id`、`time` 可选，主要用于前端或调试。

## 控制原理

采用 SDK 的 `rt/arm_sdk` 话题和 weight 机制，与官方 `g1_arm7_sdk_dds_example` 一致。

```text
Motor_real = weight * User_Cmd + (1 - weight) * BuiltIn_Cmd
```

执行流程：

1. 连接 DDS，读取所有关节当前位置。
2. `weight` 从 `0` 增加到 `1.0`，逐步接管上肢控制，同时下肢保持初始位置。
3. 在动作前 2 秒窗口内选择最接近当前姿态的入口帧。
4. 平滑过渡到该入口帧，Transition 阶段速度钳位 `0.5 rad/s`。
5. 在动作后 2 秒窗口内选择最接近初始姿态的退出帧。
6. 从入口帧回放到退出帧，Replay 阶段速度钳位 `0.8 rad/s`。
7. 从退出帧平滑回到初始姿态。
8. `weight` 从 `1.0` 降到 `0`，交还内置控制。

关键控制参数：

| 参数 | 值 | 说明 |
|------|----|------|
| `kTransitionMaxVel` | `0.5 rad/s` | 过渡阶段速度钳位 |
| `kReplayMaxVel` | `0.8 rad/s` | 回放阶段速度钳位 |
| `kNearestWindowSeconds` | `2.0s` | 入口/退出 nearest window 搜索窗口 |
| `kFinalWeightTarget` | `1.0` | 完全接管控制 |

稳定性措施：

- 回放前执行 `BalanceStand()`。
- 回放前执行 `LowStand()`。
- 下肢关节每帧保持初始位置。
- 腰、腿、手臂按电机类型设置不同 PD 增益。

## 测试与验证

Python 语法检查：

```bash
python3 -m compileall -q api tests
```

Python 测试：

```bash
pytest -q
```

只测 API：

```bash
pytest -q tests/test_api.py
```

只测数据解析：

```bash
pytest -q tests/test_csv_motion.py
```

C++ 编译验证：

```bash
cmake -S . -B build
cmake --build build -j"$(nproc)"
```

机器人连接验证：

```bash
./build/test_connection eno0
```

## 常见问题

### `thirdparty/unitree_sdk2` 为空

现象：

```text
CMake Error at CMakeLists.txt: add_subdirectory given source "thirdparty/unitree_sdk2" which is not an existing directory
```

或：

```text
The source directory .../thirdparty/unitree_sdk2 does not contain a CMakeLists.txt file.
```

处理：

```bash
git submodule update --init --recursive
test -f thirdparty/unitree_sdk2/CMakeLists.txt && echo "unitree_sdk2 ok"
```

### `fastapi` / `pytest` 找不到

现象：

```text
ModuleNotFoundError: No module named 'fastapi'
ModuleNotFoundError: No module named 'pytest'
```

处理：

```bash
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

### `csv_replay` 或 `json_replay` 不存在

现象：API 返回 `replay_error`，提示 `build/csv_replay` 或 `build/json_replay` 不存在。

处理：

```bash
cmake -S . -B build
cmake --build build -j"$(nproc)"
```

### `libddsc.so.0 not found`

现象：

```text
./build/csv_replay: error while loading shared libraries: libddsc.so.0
```

处理：

```bash
cmake -S . -B build
```

CMake 会在 `build/` 创建运行时软链接。如果仍失败，确认 `thirdparty/unitree_sdk2/thirdparty/lib/<arch>/libddsc.so` 存在。

### 子模块显示 `modified content`

现象：

```bash
git status
# thirdparty/unitree_sdk2 (modified content)
```

处理：

```bash
cd thirdparty/unitree_sdk2
git status
git checkout -- .
git clean -fd
cd ../..
```

不要在子模块目录内编译或写入临时文件。当前 CMake 已把运行时软链接放在 `build/`，正常编译不会污染子模块。

### 机器人连接不上

检查项：

- 网线是否连接到正确网口。
- `ip -br a` 中是否能看到有线网卡。
- 电脑 IP 是否在 `192.168.123.0/24`。
- 是否能 `ping 192.168.123.164`。
- API 请求里的 `net` 是否等于实际网卡名。

## 安全注意事项

- 首次运行必须有人在机器人旁边观察。
- 确认遥控器急停可用。
- 先跑 `test_connection`，再执行真实动作。
- 首次动作建议低帧率或短动作验证。
- 执行前确认机器人周围无障碍物。
- 真实回放接口必须显式传 `dry_run: false`。
- 建议在非本机访问 API 时配置 `MOTION_API_KEY`。
