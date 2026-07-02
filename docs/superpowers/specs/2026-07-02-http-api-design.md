# Local HTTP API Design

## Goal

Add a local HTTP API for `csv_replay` and future robot-control utilities so other programs can pass parameters, receive structured data, and test the interface locally with CSV files in `assets/`.

The first implementation must be useful without a robot connected. It will support dry-run validation that parses motion CSV files, checks parameters, returns metadata, and records replay jobs in memory. Real robot execution will be behind an explicit `dry_run: false` flag.

## Current Context

The project is a small C++/CMake repository. `src/csv_replay.cpp` is currently a single executable that:

- accepts `<csv> [fps] [net]` or the legacy `<net> <csv> [fps]` argument order;
- parses LAFAN1 retargeting CSV files with 36 columns and no header;
- controls the Unitree G1 through DDS topics and therefore requires the robot network for real execution.

The available local test data is:

- `assets/wave.csv`
- `assets/zuoyi.csv`

Each file currently has 599 rows.

## Chosen Approach

Use a Python FastAPI service as a thin local API layer.

Reasons:

- HTTP and JSON are easy to test with `curl`, browser tools, Postman, Python, and frontend code.
- Local dry-run testing can be built without linking against Unitree SDK.
- The existing `csv_replay` executable can stay as the robot-control implementation for now.
- Future utilities such as state recording and FSM mode switching can be added as additional endpoints without changing the external interface style.

Rejected alternatives:

- C++ HTTP server: keeps one language but adds more dependency and build complexity.
- CLI-only JSON wrapper: lighter, but it is not a real HTTP interface and is less convenient for frontend or service integration.

## API Shape

The API will run locally by default.

- Default host: `127.0.0.1`
- Default port: `8000`
- Response format: JSON

All API responses should use this envelope:

```json
{
  "ok": true,
  "data": {},
  "error": null
}
```

Errors should use:

```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "invalid_csv",
    "message": "CSV must contain 36 columns per valid frame."
  }
}
```

## Endpoints

### `GET /health`

Checks whether the API service is running.

Success response:

```json
{
  "ok": true,
  "data": {
    "status": "ok"
  },
  "error": null
}
```

### `GET /api/motions`

Lists motion CSV files under `assets/`.

Each motion item returns:

- `name`: file stem, for example `wave`
- `csv_path`: repository-relative path
- `frames`: valid parsed frame count
- `duration_seconds`: `frames / 60.0` metadata estimate
- `columns`: expected column count, currently `36`

Success response:

```json
{
  "ok": true,
  "data": {
    "motions": [
      {
        "name": "wave",
        "csv_path": "assets/wave.csv",
        "frames": 599,
        "duration_seconds": 9.983333,
        "columns": 36
      }
    ]
  },
  "error": null
}
```

### `POST /api/replay/validate`

Validates replay input without starting a job.

Request:

```json
{
  "motion": "wave",
  "csv_path": null,
  "fps": 60,
  "net": "eno0",
  "dry_run": true
}
```

Rules:

- `motion` and `csv_path` are mutually exclusive.
- `motion` resolves to `assets/<motion>.csv`.
- `csv_path` must point to a CSV inside the repository unless later explicitly expanded.
- `fps` must be greater than `0` and less than or equal to `240`.
- `net` defaults to `eno0`.
- `dry_run` defaults to `true`.

Success data:

```json
{
  "motion": "wave",
  "csv_path": "assets/wave.csv",
  "fps": 60,
  "net": "eno0",
  "dry_run": true,
  "frames": 599,
  "duration_seconds": 9.983333,
  "controlled_joint_count": 17,
  "first_frame_arm_joints": [0.0868397, 0.12404]
}
```

`first_frame_arm_joints` may be truncated in the response to keep payloads small. Full frame streaming is outside the first implementation scope.

### `POST /api/replay/start`

Starts a replay job.

For the first implementation:

- `dry_run: true` creates a completed local job after validation.
- `dry_run: false` starts `build/csv_replay <csv_path> <fps> <net>` as a subprocess if the binary exists.

Request uses the same schema as `/api/replay/validate`.

Success response:

```json
{
  "ok": true,
  "data": {
    "job_id": "replay-20260702-120000-001",
    "status": "completed",
    "dry_run": true,
    "motion": "wave",
    "csv_path": "assets/wave.csv",
    "fps": 60,
    "net": "eno0",
    "frames": 599,
    "duration_seconds": 9.983333
  },
  "error": null
}
```

For real execution, statuses are:

- `running`
- `completed`
- `failed`

### `GET /api/replay/jobs/{job_id}`

Returns stored job details.

Data includes:

- request parameters
- status
- start and finish timestamps
- process exit code for real execution
- captured recent stdout and stderr
- validation metadata

Jobs are kept in memory for the first implementation. Persistence can be added later if needed.

## Data Flow

1. HTTP request reaches FastAPI.
2. Pydantic validates the request schema.
3. API resolves `motion` or `csv_path` to a repository CSV file.
4. CSV parser reads rows, accepts only rows with exactly 36 numeric columns, and maps columns `7-35` to the 29 robot joint values.
5. API builds replay metadata and returns JSON.
6. `/api/replay/start` either records a dry-run job or starts `build/csv_replay` for real execution.

## Error Handling

Expected error codes:

- `invalid_request`: schema or parameter validation failed.
- `motion_not_found`: named asset motion does not exist.
- `csv_not_found`: provided CSV path does not exist.
- `invalid_csv`: CSV has no valid 36-column numeric frames.
- `binary_not_found`: `dry_run: false` requested but `build/csv_replay` is missing.
- `job_not_found`: requested job id does not exist.
- `execution_failed`: real replay process exits unsuccessfully.

HTTP status mapping:

- `200` for successful requests.
- `400` for invalid request data.
- `404` for missing motions, CSV files, or jobs.
- `409` for execution precondition failures such as missing binary.
- `500` for unexpected server errors.

## Local Testing

Initial tests should not require a robot.

Automated tests should cover:

- `GET /health`
- `GET /api/motions` finds `wave` and `zuoyi`
- `POST /api/replay/validate` accepts `motion: "wave"`
- validation rejects missing/ambiguous `motion` and `csv_path`
- validation rejects invalid `fps`
- validation rejects missing CSV files
- `POST /api/replay/start` with `dry_run: true` creates a completed job
- `GET /api/replay/jobs/{job_id}` returns that dry-run job

Manual local test examples:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/motions
curl -X POST http://127.0.0.1:8000/api/replay/validate \
  -H 'Content-Type: application/json' \
  -d '{"motion":"wave","fps":60,"net":"eno0","dry_run":true}'
```

## Implementation Boundary

In the first implementation, do:

- add the FastAPI service;
- add CSV parsing/validation reusable by the API;
- add in-memory replay job tracking;
- add local API tests using `assets/`;
- document how to run the service and test endpoints.

Do not:

- rewrite the C++ robot-control loop;
- add persistent storage;
- stream all CSV frames over HTTP;
- execute real robot replay by default;
- expose the server on a non-localhost interface by default.

## Open Decisions Resolved

- Interface type: HTTP API.
- First implementation framework: Python FastAPI.
- Local testing mode: dry-run with `assets/*.csv`.
- Default safety behavior: no robot execution unless `dry_run` is explicitly set to `false`.
