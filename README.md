# G1 Motion Player

Unitree G1 人形机器人上肢关键帧回放工具。通过 SDK `rt/arm_sdk` 话题下发关节角度，驱动机器人执行预录动作。

## 项目结构

```
g1_motion_player/
├── CMakeLists.txt
├── src/
│   ├── csv_replay.cpp          # 主程序：CSV 关键帧回放（Arm SDK 模式）
│   ├── json_replay.cpp         # JSON 关键帧回放（Arm SDK 模式）
│   ├── csv_replay_debug.cpp    # 调试模式：rt/user_lowcmd 直接控制（需 PASSIVE）
│   ├── g1_mode_switch.cpp      # FSM 状态切换工具
│   ├── state_recorder.cpp      # 状态录制工具：全流程录制
│   └── test_connection.cpp     # 连接测试
├── assets/
│   ├── csv/
│   │   ├── zuoyi.csv           # 作揖动作（600帧，10秒）
│   │   └── wave.csv            # 打招呼动作（600帧，10秒）
│   └── json/
│       ├── zuoyi.json          # 作揖动作 JSON 调试数据
│       └── wave.json           # 打招呼动作 JSON 调试数据
├── docs/
│   └── initial_pose_analysis.md # 初值分析报告
├── thirdparty/
│   └── unitree_sdk2/           # 宇树 SDK（git submodule）
└── README.md
```

## 环境配置

### 系统要求

- Ubuntu 20.04 / 22.04 (x86_64 或 aarch64)
- GCC 9.4+，CMake 3.5+

### 安装依赖

```bash
sudo apt-get update && sudo apt-get install -y \
  cmake g++ build-essential \
  libyaml-cpp-dev libeigen3-dev \
  libboost-all-dev libspdlog-dev libfmt-dev
```

### 克隆项目

```bash
git clone --recurse-submodules https://github.com/你/g1_motion_player.git
cd g1_motion_player
```

如果已克隆但子模块为空：

```bash
git submodule update --init --recursive
```

### 编译

```bash
mkdir -p build && cd build
cmake ..
make
```

产物：`build/csv_replay`、`build/json_replay`、`build/state_recorder`、`build/test_connection`

## 使用

### 网络配置

```bash
# 网线连接机器人，设置同网段 IP
sudo ip addr add 192.168.123.100/24 dev eno0
ping 192.168.123.164  # 测试连通
```

查看网卡名：

```bash
ip -br a
```

### 连接测试

```bash
./build/test_connection
# 或指定网卡
./build/test_connection eno0
```

### 执行动作

```bash
# 默认网卡 eno0，60fps
./build/csv_replay assets/csv/zuoyi.csv

# 指定帧率
./build/csv_replay assets/csv/zuoyi.csv 50

# 指定网卡
./build/csv_replay assets/csv/wave.csv 60 eth0

# 兼容旧参数顺序
./build/csv_replay eno0 assets/csv/zuoyi.csv
```

### 录制全流程状态

录制机器人从站立到动作执行再到恢复的全过程关节状态：

```bash
./build/state_recorder assets/csv/zuoyi.csv 60 eno0
```

输出文件自动命名为 `assets/csv/zuoyi_recorded.csv`，格式与输入 CSV 一致（36列 LAFAN1 格式，带表头）。

录制流程：2s 静止 → Engage → Transition → Replay → Disengage → 2s 静止

### FSM 状态切换

```bash
./build/g1_mode_switch walk       # 切到走跑模式
./build/g1_mode_switch passive    # 切到 PASSIVE
./build/g1_mode_switch standup    # 站立
./build/g1_mode_switch status     # 查看当前 FSM
```

### 调试模式（实验性）

通过 `rt/user_lowcmd` 直接控制全身 29 DOF，需遥控器 L2+A 先进入 PASSIVE：

```bash
./build/csv_replay_debug assets/csv/zuoyi.csv
```

**注意**：当前固件版本调试模式不可用（`SwitchToUserCtrl` API 未实现）。

## 控制原理

采用 SDK 的 `rt/arm_sdk` 话题 + weight 机制，与官方 `g1_arm7_sdk_dds_example` 一致。

```
Motor_real = weight × User_Cmd + (1 - weight) × BuiltIn_Cmd
```

执行流程：

```
① 连接 DDS，读取所有关节当前位置
② weight 0→1.0（1秒，接管上肢控制，下肢保持初始位置）
③ 平滑过渡到 CSV 首帧（2秒，速度钳位 0.5 rad/s）
④ 逐帧回放关键帧（默认 60Hz，速度钳位 0.8 rad/s）
⑤ 平滑回到初始姿态（2秒）
⑥ weight 1.0→0（2秒，交还内置控制）
```

不需要机器人处于 PASSIVE 模式，站着就能用。

### 关键参数

**PD 增益（按电机类型设置）：**

| 关节组 | 电机类型 | Kp | Kd | 说明 |
|--------|---------|-----|-----|------|
| 手臂 (15-28) | GearboxS | 60 | 1.5 | 跟踪 CSV 目标 |
| 腰Yaw (12) | GearboxM | 80 | 2 | 中等硬度，抵抗运控补偿 |
| 腰Roll/Pitch (13-14) | GearboxS | 50 | 1.5 | 中等硬度 |
| 髋关节 (0-2, 6-8) | GearboxM | 60 | 1 | 抵抗重心偏移 |
| 膝关节 (3, 9) | GearboxL | 100 | 2 | 强力支撑 |
| 踝关节 (4-5, 10-11) | GearboxS | 40 | 1 | 稳定支撑 |

**速度与重量参数：**

| 参数 | 值 | 说明 |
|------|----|------|
| `kTransitionMaxVel` | 0.5 rad/s | Transition 阶段速度钳位 |
| `kReplayMaxVel` | 0.8 rad/s | Replay 阶段速度钳位 |
| `kFinalWeightTarget` | 1.0 | 完全接管控制 |

**稳定性措施：**
- `BalanceStand()` — 回放前切换到平衡站立模式，抑制自动迈步
- `LowStand()` — 降低重心，增大稳定裕度
- 分关节 PD 增益 — 按电机类型设置，下肢高增益抵抗重心偏移

## CSV 格式

已新增表头，前 7 列是根坐标与姿态，后 29 列是关节角度（弧度），对应关节名如下：

```
root_pos_x,root_pos_y,root_pos_z,root_quat_x,root_quat_y,root_quat_z,root_quat_w,
left_hip_pitch_joint,left_hip_roll_joint,left_hip_yaw_joint,left_knee_joint,left_ankle_joint,left_ankle_roll_joint,
right_hip_pitch_joint,right_hip_roll_joint,right_hip_yaw_joint,right_knee_joint,right_ankle_joint,right_ankle_roll_joint,
waist_yaw_joint,waist_roll_joint,waist_pitch_joint,
left_shoulder_pitch_joint,left_shoulder_roll_joint,left_shoulder_yaw_joint,left_elbow_joint,
left_wrist_roll_joint,left_wrist_pitch_joint,left_wrist_yaw_joint,
right_shoulder_pitch_joint,right_shoulder_roll_joint,right_shoulder_yaw_joint,right_elbow_joint,
right_wrist_roll_joint,right_wrist_pitch_joint,right_wrist_yaw_joint
```

LAFAN1 retargeting 格式，每行 36 列（支持有表头/无表头）：

```
列 0-2:   根节点位置 XYZ（忽略）
列 3-6:   根节点四元数（忽略）
列 7-35:  29 个关节角度（弧度）
```

上肢关节（列 19-35 = SDK 关节 12-28）：

| 列 | SDK Index | 关节 |
|----|-----------|------|
| 19 | 12 | WaistYaw |
| 20 | 13 | WaistRoll |
| 21 | 14 | WaistPitch |
| 22-28 | 15-21 | LeftArm (7 DOF) |
| 29-35 | 22-28 | RightArm (7 DOF) |

## 参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `net` | 网卡名 | eno0 |
| `motion` / `csv_path` | 动作名（assets 下）或 CSV 路径 | 选填二选一，与 `motion_json` 互斥 |
| `motion_json` | JSON 形式轨迹 payload | 选填，与 `motion`/`csv_path` 互斥 |
| `fps` | 控制帧率 | 60 |

### 本地 API 请求格式（新增）

- `POST /api/replay/validate`

请求字段采用 JSON，且必须且只能给出一种来源：`motion`、`csv_path` 或 `motion_json`。  
以下是三种合法样例之一（与 `motion_json` 不可混用）：

```json
{
  "motion": "wave",
  "fps": 60,
  "net": "eno0",
  "dry_run": true
}
```

```json
{
  "csv_path": "assets/csv/wave.csv",
  "fps": 60,
  "net": "eno0",
  "dry_run": true
}
```

```json
{
  "motion_json": [
    {
      "time": 0,
      "poseData": [36个浮点数],
      "jointValues": {
        "waist_pitch_joint": 0.086,
        "...": "..."
      }
    }
  ],
  "fps": 60,
  "net": "eno0",
  "dry_run": true
}
```

字段说明：  
- `poseData`：长度 36，按 CSV 列顺序：`root_pos_x...right_wrist_yaw_joint`。  
- `jointValues`：可选，键必须是 `SDK` 关节名，值单位是角度（°），如提供会校验与 `poseData[7:36]`（弧度）一致。

- `GET /api/motions/{motion}/json?fps=60`

- `GET /api/motions/{motion}`

- `POST /api/motions`（创建新动作，写入 `assets/json/<name>.json` 与 `assets/csv/<name>.csv`）

返回该 CSV 的 `[{id,time,poseData,jointValues}]` 调试 payload，用于前端发送/日志对比。

测试资源（本地联调直接可用）：
- `assets/json/wave.json`
- `assets/json/zuoyi.json`

JSON 数据用于 `/api/replay` 的 `motion_json` 入参。接口会把该 payload 转发给
`json_replay` 执行，并在本地异步保留一份 `assets/json/<name>.json` 与 `assets/csv/<name>.csv` 便于调试追踪。

如果配置了环境变量 `MOTION_API_KEY`，则 `POST /api/replay`、`POST /api/replay/validate`
和 `POST /api/motions` 需要携带鉴权头（`Authorization: Bearer <token>` 或
`X-API-Key: <token>`）。未配置则保持免鉴权，便于本地调试。

## 常见问题

### libddsc.so.0 not found

```bash
./build/csv_replay 或 ./build/json_replay: error while loading shared libraries: libddsc.so.0
```

原因：SDK 目录里有 `libddsc.so` 但运行时需要 `libddsc.so.0`。

修复：

```bash
cd build && cmake ..
```

CMake 会在 `build/` 目录创建 `.so.0` 软链接（不会修改子模块）。

### weight=1.0 时下肢前跑

现象：执行动作时机器人偶尔会往前跑几步。

原因：`rt/arm_sdk` 的 weight 机制是全局的。当 weight=1.0 时，所有关节（包括下肢）都由用户指令控制。如果 `send()` 只设置了上肢关节，下肢关节会收到默认值（0），导致失去平衡。

修复：在 `send()` 中同时发送下肢关节的保持指令，读取初始位置后每帧都以低增益 PD 控制下肢保持原位。

### 动作执行不到位（跟踪误差大）

现象：机器人动作幅度明显小于关键帧指定的幅度。

原因：之前 Replay 阶段有速度钳位（0.5 rad/s），当 CSV 帧间角度变化大时，指令位置永远追不上目标。

修复：
1. 按电机类型设置分关节 PD 增益（手臂 Kp=60，膝关节 Kp=100）
2. Replay 阶段使用更宽松的速度钳位（0.8 rad/s）
3. weight 从 0.6 提高到 1.0，消除内置控制器的抵抗

### 上肢动作时腰部/下肢不稳

现象：执行上肢动作时，机器人腰部摆动或自动迈步。

原因：上肢动作改变重心，内置运控自动补偿（用腰或腿）。

缓解措施：
1. `BalanceStand()` — 回放前切换到平衡站立模式，抑制自动迈步
2. `LowStand()` — 降低重心，增大稳定裕度
3. 提高腰/腿 PD 增益 — 让腰更硬，抵抗运控补偿
4. 降低回放速度 — 给运控更多时间适应重心变化

### 子模块显示 modified content

现象：`git status` 显示 `thirdparty/unitree_sdk2 (modified content)`。

原因：cmake 在子模块目录内创建了 `.so.0` 软链接或产生了构建残留。

修复：

```bash
cd thirdparty/unitree_sdk2
git checkout -- .
git clean -fd
cd ../..
```

预防：CMakeLists.txt 已修改为在 build 目录创建软链接，不再修改子模块。

## 安全

- 首次运行建议有人在旁边
- 遥控器 L2+B 急停
- 下肢关节保持初始位置（按电机类型设置增益）
- Disengage 阶段先回到初始姿态再释放控制权
- `BalanceStand()` + `LowStand()` 提高稳定性
