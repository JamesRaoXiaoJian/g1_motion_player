# G1 Motion Player

Unitree G1 动作回放工具。当前主分支只保留 CSV 执行链路：

- C++ 执行层：`csv_replay` 读取 CSV，通过 Unitree SDK DDS 话题 `rt/arm_sdk` 下发动作。
- HTTP 接口层：FastAPI 只提供 `POST /api/replay`，从请求体接收 CSV 数据包，校验后保存并按需调用 `csv_replay`。
- 示例动作：`assets/wave.csv`、`assets/zuoyi.csv`。

之前的动作查询、创建、更新、JSON replay 版本已归档到远端分支 `api-json-replay-archive`。主分支不再存放 JSON 动作数据，也不再构建 `json_replay`。

## 执行策略

`csv_replay` 默认使用 nearest-window 策略：

- 进入动作时，在动作开头 2 秒窗口内选择最接近机器人当前姿态的帧作为入口。
- 退出动作时，在动作结尾 2 秒窗口内选择最接近初始姿态的帧作为退出。
- Transition 和 Replay 阶段都有速度钳位，减少初始姿态与动作首帧差异过大时的失衡。

## 目录结构

```text
g1_motion_player/
├── api/
│   ├── main.py                # FastAPI: POST /api/replay
│   └── csv_motion.py          # CSV 校验与元数据解析
├── assets/
│   ├── wave.csv
│   └── zuoyi.csv
├── src/
│   ├── csv_replay.cpp         # 生产回放程序
│   ├── csv_replay_debug.cpp   # rt/user_lowcmd 调试程序
│   ├── g1_mode_switch.cpp
│   ├── state_recorder.cpp
│   └── test_connection.cpp
├── tests/
└── thirdparty/unitree_sdk2/    # git submodule
```

## 环境要求

推荐在 G1 的 PC2 或同一有线网段的 Ubuntu 机器上运行：

- Ubuntu 20.04 / 22.04
- x86_64 或 aarch64
- GCC 9.4+
- CMake 3.5+
- Python 3.9+
- Unitree G1 与运行机器在同一有线网络

安装基础依赖：

```bash
sudo apt-get update
sudo apt-get install -y \
  git cmake g++ build-essential pkg-config \
  python3 python3-venv python3-pip
```

拉取子模块：

```bash
git submodule update --init --recursive
```

Python 环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

编译 C++：

```bash
cmake -S . -B build
cmake --build build -j"$(nproc)"
```

编译完成后至少应存在：

```text
build/csv_replay
build/state_recorder
build/test_connection
```

## 在 G1 PC2 上运行

完整部署步骤见 [docs/g1_robot_deployment.md](docs/g1_robot_deployment.md)。远端拉取和部署提示词见 [docs/remote_pull_prompt.md](docs/remote_pull_prompt.md)。

先确认网卡名：

```bash
ip link
```

如果 PC2 上机器人通信网卡是 `eno0`，可直接本地执行：

```bash
./build/csv_replay assets/wave.csv 50 eno0
```

命令格式：

```bash
./build/csv_replay <csv文件> [fps] [网卡]
```

常用示例：

```bash
./build/csv_replay assets/wave.csv
./build/csv_replay assets/wave.csv 50 eno0
./build/csv_replay assets/zuoyi.csv 50 eno0
```

默认回放频率为 50Hz，贴近宇树官方 G1 `rt/arm_sdk` 示例。若要保持 600 帧动作按 10 秒播放，可显式传 `fps=60`。

## 启动 API

本机测试建议只绑定 `127.0.0.1`：

```bash
source .venv/bin/activate
uvicorn api.main:app --host 127.0.0.1 --port 8000
```

如果要让同网段其他机器调用，再绑定 `0.0.0.0`，并确认网络只暴露在可信局域网：

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

当前主分支没有内置认证；如果要开放到非本机环境，建议先在外层加反向代理认证或防火墙限制来源 IP。
FastAPI 默认的 `/docs`、`/redoc`、`/openapi.json` 也已关闭，运行时只暴露 `POST /api/replay`。

## POST /api/replay

接口只接收请求里的 CSV 数据，不接收动作名或 JSON motion 帧。

默认 `dry_run=true`，只保存并校验 CSV，不执行机器人动作。真实执行必须显式传 `dry_run=false`，且 `build/csv_replay` 已编译存在。
未传 `fps` 时默认按 50Hz 执行；需要按 60fps 原始时间尺度回放时，可以显式传 `fps=60`。

### multipart 上传

```bash
curl -X POST http://127.0.0.1:8000/api/replay \
  -F "file=@assets/wave.csv" \
  -F "save_as=wave_upload" \
  -F "fps=50" \
  -F "net=eno0" \
  -F "dry_run=true"
```

真实执行：

```bash
curl -X POST http://127.0.0.1:8000/api/replay \
  -F "file=@assets/wave.csv" \
  -F "save_as=wave_run" \
  -F "fps=50" \
  -F "net=eno0" \
  -F "dry_run=false"
```

### JSON 请求体传 CSV 文本

```bash
python3 - <<'PY'
import json
from pathlib import Path

payload = {
    "csv_data": Path("assets/wave.csv").read_text(encoding="utf-8"),
    "save_as": "wave_json_body",
    "fps": 50,
    "net": "eno0",
    "dry_run": True,
}
Path("/tmp/replay.json").write_text(json.dumps(payload), encoding="utf-8")
PY

curl -X POST http://127.0.0.1:8000/api/replay \
  -H "Content-Type: application/json" \
  --data-binary @/tmp/replay.json
```

### raw text/csv

```bash
curl -X POST "http://127.0.0.1:8000/api/replay?save_as=wave_raw&fps=50&net=eno0&dry_run=true" \
  -H "Content-Type: text/csv" \
  --data-binary @assets/wave.csv
```

成功响应会包含保存路径：

```json
{
  "ok": true,
  "data": {
    "name": "wave_upload",
    "csv_path": "assets/uploads/wave_upload.csv",
    "frames": 600,
    "duration_seconds": 12.0,
    "columns": 36,
    "controlled_joint_count": 17,
    "first_frame_arm_joints": [0.0868397],
    "source_type": "uploaded_csv",
    "fps": 50,
    "net": "eno0",
    "dry_run": true
  },
  "error": null
}
```

上传文件会保存在 `assets/uploads/`。非法 CSV 会被拒绝，不会留下最终文件。

## CSV 格式

每行必须是 36 列 UTF-8 数值，可带一行标准表头：

- 0-6：root position + quaternion，当前回放忽略。
- 7-18：下肢 12 关节，当前回放不主动驱动。
- 19-21：腰部 3 DOF。
- 22-28：左臂 7 DOF。
- 29-35：右臂 7 DOF。

`csv_replay` 实际驱动上肢和腰部 17 个关节。

## 测试与检查

```bash
python3 -m compileall -q api tests
python3 -m pytest
g++ -std=c++17 -I. tests/replay_planner_test.cpp -o /tmp/replay_planner_test
/tmp/replay_planner_test
```

如果本机没有安装 Python 依赖，先执行：

```bash
python -m pip install -e ".[dev]"
```

## 常见问题

### `csv_replay binary not found`

先编译：

```bash
cmake -S . -B build
cmake --build build -j"$(nproc)"
```

### 机器人没有动作

检查：

- `net` 是否是实际机器人通信网卡，例如 `eno0`。
- G1 与 PC2 是否在同一有线网段。
- `build/test_connection` 是否能正常连接。
- 是否误用了默认 `dry_run=true`。真实执行要传 `dry_run=false`。

### CSV 被拒绝

CSV 必须是 UTF-8、每行 36 列、所有值都能解析为有限数值。空行会被跳过，标准表头会被跳过。
