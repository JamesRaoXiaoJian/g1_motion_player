# G1 ROS2 Foxy Docker 开发指南

本项目通过 Docker 固定 G1 ROS2 通信环境，宿主机无需安装 ROS2 Foxy。

环境版本：

```text
Ubuntu 20.04 container
ROS2 Foxy
rmw_cyclonedds_cpp 0.7.11
CycloneDDS 0.10.2
```

宇树 ROS2 消息和示例源码位于：

```text
thirdparty/unitree_ros2/
```

## 安装 Docker

```bash
sudo apt update
sudo apt install -y docker.io
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
newgrp docker
docker version
```

`docker version` 应同时显示 Client 和 Server。

## 网络要求

开发电脑与 G1 PC2 必须位于同一个二层网络：

```text
G1 PC2: 192.168.123.164/24
开发电脑: 192.168.123.x/24
```

检查：

```bash
ip -4 -brief addr
ip route get 192.168.123.164
ping -c 3 192.168.123.164
```

路由必须直接经过实际有线或无线网卡，不能经过下级路由器 NAT，也不应被 `Meta`、`tun0` 等代理接口接管。

## 构建

```bash
cd ~/Project/g1_motion_player
./build_foxy_docker.sh
```

首次构建需要访问 Docker Hub、Ubuntu/ROS 软件源和 GitHub。成功输出：

```text
Summary: 4 packages finished
Foxy workspace built: .../g1_motion_player/.foxy/install
```

构建内容：

1. Foxy 基础镜像和 ROS2 CycloneDDS RMW。
2. CycloneDDS 0.10.2。
3. `unitree_api`、`unitree_go`、`unitree_hg` 消息。
4. Unitree ROS2 示例。
5. 本项目的 C++ ROS2 控制适配器 `g1_motion_player_ros2`。

## 启动

默认网卡为 `wlo1`：

```bash
./run_foxy_docker.sh
```

其他机器按实际网卡指定：

```bash
UNITREE_NET_IFACE=wlan0 ./run_foxy_docker.sh
```

容器中确认：

```bash
echo "$ROS_DISTRO $RMW_IMPLEMENTATION"
ros2 topic list | grep -E '^/(lowstate|lowcmd|user_lowcmd|arm_sdk)$'
```

预期环境：

```text
foxy rmw_cyclonedds_cpp
```

## 状态接收

读取完整底层状态：

```bash
ros2 topic echo /lowstate unitree_hg/msg/LowState
```

测量接收频率：

```bash
python3 docker/foxy/measure_lowstate_rate.py --duration 10
```

读取 7-DOF 双臂角度：

```bash
python3 docker/foxy/read_upper_body.py
```

同时读取腰部：

```bash
python3 docker/foxy/read_upper_body.py --include-waist
```

## 双端通信测试

本机容器发布：

```bash
python3 docker/foxy/test_publisher.py
```

G1 调试终端仅临时加载其原有环境：

```bash
source /opt/ros/foxy/setup.bash
source ~/cyclonedds_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_DOMAIN_ID=0
export ROS_LOCALHOST_ONLY=0
ros2 topic echo /unitree_test std_msgs/msg/String
```

不要在 G1 上部署本仓库或覆盖其内置 ROS2 工作区。

## ROS2 CSV 实时回放

ROS2 回放程序：

```text
src/ros2/csv_replay_ros2.cpp
```

它订阅 `/lowstate`，并以 CSV 一行一帧、一周期一条 `LowCmd` 的方式发布到 `/arm_sdk`。每条消息同步携带双臂和腰部17轴目标，不发送腿部位置命令。

只校验 CSV：

```bash
ros2 run g1_motion_player_ros2 csv_replay_ros2 assets/wave.csv
```

实体机器人执行：

```bash
ros2 run g1_motion_player_ros2 csv_replay_ros2 assets/wave.csv --execute
```

自定义参数：

```bash
ros2 run g1_motion_player_ros2 csv_replay_ros2 \
  assets/wave.csv --fps 50 --execute
```

程序包含：

- 当前关节状态初始化。
- 最近窗口入口和出口帧选择。
- 使用绝对时间点调度发布周期，避免 `sleep_for` 产生累计漂移。
- 过渡与回放速度钳位。
- 持续处理 `/lowstate`，分别检查双臂和腰部实际跟踪误差。
- 到达入口和返回初始姿态时，要求实际关节误差连续稳定达标。
- `/lowstate` 超时、持续跟踪误差、重复 `/arm_sdk` publisher 和连续周期严重超时看门狗。
- `/arm_sdk` 控制权重渐入和渐出。
- 回到初始上肢姿态。
- 正常结束、看门狗触发和 `Ctrl+C` 时均尝试平滑释放控制权。

当前固定安全阈值：

| 检查项 | 阈值 |
|---|---:|
| `/lowstate` 超时 | 500 ms |
| 双臂持续跟踪误差 | 0.35 rad，连续 15 个控制周期 |
| 腰部持续跟踪误差 | 0.20 rad，连续 15 个控制周期 |
| 双臂到位误差 | 0.08 rad，连续 10 个控制周期 |
| 腰部到位误差 | 0.05 rad，连续 10 个控制周期 |
| 到位等待超时 | 5 s |
| 发布周期严重超时 | 超过 2 个周期，连续 3 次 |

看门狗触发时终端输出 `SAFETY STOP`，停止推进轨迹，并在约 2 秒内把
`/arm_sdk` 权重降为 0。阈值是初始保守值，实机正式使用前应根据负载、动作速度和网络状态验证。

## SDK2 与 ROS2 两条链路

项目保留原有 Unitree SDK2 C++程序：

```bash
cmake -S . -B build
cmake --build build -j"$(nproc)"
./build/csv_replay assets/wave.csv 50 eth0
```

新开发默认使用 ROS2 Docker：

```bash
./run_foxy_docker.sh
ros2 run g1_motion_player_ros2 csv_replay_ros2 assets/wave.csv --execute
```

两种程序都可能向机器人 `arm_sdk` 控制链路发送命令，禁止同时运行。

## 安全要求

- 确保机器人周围无人员和障碍物。
- 机器人应稳定站立或可靠支撑。
- 操作者必须可以立即使用急停。
- 控制前确认 `/lowstate` 持续接收正常。
- CSV 必须先在无 `--execute` 模式下校验。
- 禁止同时启动多个 `/arm_sdk` publisher。
- 不要用 `ros2 topic pub` 向 `/arm_sdk`、`/lowcmd` 或 `/user_lowcmd` 发送空消息。

## 常见问题

### Docker socket permission denied

```bash
sudo usermod -aG docker "$USER"
newgrp docker
```

### Docker Hub timeout

若 `registry-1.docker.io:443` 超时，需要配置 Docker daemon 代理或从已构建机器导入镜像：

```bash
docker save \
  ros:foxy-ros-base \
  g1-motion-player-foxy:0.10.2 \
  -o g1-motion-player-foxy-images.tar
```

目标机器：

```bash
docker load -i g1-motion-player-foxy-images.tar
```

### 容器没有 G1 话题

```bash
ip -4 -brief addr
ip route get 192.168.123.164
```

确认网卡后重新启动：

```bash
UNITREE_NET_IFACE=<实际网卡> ./run_foxy_docker.sh
```

### 宿主机已安装 Jazzy

无需卸载。G1 通信全部在 Foxy 容器中执行，宿主机 ROS2、Conda 和 Python 不参与容器运行。
