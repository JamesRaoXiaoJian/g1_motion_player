# G1 Motion Player API

当前主分支只提供一个接口：

```text
POST /api/replay
```

接口从请求体接收 CSV 数据包，保存到 `assets/uploads/`，校验通过后按 `dry_run` 决定是否调用 `build/csv_replay`。

旧版动作查询、创建、更新、JSON replay 接口已归档到远端分支 `api-json-replay-archive`。
FastAPI 默认的 `/docs`、`/redoc`、`/openapi.json` 也已关闭，运行时只暴露 `POST /api/replay`。

## 执行流程

```text
client
  -> POST /api/replay
  -> FastAPI 解析 CSV 上传或请求体
  -> 写入 assets/uploads/.<name>.tmp
  -> load_motion_csv 校验 36 列数值帧
  -> 校验通过后替换为 assets/uploads/<name>.csv
  -> dry_run=false 时调用 build/csv_replay
  -> csv_replay 通过 rt/arm_sdk 下发动作
```

非法 CSV 只会留下错误响应，不会留下最终上传文件。

## 启动

```bash
source .venv/bin/activate
uvicorn api.main:app --host 127.0.0.1 --port 8000
```

真实执行前必须先编译：

```bash
cmake -S . -B build
cmake --build build -j"$(nproc)"
```

## 请求方式

### multipart/form-data

字段：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `file` | file | 是 | - | CSV 文件 |
| `save_as` | string | 否 | 自动生成 | 保存到 `assets/uploads/<save_as>.csv` |
| `fps` | number | 否 | `50` | 回放帧率，范围 `(0, 240]` |
| `net` | string | 否 | `eno0` | 机器人通信网卡 |
| `dry_run` | bool | 否 | `true` | `true` 只校验，`false` 执行 |

示例：

```bash
curl -X POST http://127.0.0.1:8000/api/replay \
  -F "file=@assets/wave.csv" \
  -F "save_as=wave_upload" \
  -F "fps=50" \
  -F "net=eno0" \
  -F "dry_run=true"
```

### application/json

字段：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `csv_data` | string | 是 | - | CSV 文件完整文本 |
| `save_as` | string | 否 | 自动生成 | 保存到 `assets/uploads/<save_as>.csv` |
| `fps` | number | 否 | `50` | 回放帧率 |
| `net` | string | 否 | `eno0` | 机器人通信网卡 |
| `dry_run` | bool | 否 | `true` | 是否只校验 |

示例：

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

### text/csv

参数放在 query string：

```bash
curl -X POST "http://127.0.0.1:8000/api/replay?save_as=wave_raw&fps=50&net=eno0&dry_run=true" \
  -H "Content-Type: text/csv" \
  --data-binary @assets/wave.csv
```

## 响应

成功：

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

`dry_run=false` 且执行成功时，`data` 会多出：

默认 `fps=50`。如果动作数据需要保持 60fps 原始时间尺度，可在请求中显式传 `fps=60`。

```json
{
  "replay": {
    "returncode": 0,
    "stdout": "...",
    "stderr": ""
  }
}
```

失败：

```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "invalid_csv",
    "message": "CSV rows must contain exactly 36 columns."
  }
}
```

## 错误码

| code | HTTP | 说明 |
|------|------|------|
| `invalid_request` | 400 / 413 | 请求格式、参数、大小或 `save_as` 非法 |
| `invalid_csv` | 400 | CSV 不是 UTF-8、列数不对、非数值或非有限数 |
| `csv_not_found` | 404 | 内部 CSV 路径不存在 |
| `replay_error` | 500 | `csv_replay` 不存在或执行返回非 0 |

## CSV 规则

- UTF-8 文本。
- 每个有效行必须 36 列。
- 所有值必须能解析为有限浮点数。
- 空行会跳过。
- 标准 36 列表头会跳过。
- 最大请求体大小为 10 MiB。

## 安全说明

主分支当前没有内置认证，适合 PC2 本机或可信内网联调。绑定 `0.0.0.0` 前建议使用防火墙限制来源 IP，或在 Nginx/Caddy 等反向代理层加认证。
