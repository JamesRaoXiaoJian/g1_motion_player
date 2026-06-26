# G1 Motion Player

Unitree G1 人形机器人上肢关键帧回放工具。通过 SDK `rt/arm_sdk` 话题下发关节角度，驱动机器人执行预录动作。

## 项目结构

```
g1_motion_player/
├── CMakeLists.txt
├── src/
│   ├── csv_replay.cpp          # 主程序：CSV 关键帧回放
│   └── test_connection.cpp     # 连接测试
├── assets/
│   ├── zuoyi.csv               # 作揖动作（600帧，10秒）
│   └── wave.csv                # 打招呼动作（600帧，10秒）
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

产物：`build/csv_replay` 和 `build/test_connection`

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
# 默认网卡 eno0（推荐）
./build/csv_replay assets/zuoyi.csv

# 指定帧率
./build/csv_replay assets/zuoyi.csv 50

# 指定网卡
./build/csv_replay assets/wave.csv 60 eno0

# 兼容旧参数顺序
./build/csv_replay eno0 assets/zuoyi.csv
```

## 控制原理

采用 SDK 的 `rt/arm_sdk` 话题 + weight 机制，与官方 `g1_arm7_sdk_dds_example` 一致。

```
Motor_real = weight × User_Cmd + (1 - weight) × BuiltIn_Cmd
```

执行流程：

```
① 连接 DDS
② 读取当前关节角度
③ weight 0→1（1秒，接管上肢控制）
④ 平滑过渡到 CSV 首帧（2秒，速度钳位 0.5 rad/s）
⑤ 逐帧回放关键帧（默认 60Hz）
⑥ weight 1→0（2秒，交还内置控制）
```

不需要机器人处于 PASSIVE 模式，站着就能用。

## CSV 格式

LAFAN1 retargeting 格式，每行 36 列，无表头：

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
| `csv` | CSV 文件路径 | 必填 |
| `fps` | 控制帧率 | 60 |

## 常见问题

### 启动时报错: libddsc.so.0 not found

现象：

```bash
./build/csv_replay: error while loading shared libraries: libddsc.so.0: cannot open shared object file
```

原因：
- SDK 目录里有 `libddsc.so` / `libddscxx.so`，但运行时需要 `libddsc.so.0` / `libddscxx.so.0`。

修复：

```bash
cd build
cmake ..
```

本项目的 CMake 会在配置阶段自动创建 `.so.0` 软链接，执行一次 `cmake ..` 即可。

## 安全

- 首次运行建议有人在旁边
- 遥控器 L2+B 急停
- 速度钳位 0.5 rad/s（与官方一致）
- PD 增益 kp=60, kd=1.5（与官方一致）