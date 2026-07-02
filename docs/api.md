# G1 Motion Player API 文档

## 项目运作方式

### 整体架构

```
┌─────────────┐    HTTP     ┌──────────────┐    DDS (rt/arm_sdk)    ┌─────────────┐
│   客户端     │ ──────────→ │   FastAPI     │ ────────────────────→ │   G1 机器人   │
│  curl/前端   │ ←────────── │   :8000       │ ←──────────────────── │   (Unitree)  │
└─────────────┘    JSON     └──────────────┘    rt/lowstate         └─────────────┘
                                  │
                                  │ spawn subprocess
                                  ▼
                           ┌────────────────────┐
                           │ csv_replay         │
                           │ json_replay        │
                           │  (C++ binary)      │
                           └────────────────────┘
```

### 执行流程

1. **客户端** 发送 HTTP 请求到 FastAPI 服务
2. **FastAPI** 解析请求，加载 CSV 或 JSON 动作数据，校验合法性
3. **FastAPI** 调用编译好的 `csv_replay` 或 `json_replay` C++ 二进制（子进程）
4. **csv_replay/json_replay** 通过宇树 SDK 的 DDS 通信（`rt/arm_sdk` 话题）下发关节角度给机器人
5. 机器人执行动作，完成后子进程退出，API 返回结果

### 动作执行的五个阶段

| 阶段 | 时长 | 说明 |
|------|------|------|
| BalanceStand + LowStand | 即时 | 切换平衡站立，降低重心 |
| Engage | ~1s | weight 从 0→1，逐步接管上肢控制 |
| Transition | ~2s | 平滑过渡到 CSV 首帧（速度钳位 0.5 rad/s） |
| Replay | 取决于帧数/fps | 逐帧回放（速度钳位 0.8 rad/s） |
| Disengage | ~4s | 回到初始姿态，weight 从 1→0 交还控制 |

### 关节映射

CSV/JSON 包含 36 个值，程序只驱动上肢 **17 个关节**：

| 索引范围 | 内容 | 是否驱动 |
|----------|------|----------|
| 0-6 | 根节点位置+四元数 | ❌ 忽略 |
| 7-18 | 下肢 12 关节 | ❌ 内置运控控制 |
| 19-21 | 腰部 3 DOF（yaw/roll/pitch） | ✅ SDK 12-14 |
| 22-28 | 左臂 7 DOF | ✅ SDK 15-21 |
| 29-35 | 右臂 7 DOF | ✅ SDK 22-28 |

---

## 启动服务

```bash
# 前台运行（可看日志，Ctrl+C 停止）
python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8000

# 后台运行
nohup python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8000 &
```

---

## 统一响应格式

**成功：**

```json
{
  "ok": true,
  "data": { ... },
  "error": null
}
```

**失败：**

```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "invalid_request",
    "message": "错误描述"
  }
}
```

---

## 接口列表

### 1. `GET /health`

健康检查。

**请求参数：** 无

**响应：**

```json
{
  "ok": true,
  "data": { "status": "ok" },
  "error": null
}
```

---

### 2. `GET /api/motions`

列出 `assets/` 目录下所有合法的动作 CSV 文件。

**请求参数：** 无

**响应示例：**

```json
{
  "ok": true,
  "data": {
    "motions": [
      {
        "name": "wave",
        "csv_path": "assets/csv/wave.csv",
        "frames": 600,
        "duration_seconds": 10.0,
        "columns": 36,
        "controlled_joint_count": 17,
        "first_frame_arm_joints": [
          0.0868397, 0.12404, 0.239799, 1.39578, 0.3531, 0.135927,
          -0.116623, 0.0378742, -0.13948, -0.239799, 1.41144, -0.424301,
          0.0711032, 0.196331, -0.0231218, -0.0155658, -0.0174935
        ]
      }
    ]
  },
  "error": null
}
```

**字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 动作名（文件名去掉 `.csv`） |
| `csv_path` | string | 相对于项目根目录的路径 |
| `frames` | int | 总帧数 |
| `duration_seconds` | float | 时长（秒），按 60fps 计算 |
| `columns` | int | 列数，固定 36 |
| `controlled_joint_count` | int | 实际驱动关节数，固定 17 |
| `first_frame_arm_joints` | float[17] | 首帧上肢 17 关节角度（弧度） |

---

### 3. `GET /api/motions/{motion}/json`

获取指定动作的完整帧数据（JSON 格式）。

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `motion` | string | 动作名，如 `wave`、`zuoyi` |

**查询参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `fps` | float | 60.0 | 帧率，必须 > 0 |

**请求示例：**

```
GET /api/motions/wave/json?fps=30
```

**响应示例：**

```json
{
  "ok": true,
  "data": {
    "motion": "wave",
    "fps": 30.0,
    "duration_seconds": 20.0,
    "frame_count": 600,
    "frames": [
      {
        "id": 0,
        "time": 0.0,
        "poseData": [0.0303281, 0.00633653, 0.793114, ...],
        "jointValues": {
          "left_shoulder_pitch_joint": 4.975,
          "left_shoulder_roll_joint": 7.107,
          "waist_yaw_joint": -1.325,
          ...
        }
      }
    ]
  },
  "error": null
}
```

**frame 字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | int | 帧序号（从 0 开始） |
| `time` | float | 时间戳（秒） |
| `poseData` | float[36] | 36 个关节值（**弧度**），与 CSV 一一对应 |
| `jointValues` | object | 29 个关节名→角度（**度**），仅 SDK 控制的 29 关节 |

---

### 4. `POST /api/replay/validate`

验证回放请求的合法性，不执行动作。请求体与 `/api/replay` 完全相同（见下方）。

**响应示例：**

```json
{
  "ok": true,
  "data": {
    "motion": "wave",
    "csv_path": "assets/csv/wave.csv",
    "fps": 60.0,
    "net": "eno0",
    "dry_run": true,
    "source_type": "motion_csv",
    "frames": 600,
    "duration_seconds": 10.0,
    "controlled_joint_count": 17,
    "first_frame_arm_joints": [0.0868397, ...]
  },
  "error": null
}
```

---

### 5. `POST /api/replay`

执行动作回放。核心接口。

**请求体（JSON）：**

```json
{
  "motion": "wave",
  "fps": 60.0,
  "net": "eno0",
  "dry_run": false
}
```

**请求字段：**

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `motion` | string \| null | 三选一 | null | 动作名（如 `wave`），对应 `assets/csv/{name}.csv` |
| `csv_path` | string \| null | 三选一 | null | CSV 文件相对路径（如 `assets/csv/wave.csv`） |
| `motion_json` | array \| null | 三选一 | null | JSON 帧数据数组（见下方格式） |
| `fps` | float | 否 | 60.0 | 回放帧率，范围 (0, 240] |
| `net` | string | 否 | "eno0" | DDS 网卡名 |
| `dry_run` | bool | 否 | true | `true`=仅验证，`false`=真正执行 |

> **三选一**：`motion`、`csv_path`、`motion_json` 必须且只能提供一个。

**motion_json 帧格式：**

```json
{
  "motion_json": [
    {
      "poseData": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, ...],
      "jointValues": {
        "left_shoulder_pitch_joint": 4.975,
        "right_shoulder_pitch_joint": 2.170
      }
    }
  ]
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `poseData` | float[36] | ✅ | 36 个关节值（弧度），与 CSV 行对应 |
| `jointValues` | object | 否 | 关节名→角度（度），若提供则必须与 poseData[7:36] 一致 |

**成功响应（dry_run=false）：**

```json
{
  "ok": true,
  "data": {
    "motion": "wave",
    "csv_path": "assets/csv/wave.csv",
    "fps": 60.0,
    "net": "eno0",
    "dry_run": false,
    "source_type": "motion_csv",
    "frames": 600,
    "duration_seconds": 10.0,
    "controlled_joint_count": 17,
    "first_frame_arm_joints": [0.0868397, ...],
    "replay": {
      "returncode": 0,
      "stdout": "Loaded 600 frames (10s)\nConnecting via eno0...\n...\nDone: 600 frames in 10.054s",
      "stderr": ""
    }
  },
  "error": null
}
```

**replay 字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `returncode` | int | 进程退出码，0=成功 |
| `stdout` | string | csv_replay 或 json_replay 的标准输出（含完整执行日志） |
| `stderr` | string | 标准错误输出 |

当 `source_type` 为 `motion_json` 时，响应还会带上：

| 字段 | 类型 | 说明 |
|------|------|------|
| `debug_json_path` | string | 写入的 JSON 调试文件（如 `assets/json/<name>.json`） |
| `debug_csv_path` | string | 写入的 CSV 调试文件（如 `assets/csv/<name>.csv`） |

---

### 6. `GET /api/motions/{motion}`

获取单个动作的元数据（与 `GET /api/motions` 列表中的单项一致）。

**响应示例：**

```json
{
  "ok": true,
  "data": {
    "name": "wave",
    "csv_path": "assets/csv/wave.csv",
    "frames": 600,
    "duration_seconds": 10.0,
    "columns": 36,
    "controlled_joint_count": 17,
    "first_frame_arm_joints": [0.0868397, 0.12404, ...]
  },
  "error": null
}
```

### 7. `POST /api/motions`

创建一个动作。

**请求体：**

```json
{
  "name": "demo_payload",
  "motion_json": [
    {
      "time": 0,
      "poseData": [36个浮点数]
    }
  ],
  "fps": 60,
  "overwrite": false
}
```

**响应示例：**

```json
{
  "ok": true,
  "data": {
    "motion": "demo_payload",
    "motion_json_path": "assets/json/demo_payload.json",
    "motion_csv_path": "assets/csv/demo_payload.csv",
    "frames": 1,
    "duration_seconds": 0.0166667,
    "fps": 60,
    "controlled_joint_count": 17,
    "first_frame_arm_joints": [0.0868397, 0.12404, ...]
  },
  "error": null
}
```

当 `overwrite=false` 且同名动作已存在时，返回 `409 motion_exists`。

创建动作会写入 `assets/json/<name>.json` 与 `assets/csv/<name>.csv`，可立即通过
`/api/motions/{motion}` 与 `/api/replay` 使用。

### 8. `PUT /api/motions/{motion}`

更新已存在的动作。该接口会把传入 `motion_json` 全量覆盖到指定动作文件。

**请求体：**

```json
{
  "motion_json": [
    {
      "time": 0,
      "poseData": [36个浮点数]
    }
  ],
  "fps": 60
}
```

**响应示例：**

```json
{
  "ok": true,
  "data": {
    "motion": "wave",
    "motion_json_path": "assets/json/wave.json",
    "motion_csv_path": "assets/csv/wave.csv",
    "frames": 600,
    "duration_seconds": 10.0,
    "fps": 60,
    "controlled_joint_count": 17,
    "first_frame_arm_joints": [0.0868397, 0.12404, ...]
  },
  "error": null
}
```

当目标动作不存在时返回 `404 motion_not_found`。

## 认证说明

如果设置环境变量 `MOTION_API_KEY`，则 `POST /api/replay`、`POST /api/replay/validate`、
`POST /api/motions`、`PUT /api/motions/{motion}` 需要鉴权。支持以下方式之一：

- `Authorization: Bearer <token>`
- `X-API-Key: <token>`

未配置 `MOTION_API_KEY` 时，接口不启用鉴权（兼容本地快速联调）。

---

## 错误码

| code | HTTP 状态码 | 说明 |
|------|-------------|------|
| `invalid_request` | 400 | 参数错误（缺少源、fps 超范围、多个源等） |
| `motion_not_found` | 404 | 动作名不存在 |
| `csv_not_found` | 404 | CSV 文件不存在 |
| `invalid_csv` | 400 | CSV 格式错误（列数、数值等） |
| `invalid_json` | 400 | JSON 帧数据格式错误 |
| `replay_error` | 500 | csv_replay/json_replay 执行失败（二进制不存在或返回非零） |
| `unauthorized` | 401 | API Key 缺失或无效 |
| `motion_exists` | 409 | 新建动作已存在且 `overwrite=false` |

---

## 请求示例

```bash
# 健康检查
curl http://localhost:8000/health

# 列出所有动作
curl http://localhost:8000/api/motions

# 获取动作 JSON 帧
curl "http://localhost:8000/api/motions/wave/json?fps=30"

# 验证（不执行）
curl -X POST http://localhost:8000/api/replay \
  -H "Content-Type: application/json" \
  -d '{"motion": "wave", "fps": 60, "dry_run": true}'

# 执行 wave 动作
curl -X POST http://localhost:8000/api/replay \
  -H "Content-Type: application/json" \
  -d '{"motion": "wave", "fps": 60, "net": "eno0", "dry_run": false}'

# 执行 zuoyi 动作，50fps
curl -X POST http://localhost:8000/api/replay \
  -H "Content-Type: application/json" \
  -d '{"motion": "zuoyi", "fps": 50, "net": "eno0", "dry_run": false}'

# 通过 motion_json 执行
curl -X POST http://localhost:8000/api/replay \
  -H "Content-Type: application/json" \
  -d '{"motion_json": [{"poseData": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], "jointValues": {"waist_pitch_joint": 0.0}}], "dry_run": false}'

# 通过 csv_path 指定文件
curl -X POST http://localhost:8000/api/replay \
  -H "Content-Type: application/json" \
  -d '{"csv_path": "assets/csv/wave.csv", "dry_run": false}'
```
