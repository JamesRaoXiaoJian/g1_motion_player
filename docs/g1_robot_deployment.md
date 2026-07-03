# Unitree G1 PC2 本体部署文档

本文档用于把当前 `g1_motion_player` 主分支部署到宇树 G1 的 PC2 本机。当前主分支只暴露一个接口：

```text
POST /api/replay
```

接口接收请求体里的 CSV 数据或 multipart CSV 上传，保存到 `assets/uploads/`，校验通过后在 `dry_run=false` 时调用 `build/csv_replay` 执行动作。

## 1. 部署原则

- 默认只绑定 `127.0.0.1`，先在 PC2 本机联调。
- 默认请求使用 `dry_run=true`，确认 CSV 合法和保存路径后再切换到 `dry_run=false`。
- 不在主分支使用 JSON replay，不上传 JSON 动作数据。
- 不在部署时执行 `git reset --hard`、删除 `assets/uploads/` 或覆盖本地未确认文件。
- 真实执行动作前，确认机器人周围安全、急停可用、电量充足、机器人处于稳定站立状态。

## 2. 首次部署

在 G1 PC2 本机执行：

```bash
cd ~
git clone --recurse-submodules git@github.com:JamesRaoXiaoJian/g1_motion_player.git
cd g1_motion_player
git switch main
```

如果 PC2 没有配置 GitHub SSH key，也可以使用 HTTPS：

```bash
git clone --recurse-submodules https://github.com/JamesRaoXiaoJian/g1_motion_player.git
cd g1_motion_player
git switch main
```

确认当前分支和子模块：

```bash
git status --short --branch
git submodule update --init --recursive
test -f thirdparty/unitree_sdk2/CMakeLists.txt && echo "unitree_sdk2 ok"
```

如果一开始已经执行了不带 `--recurse-submodules` 的普通 clone，不要重新 clone 到同名目录。直接进入已有仓库补齐子模块：

```bash
cd ~/g1_motion_player
git switch main
git submodule update --init --recursive
test -f thirdparty/unitree_sdk2/CMakeLists.txt && echo "unitree_sdk2 ok"
```

如果 `thirdparty/unitree_sdk2/` 是空目录，通常就是子模块还没有初始化；上面的 `git submodule update --init --recursive` 成功后应出现 `CMakeLists.txt`、`include/`、`lib/` 等 SDK 文件。

## 3. 系统依赖

```bash
sudo apt-get update
sudo apt-get install -y \
  git cmake g++ build-essential pkg-config \
  python3 python3-venv python3-pip
```

如果 PC2 已经有这些依赖，可以跳过重复安装。

## 4. Python API 环境

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .
```

如果需要在 PC2 上跑测试，安装开发依赖：

```bash
python -m pip install -e ".[dev]"
```

## 5. 编译 C++ 回放程序

```bash
cmake -S . -B build
cmake --build build -j"$(nproc)" --target csv_replay
```

确认产物存在：

```bash
test -x build/csv_replay && echo "csv_replay ok"
```

## 6. 确认机器人通信网卡

查看 PC2 网卡：

```bash
ip -br link
ip -br addr
```

本次 PC2 现场输出里，机器人有线通信网卡是 `eth0`，地址为 `192.168.123.164/24`；`wlan0` 是无线网，不用于 Unitree SDK DDS 机器人通信。仓库默认机器人通信网卡已设为 `eth0`。

本文后续示例按这台 PC2 使用 `eth0`。如果另一台 PC2 显示为 `eno0`、`enP8p1s0` 或其他名字，先按“修改默认网卡”章节更新仓库默认值，再编译和启动 API。

可以先跑连接测试程序：

```bash
cmake --build build -j"$(nproc)" --target test_connection
./build/test_connection eth0
```

## 7. 直接程序调用

不经过 API 时，直接调用：

```bash
./build/csv_replay assets/wave.csv 50 eth0
```

命令格式：

```bash
./build/csv_replay <csv文件> [fps] [网卡]
```

常用示例：

```bash
./build/csv_replay assets/wave.csv
./build/csv_replay assets/wave.csv 50 eth0
./build/csv_replay assets/zuoyi.csv 50 eth0
```

默认回放频率为 50Hz。若要保持 600 帧动作按 10 秒播放，可以显式传 `60`。

## 8. 启动 API

本机调试：

```bash
source .venv/bin/activate
python -m uvicorn api.main:app --host 127.0.0.1 --port 8001
```

如果前端或上位机在同一可信局域网，需要远程访问 PC2：

```bash
python -m uvicorn api.main:app --host 0.0.0.0 --port 8001
```

当前主分支没有内置认证。绑定 `0.0.0.0` 前，建议用防火墙限制来源 IP，或在外层反向代理加认证。

本次现场确认 `8000` 已被其他 `uvicorn` 占用，所以本项目默认使用 `8001`。如果需要排查旧进程，先查清来源：

```bash
sudo lsof -iTCP:8000 -sTCP:LISTEN -n -P
ps -ww -fp <PID>
readlink -f /proc/<PID>/cwd
```

不确定该进程用途时不要直接杀掉。

API 不暴露 `net` 参数；机器人通信网卡由 PC2 端仓库默认值决定，当前默认 `eth0`。

## 9. API dry-run 验证

multipart 上传 CSV，只校验不执行：

```bash
curl -X POST http://127.0.0.1:8001/api/replay \
  -F "file=@assets/wave.csv" \
  -F "save_as=wave_pc2_check" \
  -F "fps=50" \
  -F "dry_run=true"
```

期望返回：

```json
{
  "ok": true,
  "error": null
}
```

并且 `data.csv_path` 类似：

```text
assets/uploads/wave_pc2_check.csv
```

## 10. API 真实执行

确认机器人安全后，把 `dry_run` 改成 `false`：

```bash
curl -X POST http://127.0.0.1:8001/api/replay \
  -F "file=@assets/wave.csv" \
  -F "save_as=wave_pc2_run" \
  -F "fps=50" \
  -F "dry_run=false"
```

单行版本：

```bash
curl -X POST http://127.0.0.1:8001/api/replay -F "file=@assets/wave.csv" -F "save_as=wave_pc2_run" -F "fps=50" -F "dry_run=false"
```

如果返回 `replay_error` 且提示找不到 `build/csv_replay`，重新编译：

```bash
cmake --build build -j"$(nproc)" --target csv_replay
```

本次 PC2 真机验证结果：

- `./build/test_connection eth0` 输出 `=== CONNECTED ===` 和 `PASSED.`。
- `dry_run=true` 返回 `ok=true`，`frames=600`，`duration_seconds=12.0`。
- `dry_run=false` 返回 `ok=true`，`replay.returncode=0`，日志包含 `Connected.`、`Done: 500 frames in 10.0301s`、`Robot returned to built-in control.`。

## 11. 修改默认网卡

机器人部署版 API 不接收外部 `net` 参数，外部电脑只负责上传 CSV 和指定 `dry_run`。如果另一台 PC2 的机器人通信网卡不是当前默认的 `eth0`，需要同步修改以下位置：

- `api/main.py`：`DEFAULT_ROBOT_NET`。
- `src/csv_replay.cpp`：默认 `net` 字符串和帮助文本 `Default net: ...`。
- `src/test_connection.cpp`：默认网卡和文件头注释。
- 如使用调试/记录工具，同步修改 `src/csv_replay_debug.cpp`、`src/state_recorder.cpp`、`src/g1_mode_switch.cpp`。

修改后重新安装或重启 API，并重新编译 C++：

```bash
source .venv/bin/activate
python -m pip install -e .
cmake -S . -B build
cmake --build build -j"$(nproc)" --target csv_replay test_connection
```

改完后重新执行：

```bash
./build/test_connection <实际网卡名>
```

## 12. systemd 常驻服务

如需 PC2 开机后自动启动 API，可创建 systemd 服务文件。默认只绑定本机：

```bash
sudo tee /etc/systemd/system/g1-motion-player-api.service >/dev/null <<'EOF'
[Unit]
Description=G1 Motion Player API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/unitree/g1_motion_player
ExecStart=/home/unitree/g1_motion_player/.venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8001
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF
```

把 `/home/unitree/g1_motion_player` 替换为 PC2 上实际仓库路径。

如果需要同一可信局域网内的外部电脑访问，把 `ExecStart` 的 `--host 127.0.0.1` 改为 `--host 0.0.0.0`，访问地址使用 PC2 机器人网卡 IP，例如 `http://192.168.123.164:8001/api/replay`。当前主分支没有认证，只能在可信网络或受防火墙限制的环境中这样做。

启用服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable g1-motion-player-api
sudo systemctl start g1-motion-player-api
sudo systemctl status g1-motion-player-api --no-pager
```

查看日志：

```bash
journalctl -u g1-motion-player-api -f
```

## 13. 更新部署

已有仓库时，在 PC2 执行：

```bash
cd /home/unitree/g1_motion_player
git status --short --branch
git fetch origin
git switch main
git pull --ff-only origin main
git submodule update --init --recursive
source .venv/bin/activate
python -m pip install -e .
cmake -S . -B build
cmake --build build -j"$(nproc)" --target csv_replay
```

如果 `git status --short --branch` 显示本地有未提交修改，先停下来确认，不要直接覆盖。

## 14. 快速排查

### API 起不来

```bash
source .venv/bin/activate
python -m compileall -q api tests
python -m uvicorn api.main:app --host 127.0.0.1 --port 8001
```

### 接口能 dry-run 但真实执行失败

检查：

- `build/csv_replay` 是否存在并可执行。
- 仓库默认网卡是否是实际机器人通信网卡；当前默认 `eth0`。
- `thirdparty/unitree_sdk2` 子模块是否完整。
- PC2 是否能通过 Unitree SDK DDS 与机器人通信。

### 上传 CSV 被拒绝

CSV 必须满足：

- UTF-8 文本。
- 每个有效行 36 列。
- 所有值是有限数字。
- 请求体不超过 10 MiB。
