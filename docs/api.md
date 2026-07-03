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
python -m uvicorn api.main:app --host 127.0.0.1 --port 8001
```

真实执行前必须先编译：

```bash
cmake -S . -B build
cmake --build build -j"$(nproc)"
```

## 请求方式

接口支持三种请求体格式，三种格式最终都会把 CSV 保存到 `assets/uploads/`，并返回同一类响应。

通用规则：

- API 不接收 `net` 参数。机器人通信网卡由服务端部署配置决定。
- 未传 `fps` 时使用 `50`。
- 未传 `dry_run` 时使用 `true`，只校验和保存，不执行机器人动作。
- 真实执行必须显式传 `dry_run=false`。

### multipart/form-data

字段：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `file` | file | 否 | - | CSV 文件。`file` 和 `csv_data` 至少传一个；两者都传时优先使用 `file`。 |
| `csv_data` | string | 否 | - | CSV 文件完整文本。适合不方便 multipart 文件上传时使用。 |
| `save_as` | string | 否 | 自动生成 | 保存文件名，不含目录。可传 `wave_run` 或 `wave_run.csv`，最终保存为 `assets/uploads/wave_run.csv`。只允许 ASCII 字母、数字、`.`、`_`、`-`，不能以 `.` 开头。 |
| `fps` | number | 否 | `50` | 回放帧率，范围 `(0, 240]`。影响 `duration_seconds` 和真实执行速度。 |
| `dry_run` | bool | 否 | `true` | `true` 只保存和校验 CSV；`false` 会调用 `build/csv_replay` 真实执行。可用 `true/false`、`1/0`、`yes/no`、`on/off`。 |

示例：

```bash
curl -X POST http://127.0.0.1:8001/api/replay \
  -F "file=@assets/wave.csv" \
  -F "save_as=wave_upload" \
  -F "fps=50" \
  -F "dry_run=true"
```

### application/json

字段：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `csv_data` | string | 是 | - | CSV 文件完整文本。也兼容字段名 `csv_text`。 |
| `save_as` | string | 否 | 自动生成 | 保存文件名，不含目录。规则同 multipart。 |
| `fps` | number | 否 | `50` | 回放帧率，范围 `(0, 240]`。 |
| `dry_run` | bool | 否 | `true` | `true` 只保存和校验；`false` 真实执行。 |

示例：

```bash
python3 - <<'PY'
import json
from pathlib import Path

payload = {
    "csv_data": Path("assets/wave.csv").read_text(encoding="utf-8"),
    "save_as": "wave_json_body",
    "fps": 50,
    "dry_run": True,
}
Path("/tmp/replay.json").write_text(json.dumps(payload), encoding="utf-8")
PY

curl -X POST http://127.0.0.1:8001/api/replay \
  -H "Content-Type: application/json" \
  --data-binary @/tmp/replay.json
```

### text/csv

请求体直接放 CSV 文本，参数放在 query string：

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `save_as` | string | 否 | 自动生成 | 保存文件名，不含目录。规则同 multipart。 |
| `fps` | number | 否 | `50` | 回放帧率，范围 `(0, 240]`。 |
| `dry_run` | bool | 否 | `true` | `true` 只保存和校验；`false` 真实执行。 |

```bash
curl -X POST "http://127.0.0.1:8001/api/replay?save_as=wave_raw&fps=50&dry_run=true" \
  -H "Content-Type: text/csv" \
  --data-binary @assets/wave.csv
```

## 响应

所有响应都使用统一外层结构：

| 字段 | 类型 | 说明 |
|------|------|------|
| `ok` | bool | 请求是否成功。 |
| `data` | object/null | 成功时为结果对象，失败时为 `null`。 |
| `error` | object/null | 失败时为错误对象，成功时为 `null`。 |

成功时 `data` 字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 保存后的动作名，即 CSV 文件名去掉 `.csv`。 |
| `csv_path` | string | 服务端保存路径，相对仓库根目录。 |
| `frames` | number | CSV 有效帧数。 |
| `duration_seconds` | number | 按 `frames / fps` 计算的时长。 |
| `columns` | number | CSV 列数，合法文件应为 `36`。 |
| `controlled_joint_count` | number | 当前回放控制的关节数量，当前为 `17`。 |
| `first_frame_arm_joints` | number[] | 第一帧中受控的上肢和腰部关节值，用于检查动作起始姿态。 |
| `source_type` | string | 当前固定为 `uploaded_csv`。 |
| `fps` | number | 本次请求采用的回放帧率。 |
| `dry_run` | bool | 本次请求是否只校验。 |
| `replay` | object | 仅 `dry_run=false` 且执行成功时出现。 |

成功示例：

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
    "dry_run": true
  },
  "error": null
}
```

默认 `fps=50`。如果动作数据需要保持 60fps 原始时间尺度，可在请求中显式传 `fps=60`。

`dry_run=false` 且执行成功时，`data.replay` 会包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| `returncode` | number | `build/csv_replay` 进程退出码。成功为 `0`。 |
| `stdout` | string | `csv_replay` 标准输出。 |
| `stderr` | string | `csv_replay` 标准错误。 |

```json
{
  "replay": {
    "returncode": 0,
    "stdout": "...",
    "stderr": ""
  }
}
```

失败时 `error` 字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | string | 稳定错误码。 |
| `message` | string | 面向调用方的错误说明。 |

失败示例：

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
