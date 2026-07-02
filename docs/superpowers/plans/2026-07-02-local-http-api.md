# Local HTTP API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local FastAPI HTTP service that validates and starts G1 CSV replay jobs using `assets/*.csv` for robot-free local testing.

**Architecture:** Add a Python API layer beside the existing C++ tools. CSV parsing and motion discovery live in `api/csv_motion.py`, replay job state and subprocess execution live in `api/jobs.py`, and HTTP endpoints live in `api/main.py`. The first usable path is safe dry-run execution; real robot replay requires `dry_run: false` and an existing `build/csv_replay` binary.

**Tech Stack:** Python 3.9+, FastAPI, Uvicorn, Pydantic, Pytest, HTTPX TestClient.

---

## File Structure

- Create: `pyproject.toml`
  - Defines FastAPI, Uvicorn, Pytest, and HTTPX dependencies.
  - Configures pytest to import the repository root.
- Create: `api/__init__.py`
  - Marks `api` as an importable package, then exports `create_app` after `api/main.py` exists.
- Create: `api/csv_motion.py`
  - Resolves `motion` names and repository-local CSV paths.
  - Parses 36-column LAFAN1 CSV rows.
  - Returns metadata used by endpoints and jobs.
- Create: `api/jobs.py`
  - Stores replay jobs in memory.
  - Creates completed dry-run jobs.
  - Runs real `build/csv_replay` jobs in a background thread when requested.
- Create: `api/main.py`
  - Defines the FastAPI app and all HTTP endpoints.
  - Normalizes success and error response envelopes.
- Create: `tests/test_csv_motion.py`
  - Tests CSV parsing, motion discovery, path resolution, and invalid input behavior.
- Create: `tests/test_api.py`
  - Tests `/health`, `/api/motions`, `/api/replay/validate`, `/api/replay/start`, and `/api/replay/jobs/{job_id}`.
- Modify: `README.md`
  - Documents how to install API dependencies, run the local server, and test dry-run endpoints.

---

### Task 1: Python Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `api/__init__.py`

- [ ] **Step 1: Add Python dependency metadata**

Create `pyproject.toml`:

```toml
[project]
name = "g1-motion-player-api"
version = "0.1.0"
description = "Local HTTP API for G1 motion replay tools"
requires-python = ">=3.9"
dependencies = [
  "fastapi>=0.115,<1",
  "uvicorn[standard]>=0.30,<1"
]

[project.optional-dependencies]
dev = [
  "httpx>=0.27,<1",
  "pytest>=8,<9"
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

- [ ] **Step 2: Add API package entry point**

Create `api/__init__.py`:

```python
"""Local HTTP API package for G1 motion player."""
```

- [ ] **Step 3: Verify dependency metadata parses**

Run:

```bash
python3 -m py_compile api/__init__.py
```

Expected: exit code `0`.

- [ ] **Step 4: Commit scaffold**

Run:

```bash
git add pyproject.toml api/__init__.py
git commit -m "chore: add python api scaffold"
```

---

### Task 2: CSV Motion Parser

**Files:**
- Create: `tests/test_csv_motion.py`
- Create: `api/csv_motion.py`

- [ ] **Step 1: Write failing parser tests**

Create `tests/test_csv_motion.py`:

```python
from pathlib import Path

import pytest

from api.csv_motion import (
    CsvMotionError,
    discover_motions,
    load_motion_csv,
    resolve_csv_path,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_load_motion_csv_returns_metadata_for_asset_wave():
    metadata = load_motion_csv(REPO_ROOT / "assets" / "wave.csv")

    assert metadata.name == "wave"
    assert metadata.csv_path == "assets/wave.csv"
    assert metadata.frames == 599
    assert metadata.columns == 36
    assert metadata.controlled_joint_count == 17
    assert metadata.duration_seconds == pytest.approx(599 / 60.0)
    assert metadata.first_frame_arm_joints[:2] == pytest.approx([0.0868397, 0.12404])


def test_discover_motions_lists_assets_sorted_by_name():
    motions = discover_motions(REPO_ROOT)

    names = [motion.name for motion in motions]
    assert names == ["wave", "zuoyi"]
    assert all(motion.frames == 599 for motion in motions)


def test_resolve_csv_path_accepts_motion_name():
    resolved = resolve_csv_path(REPO_ROOT, motion="wave", csv_path=None)

    assert resolved == REPO_ROOT / "assets" / "wave.csv"


def test_resolve_csv_path_rejects_ambiguous_source():
    with pytest.raises(CsvMotionError) as excinfo:
        resolve_csv_path(REPO_ROOT, motion="wave", csv_path="assets/wave.csv")

    assert excinfo.value.code == "invalid_request"
    assert "mutually exclusive" in excinfo.value.message


def test_resolve_csv_path_rejects_path_outside_repo():
    with pytest.raises(CsvMotionError) as excinfo:
        resolve_csv_path(REPO_ROOT, motion=None, csv_path="../outside.csv")

    assert excinfo.value.code == "invalid_request"
    assert "inside the repository" in excinfo.value.message


def test_load_motion_csv_rejects_file_without_valid_frames(tmp_path):
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text("1,2,3\nnot,a,number\n", encoding="utf-8")

    with pytest.raises(CsvMotionError) as excinfo:
        load_motion_csv(bad_csv, repo_root=tmp_path)

    assert excinfo.value.code == "invalid_csv"
    assert "valid 36-column" in excinfo.value.message
```

- [ ] **Step 2: Run parser tests to verify they fail**

Run:

```bash
/home/james/.local/bin/uv run --extra dev pytest tests/test_csv_motion.py -v
```

Expected: FAIL because `api.csv_motion` does not exist.

- [ ] **Step 3: Add CSV parser implementation**

Create `api/csv_motion.py`:

```python
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path


EXPECTED_COLUMNS = 36
DEFAULT_METADATA_FPS = 60.0
ARM_JOINT_INDICES = (
    15, 16, 17, 18, 19, 20, 21,
    22, 23, 24, 25, 26, 27, 28,
    12, 13, 14,
)


class CsvMotionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class MotionMetadata:
    name: str
    csv_path: str
    frames: int
    duration_seconds: float
    columns: int
    controlled_joint_count: int
    first_frame_arm_joints: list[float]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _repo_relative(path: Path, repo_root: Path | None) -> str:
    if repo_root is None:
        return path.name
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _is_inside_repo(path: Path, repo_root: Path) -> bool:
    try:
        path.resolve().relative_to(repo_root.resolve())
        return True
    except ValueError:
        return False


def _parse_valid_joint_rows(path: Path) -> list[list[float]]:
    frames: list[list[float]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if not row:
                continue
            if len(row) != EXPECTED_COLUMNS:
                continue
            try:
                values = [float(cell) for cell in row]
            except ValueError:
                continue
            frames.append(values[7:36])
    return frames


def load_motion_csv(path: Path, repo_root: Path | None = None) -> MotionMetadata:
    if not path.exists():
        raise CsvMotionError("csv_not_found", f"CSV file does not exist: {path}")
    if not path.is_file():
        raise CsvMotionError("csv_not_found", f"CSV path is not a file: {path}")

    frames = _parse_valid_joint_rows(path)
    if not frames:
        raise CsvMotionError(
            "invalid_csv",
            "CSV must contain at least one valid 36-column numeric frame.",
        )

    first_frame = frames[0]
    first_frame_arm_joints = [first_frame[index] for index in ARM_JOINT_INDICES]
    return MotionMetadata(
        name=path.stem,
        csv_path=_repo_relative(path, repo_root or path.parent.parent),
        frames=len(frames),
        duration_seconds=len(frames) / DEFAULT_METADATA_FPS,
        columns=EXPECTED_COLUMNS,
        controlled_joint_count=len(ARM_JOINT_INDICES),
        first_frame_arm_joints=first_frame_arm_joints,
    )


def discover_motions(repo_root: Path) -> list[MotionMetadata]:
    assets_dir = repo_root / "assets"
    motions: list[MotionMetadata] = []
    for csv_path in sorted(assets_dir.glob("*.csv")):
        motions.append(load_motion_csv(csv_path, repo_root=repo_root))
    return motions


def resolve_csv_path(repo_root: Path, motion: str | None, csv_path: str | None) -> Path:
    has_motion = bool(motion)
    has_csv_path = bool(csv_path)
    if has_motion and has_csv_path:
        raise CsvMotionError(
            "invalid_request",
            "motion and csv_path are mutually exclusive.",
        )
    if not has_motion and not has_csv_path:
        raise CsvMotionError(
            "invalid_request",
            "Either motion or csv_path is required.",
        )

    if has_motion:
        motion_name = str(motion).strip()
        if not motion_name:
            raise CsvMotionError("invalid_request", "motion must not be empty.")
        resolved = repo_root / "assets" / f"{motion_name}.csv"
        if not resolved.exists():
            raise CsvMotionError("motion_not_found", f"Motion not found: {motion_name}")
        return resolved

    raw_path = Path(str(csv_path))
    resolved = raw_path if raw_path.is_absolute() else repo_root / raw_path
    if not _is_inside_repo(resolved, repo_root):
        raise CsvMotionError(
            "invalid_request",
            "csv_path must point to a CSV file inside the repository.",
        )
    if not resolved.exists():
        raise CsvMotionError("csv_not_found", f"CSV file does not exist: {csv_path}")
    return resolved
```

- [ ] **Step 4: Run parser tests to verify they pass**

Run:

```bash
/home/james/.local/bin/uv run --extra dev pytest tests/test_csv_motion.py -v
```

Expected: PASS, `6 passed`.

- [ ] **Step 5: Commit parser**

Run:

```bash
git add api/csv_motion.py tests/test_csv_motion.py
git commit -m "feat: add csv motion parser"
```

---

### Task 3: API Endpoints for Health, Motions, and Validation

**Files:**
- Create: `tests/test_api.py`
- Create: `api/main.py`
- Modify: `api/__init__.py`

- [ ] **Step 1: Write failing endpoint tests**

Create `tests/test_api.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import create_app


REPO_ROOT = Path(__file__).resolve().parents[1]


def make_client() -> TestClient:
    return TestClient(create_app(repo_root=REPO_ROOT))


def test_health_returns_ok_envelope():
    response = make_client().get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "data": {"status": "ok"},
        "error": None,
    }


def test_motions_returns_assets_with_metadata():
    response = make_client().get("/api/motions")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["error"] is None
    assert [motion["name"] for motion in body["data"]["motions"]] == ["wave", "zuoyi"]
    assert body["data"]["motions"][0]["frames"] == 599


def test_validate_accepts_motion_request():
    response = make_client().post(
        "/api/replay/validate",
        json={"motion": "wave", "fps": 60, "net": "eno0", "dry_run": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["error"] is None
    assert body["data"]["motion"] == "wave"
    assert body["data"]["csv_path"] == "assets/wave.csv"
    assert body["data"]["fps"] == 60
    assert body["data"]["net"] == "eno0"
    assert body["data"]["dry_run"] is True
    assert body["data"]["frames"] == 599
    assert body["data"]["controlled_joint_count"] == 17
    assert body["data"]["first_frame_arm_joints"][:2] == [0.0868397, 0.12404]


def test_validate_rejects_invalid_fps():
    response = make_client().post(
        "/api/replay/validate",
        json={"motion": "wave", "fps": 0},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["ok"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "invalid_request"
    assert "fps" in body["error"]["message"]


def test_validate_rejects_missing_motion():
    response = make_client().post(
        "/api/replay/validate",
        json={"fps": 60},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "invalid_request"


def test_validate_rejects_unknown_motion():
    response = make_client().post(
        "/api/replay/validate",
        json={"motion": "missing_motion", "fps": 60},
    )

    assert response.status_code == 404
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "motion_not_found"
```

- [ ] **Step 2: Run endpoint tests to verify they fail**

Run:

```bash
/home/james/.local/bin/uv run --extra dev pytest tests/test_api.py -v
```

Expected: FAIL because `api.main` does not exist.

- [ ] **Step 3: Add FastAPI app with validation endpoint**

Create `api/main.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .csv_motion import CsvMotionError, discover_motions, load_motion_csv, resolve_csv_path


class ApiError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class ReplayRequest(BaseModel):
    motion: str | None = None
    csv_path: str | None = None
    fps: float = 60.0
    net: str = "eno0"
    dry_run: bool = True


def success(data: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"ok": True, "data": data, "error": None},
    )


def error_response(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "ok": False,
            "data": None,
            "error": {"code": code, "message": message},
        },
    )


def _status_for_csv_error(exc: CsvMotionError) -> int:
    if exc.code in {"motion_not_found", "csv_not_found"}:
        return 404
    if exc.code == "invalid_request":
        return 400
    return 400


def _validate_replay_request(repo_root: Path, request_data: ReplayRequest) -> dict[str, Any]:
    if request_data.fps <= 0 or request_data.fps > 240:
        raise ApiError("invalid_request", "fps must be greater than 0 and less than or equal to 240.", 400)
    if not request_data.net.strip():
        raise ApiError("invalid_request", "net must not be empty.", 400)

    csv_path = resolve_csv_path(repo_root, request_data.motion, request_data.csv_path)
    metadata = load_motion_csv(csv_path, repo_root=repo_root)
    return {
        "motion": request_data.motion or metadata.name,
        "csv_path": metadata.csv_path,
        "fps": request_data.fps,
        "net": request_data.net,
        "dry_run": request_data.dry_run,
        "frames": metadata.frames,
        "duration_seconds": metadata.frames / request_data.fps,
        "controlled_joint_count": metadata.controlled_joint_count,
        "first_frame_arm_joints": metadata.first_frame_arm_joints,
    }


def create_app(repo_root: Path | None = None) -> FastAPI:
    root = (repo_root or Path(__file__).resolve().parents[1]).resolve()
    app = FastAPI(title="G1 Motion Player API")

    @app.exception_handler(ApiError)
    async def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.code, exc.message, exc.status_code)

    @app.exception_handler(CsvMotionError)
    async def handle_csv_error(_: Request, exc: CsvMotionError) -> JSONResponse:
        return error_response(exc.code, exc.message, _status_for_csv_error(exc))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response("invalid_request", str(exc), 400)

    @app.get("/health")
    async def health() -> JSONResponse:
        return success({"status": "ok"})

    @app.get("/api/motions")
    async def motions() -> JSONResponse:
        return success({"motions": [motion.to_dict() for motion in discover_motions(root)]})

    @app.post("/api/replay/validate")
    async def validate_replay(request_data: ReplayRequest) -> JSONResponse:
        return success(_validate_replay_request(root, request_data))

    return app


app = create_app()
```

Replace `api/__init__.py` with:

```python
from .main import create_app

__all__ = ["create_app"]
```

- [ ] **Step 4: Run endpoint tests to verify they pass**

Run:

```bash
/home/james/.local/bin/uv run --extra dev pytest tests/test_api.py -v
```

Expected: PASS for the six endpoint tests in `tests/test_api.py`.

- [ ] **Step 5: Run all current Python tests**

Run:

```bash
/home/james/.local/bin/uv run --extra dev pytest -v
```

Expected: PASS for parser and API tests.

- [ ] **Step 6: Commit endpoints**

Run:

```bash
git add api/__init__.py api/main.py tests/test_api.py
git commit -m "feat: add replay validation api"
```

---

### Task 4: Replay Job Store and Start Endpoint

**Files:**
- Modify: `tests/test_api.py`
- Create: `api/jobs.py`
- Modify: `api/main.py`

- [ ] **Step 1: Add failing job endpoint tests**

Append to `tests/test_api.py`:

```python

def test_start_dry_run_creates_completed_job():
    client = make_client()

    response = client.post(
        "/api/replay/start",
        json={"motion": "wave", "fps": 60, "net": "eno0", "dry_run": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "completed"
    assert body["data"]["dry_run"] is True
    assert body["data"]["job_id"].startswith("replay-")
    assert body["data"]["frames"] == 599


def test_get_job_returns_dry_run_job_details():
    client = make_client()
    start_response = client.post(
        "/api/replay/start",
        json={"motion": "zuoyi", "fps": 60, "net": "eno0", "dry_run": True},
    )
    job_id = start_response.json()["data"]["job_id"]

    response = client.get(f"/api/replay/jobs/{job_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["job_id"] == job_id
    assert body["data"]["status"] == "completed"
    assert body["data"]["motion"] == "zuoyi"
    assert body["data"]["exit_code"] == 0
    assert body["data"]["stderr"] == ""


def test_get_job_returns_404_for_unknown_job():
    response = make_client().get("/api/replay/jobs/replay-missing")

    assert response.status_code == 404
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "job_not_found"


def test_start_real_replay_requires_csv_replay_binary():
    response = make_client().post(
        "/api/replay/start",
        json={"motion": "wave", "fps": 60, "net": "eno0", "dry_run": False},
    )

    assert response.status_code == 409
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "binary_not_found"
```

- [ ] **Step 2: Run job tests to verify they fail**

Run:

```bash
/home/james/.local/bin/uv run --extra dev pytest tests/test_api.py -v
```

Expected: FAIL because `/api/replay/start` and `/api/replay/jobs/{job_id}` do not exist.

- [ ] **Step 3: Add in-memory job store**

Create `api/jobs.py`:

```python
from __future__ import annotations

import subprocess
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MAX_CAPTURED_OUTPUT = 4000


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ReplayJob:
    job_id: str
    status: str
    dry_run: bool
    motion: str
    csv_path: str
    fps: float
    net: str
    frames: int
    duration_seconds: float
    started_at: str
    finished_at: str | None
    exit_code: int | None
    stdout: str
    stderr: str
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, ReplayJob] = {}
        self._lock = threading.Lock()
        self._sequence = 0

    def _next_id(self) -> str:
        with self._lock:
            self._sequence += 1
            return f"replay-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{self._sequence:03d}"

    def create_dry_run(self, validation: dict[str, Any]) -> ReplayJob:
        job = ReplayJob(
            job_id=self._next_id(),
            status="completed",
            dry_run=True,
            motion=str(validation["motion"]),
            csv_path=str(validation["csv_path"]),
            fps=float(validation["fps"]),
            net=str(validation["net"]),
            frames=int(validation["frames"]),
            duration_seconds=float(validation["duration_seconds"]),
            started_at=utc_now_iso(),
            finished_at=utc_now_iso(),
            exit_code=0,
            stdout="dry-run completed without robot execution",
            stderr="",
            error=None,
        )
        self._save(job)
        return job

    def start_process(self, validation: dict[str, Any], command: list[str], cwd: Path) -> ReplayJob:
        job = ReplayJob(
            job_id=self._next_id(),
            status="running",
            dry_run=False,
            motion=str(validation["motion"]),
            csv_path=str(validation["csv_path"]),
            fps=float(validation["fps"]),
            net=str(validation["net"]),
            frames=int(validation["frames"]),
            duration_seconds=float(validation["duration_seconds"]),
            started_at=utc_now_iso(),
            finished_at=None,
            exit_code=None,
            stdout="",
            stderr="",
            error=None,
        )
        self._save(job)

        thread = threading.Thread(
            target=self._run_process,
            args=(job.job_id, command, cwd),
            daemon=True,
        )
        thread.start()
        return job

    def get(self, job_id: str) -> ReplayJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def _save(self, job: ReplayJob) -> None:
        with self._lock:
            self._jobs[job.job_id] = job

    def _run_process(self, job_id: str, command: list[str], cwd: Path) -> None:
        try:
            completed = subprocess.run(
                command,
                cwd=str(cwd),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            with self._lock:
                job = self._jobs[job_id]
                job.exit_code = completed.returncode
                job.stdout = completed.stdout[-MAX_CAPTURED_OUTPUT:]
                job.stderr = completed.stderr[-MAX_CAPTURED_OUTPUT:]
                job.finished_at = utc_now_iso()
                job.status = "completed" if completed.returncode == 0 else "failed"
                job.error = None if completed.returncode == 0 else "csv_replay exited unsuccessfully"
        except Exception as exc:
            with self._lock:
                job = self._jobs[job_id]
                job.exit_code = None
                job.stdout = ""
                job.stderr = str(exc)
                job.finished_at = utc_now_iso()
                job.status = "failed"
                job.error = str(exc)
```

- [ ] **Step 4: Add start and job lookup routes**

Modify `api/main.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .csv_motion import CsvMotionError, discover_motions, load_motion_csv, resolve_csv_path
from .jobs import JobStore


class ApiError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class ReplayRequest(BaseModel):
    motion: str | None = None
    csv_path: str | None = None
    fps: float = 60.0
    net: str = "eno0"
    dry_run: bool = True


def success(data: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"ok": True, "data": data, "error": None},
    )


def error_response(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "ok": False,
            "data": None,
            "error": {"code": code, "message": message},
        },
    )


def _status_for_csv_error(exc: CsvMotionError) -> int:
    if exc.code in {"motion_not_found", "csv_not_found"}:
        return 404
    if exc.code == "invalid_request":
        return 400
    return 400


def _validate_replay_request(repo_root: Path, request_data: ReplayRequest) -> dict[str, Any]:
    if request_data.fps <= 0 or request_data.fps > 240:
        raise ApiError("invalid_request", "fps must be greater than 0 and less than or equal to 240.", 400)
    if not request_data.net.strip():
        raise ApiError("invalid_request", "net must not be empty.", 400)

    csv_path = resolve_csv_path(repo_root, request_data.motion, request_data.csv_path)
    metadata = load_motion_csv(csv_path, repo_root=repo_root)
    return {
        "motion": request_data.motion or metadata.name,
        "csv_path": metadata.csv_path,
        "fps": request_data.fps,
        "net": request_data.net,
        "dry_run": request_data.dry_run,
        "frames": metadata.frames,
        "duration_seconds": metadata.frames / request_data.fps,
        "controlled_joint_count": metadata.controlled_joint_count,
        "first_frame_arm_joints": metadata.first_frame_arm_joints,
    }


def create_app(repo_root: Path | None = None, job_store: JobStore | None = None) -> FastAPI:
    root = (repo_root or Path(__file__).resolve().parents[1]).resolve()
    jobs = job_store or JobStore()
    app = FastAPI(title="G1 Motion Player API")

    @app.exception_handler(ApiError)
    async def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.code, exc.message, exc.status_code)

    @app.exception_handler(CsvMotionError)
    async def handle_csv_error(_: Request, exc: CsvMotionError) -> JSONResponse:
        return error_response(exc.code, exc.message, _status_for_csv_error(exc))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response("invalid_request", str(exc), 400)

    @app.get("/health")
    async def health() -> JSONResponse:
        return success({"status": "ok"})

    @app.get("/api/motions")
    async def motions() -> JSONResponse:
        return success({"motions": [motion.to_dict() for motion in discover_motions(root)]})

    @app.post("/api/replay/validate")
    async def validate_replay(request_data: ReplayRequest) -> JSONResponse:
        return success(_validate_replay_request(root, request_data))

    @app.post("/api/replay/start")
    async def start_replay(request_data: ReplayRequest) -> JSONResponse:
        validation = _validate_replay_request(root, request_data)
        if request_data.dry_run:
            return success(jobs.create_dry_run(validation).to_dict())

        binary = root / "build" / "csv_replay"
        if not binary.exists():
            raise ApiError(
                "binary_not_found",
                "build/csv_replay does not exist. Build the C++ project before dry_run false.",
                409,
            )

        command = [
            str(binary),
            str(root / str(validation["csv_path"])),
            str(validation["fps"]),
            str(validation["net"]),
        ]
        return success(jobs.start_process(validation, command, cwd=root).to_dict())

    @app.get("/api/replay/jobs/{job_id}")
    async def get_job(job_id: str) -> JSONResponse:
        job = jobs.get(job_id)
        if job is None:
            raise ApiError("job_not_found", f"Replay job not found: {job_id}", 404)
        return success(job.to_dict())

    return app


app = create_app()
```

- [ ] **Step 5: Run API tests to verify they pass**

Run:

```bash
/home/james/.local/bin/uv run --extra dev pytest tests/test_api.py -v
```

Expected: PASS for all API tests.

- [ ] **Step 6: Run all Python tests**

Run:

```bash
/home/james/.local/bin/uv run --extra dev pytest -v
```

Expected: PASS for parser and API tests.

- [ ] **Step 7: Commit job endpoints**

Run:

```bash
git add api/jobs.py api/main.py tests/test_api.py
git commit -m "feat: add replay job api"
```

---

### Task 5: README API Documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add API usage documentation**

Append this section to `README.md` after the build section or before the robot usage section:

````markdown
## Local HTTP API

The project includes a local FastAPI service for testing replay parameters and CSV parsing before connecting to the robot.

Install and run with `uv`:

```bash
/home/james/.local/bin/uv sync --extra dev
/home/james/.local/bin/uv run uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

List asset motions:

```bash
curl http://127.0.0.1:8000/api/motions
```

Validate a dry-run replay request:

```bash
curl -X POST http://127.0.0.1:8000/api/replay/validate \
  -H 'Content-Type: application/json' \
  -d '{"motion":"wave","fps":60,"net":"eno0","dry_run":true}'
```

Start a local dry-run job:

```bash
curl -X POST http://127.0.0.1:8000/api/replay/start \
  -H 'Content-Type: application/json' \
  -d '{"motion":"zuoyi","fps":60,"net":"eno0","dry_run":true}'
```

Real robot replay is disabled by default. To execute the existing C++ replay binary through the API, build the project first and send `"dry_run": false`. The service runs on `127.0.0.1` by default.
````

- [ ] **Step 2: Verify README Markdown context**

Run:

```bash
rg -n "Local HTTP API|uvicorn api.main:app|dry_run" README.md
```

Expected: output contains the new section heading and the three API command examples.

- [ ] **Step 3: Commit documentation**

Run:

```bash
git add README.md
git commit -m "docs: document local http api"
```

---

### Task 6: Final Verification

**Files:**
- Read: `docs/superpowers/specs/2026-07-02-http-api-design.md`
- Read: `docs/superpowers/plans/2026-07-02-local-http-api.md`
- Verify: whole repository state

- [ ] **Step 1: Run Python tests**

Run:

```bash
/home/james/.local/bin/uv run --extra dev pytest -v
```

Expected: all tests pass.

- [ ] **Step 2: Compile Python files**

Run:

```bash
python3 -m py_compile api/__init__.py api/csv_motion.py api/jobs.py api/main.py
```

Expected: exit code `0`.

- [ ] **Step 3: Start local server for manual API verification**

Run:

```bash
/home/james/.local/bin/uv run uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Expected: server starts and logs that Uvicorn is running on `http://127.0.0.1:8000`.

- [ ] **Step 4: Verify HTTP endpoints manually in another shell**

Run:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/motions
curl -X POST http://127.0.0.1:8000/api/replay/validate \
  -H 'Content-Type: application/json' \
  -d '{"motion":"wave","fps":60,"net":"eno0","dry_run":true}'
curl -X POST http://127.0.0.1:8000/api/replay/start \
  -H 'Content-Type: application/json' \
  -d '{"motion":"wave","fps":60,"net":"eno0","dry_run":true}'
```

Expected: each response has `"ok": true`; the start response includes a `job_id` and `"status": "completed"`.

- [ ] **Step 5: Stop the local server**

Use `Ctrl-C` in the server shell.

Expected: Uvicorn exits cleanly.

- [ ] **Step 6: Check git status**

Run:

```bash
git status --short
```

Expected: no unstaged implementation changes remain.

---

## Self-Review Notes

- Spec coverage: The plan covers the FastAPI service, CSV parsing, dry-run validation, in-memory jobs, local tests using `assets/`, README usage docs, and explicit `dry_run: false` real execution through `build/csv_replay`.
- Scope: The plan does not rewrite C++ replay logic, add persistent storage, stream all frames, or expose the server beyond localhost.
- Type consistency: `ReplayRequest`, `MotionMetadata`, `ReplayJob`, `JobStore`, `create_app`, and response envelope keys are used consistently across tasks.
