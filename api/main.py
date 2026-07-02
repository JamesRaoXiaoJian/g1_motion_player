from __future__ import annotations

import asyncio
import csv
import json
import os
from pathlib import Path
from uuid import uuid4
from typing import Any

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .csv_motion import (
    CsvMotionError,
    parse_motion_json_frames,
    discover_motions,
    load_motion_csv,
    load_motion_csv_as_json,
    load_motion_json,
    CSV_ASSETS_DIR,
    JSON_ASSETS_DIR,
    resolve_csv_path,
)

CSV_DIR = CSV_ASSETS_DIR
JSON_DIR = JSON_ASSETS_DIR


class ApiError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class MotionFramePayload(BaseModel):
    id: int | None = None
    time: float | None = None
    poseData: list[float]
    jointValues: dict[str, float] = Field(default_factory=dict)


class ReplayRequest(BaseModel):
    motion: str | None = None
    csv_path: str | None = None
    motion_json: list[MotionFramePayload] | None = None
    fps: float = 60.0
    net: str = "eno0"
    dry_run: bool = True


class CreateMotionRequest(BaseModel):
    name: str
    motion_json: list[MotionFramePayload]
    fps: float = 60.0
    overwrite: bool = False


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
    if exc.code in {"invalid_request", "invalid_csv", "invalid_json"}:
        return 400
    return 400


def _require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    expected_key = os.getenv("MOTION_API_KEY")
    if expected_key is None:
        return

    provided = x_api_key
    if authorization:
        parts = authorization.strip().split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            provided = parts[1]

    if not provided or provided != expected_key:
        raise ApiError("unauthorized", "Missing or invalid API key.", 401)


async def _run_csv_replay(
    repo_root: Path,
    csv_path: str,
    fps: float,
    net: str,
) -> dict[str, Any]:
    binary = repo_root / "build" / "csv_replay"
    if not binary.exists():
        raise ApiError(
            "replay_error",
            f"csv_replay binary not found at {binary}. Build the project first.",
            500,
        )

    cmd = [str(binary), str(csv_path), str(int(fps)), net]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(repo_root),
    )
    stdout, stderr = await proc.communicate()
    return {
        "returncode": proc.returncode,
        "stdout": stdout.decode(errors="replace").strip(),
        "stderr": stderr.decode(errors="replace").strip(),
    }


async def _run_json_replay(
    repo_root: Path,
    json_payload: str,
    fps: float,
    net: str,
) -> dict[str, Any]:
    binary = repo_root / "build" / "json_replay"
    if not binary.exists():
        raise ApiError(
            "replay_error",
            f"json_replay binary not found at {binary}. Build the project first.",
            500,
        )

    cmd = [str(binary), "--stdin", str(int(fps)), net]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(repo_root),
    )
    stdout, stderr = await proc.communicate(input=json_payload.encode(errors="utf-8"))
    return {
        "returncode": proc.returncode,
        "stdout": stdout.decode(errors="replace").strip(),
        "stderr": stderr.decode(errors="replace").strip(),
    }


def _sanitize_artifact_stem(name: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in name.strip())
    return safe or "payload"


def _payload_paths(repo_root: Path, stem: str) -> tuple[Path, Path]:
    stem = _sanitize_artifact_stem(stem)
    return (
        repo_root / JSON_DIR / f"{stem}.json",
        repo_root / CSV_DIR / f"{stem}.csv",
    )


def _serialize_motion_json(frames: list[MotionFramePayload]) -> str:
    return json.dumps([frame.model_dump() for frame in frames], ensure_ascii=False)


def _validate_motion_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise ApiError("invalid_request", "motion name must not be empty.", 400)

    motion_path = Path(normalized)
    if (
        normalized in {".", ".."}
        or "/" in normalized
        or "\\" in normalized
        or motion_path.name != normalized
        or motion_path.is_absolute()
    ):
        raise ApiError("invalid_request", "motion name must be a simple file stem.", 400)

    safe_name = _sanitize_artifact_stem(normalized)
    if safe_name != normalized:
        raise ApiError("invalid_request", "motion name contains unsupported characters.", 400)
    return safe_name


def _write_payload_artifacts(
    json_path: Path,
    csv_path: Path,
    frames: list[MotionFramePayload],
) -> tuple[Path, Path]:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    json_path.write_text(
        _serialize_motion_json(frames),
        encoding="utf-8",
    )

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        for frame in frames:
            writer.writerow([f"{value:.10g}" for value in frame.poseData])
    return json_path, csv_path


async def _schedule_payload_artifacts(
    repo_root: Path,
    stem: str,
    frames: list[MotionFramePayload],
) -> tuple[Path, Path]:
    json_path, csv_path = _payload_paths(repo_root, stem)
    await asyncio.to_thread(_write_payload_artifacts, json_path, csv_path, frames)
    return json_path, csv_path


def _silence_task_errors(task: asyncio.Task[Any]) -> None:
    try:
        task.result()
    except Exception:
        pass


def _validate_replay_request(
    repo_root: Path,
    request_data: ReplayRequest,
) -> dict[str, Any]:
    if request_data.fps <= 0 or request_data.fps > 240:
        raise ApiError(
            "invalid_request",
            "fps must be greater than 0 and less than or equal to 240.",
            400,
        )
    if not request_data.net.strip():
        raise ApiError("invalid_request", "net must not be empty.", 400)

    has_source = sum(
        bool(flag)
        for flag in (
            bool(request_data.motion),
            bool(request_data.csv_path),
            bool(request_data.motion_json),
        )
    )
    if has_source != 1:
        raise ApiError(
            "invalid_request",
            "Provide exactly one of: motion, csv_path, motion_json.",
            400,
        )

    if request_data.motion_json is not None:
        metadata = load_motion_json(
            [frame.model_dump() for frame in request_data.motion_json],
            source_name=request_data.motion or "payload",
            fps=request_data.fps,
        )
        return {
            "motion": request_data.motion or "payload",
            "csv_path": None,
            "fps": request_data.fps,
            "net": request_data.net,
            "dry_run": request_data.dry_run,
            "source_type": "motion_json",
            "frames": metadata.frames,
            "duration_seconds": metadata.duration_seconds,
            "controlled_joint_count": metadata.controlled_joint_count,
            "first_frame_arm_joints": metadata.first_frame_arm_joints,
        }

    csv_path = resolve_csv_path(repo_root, request_data.motion, request_data.csv_path)
    metadata = load_motion_csv(csv_path, repo_root=repo_root)
    return {
        "motion": request_data.motion or metadata.name,
        "csv_path": metadata.csv_path,
        "fps": request_data.fps,
        "net": request_data.net,
        "dry_run": request_data.dry_run,
        "source_type": "motion_csv",
        "frames": metadata.frames,
        "duration_seconds": metadata.duration_seconds,
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

    @app.get("/api/motions/{motion}/json")
    async def motion_json(motion: str, fps: float = 60.0) -> JSONResponse:
        if fps <= 0:
            raise ApiError("invalid_request", "fps must be greater than 0.", 400)
        csv_path = resolve_csv_path(root, motion=motion, csv_path=None)
        metadata = load_motion_csv(csv_path, repo_root=root)
        frames = load_motion_csv_as_json(csv_path, fps=fps)
        return success(
            {
                "motion": metadata.name,
                "fps": fps,
                "duration_seconds": len(frames) / fps,
                "frame_count": metadata.frames,
                "frames": frames,
            }
        )

    @app.get("/api/motions/{motion}")
    async def motion_metadata(motion: str) -> JSONResponse:
        csv_path = resolve_csv_path(root, motion=motion, csv_path=None)
        metadata = load_motion_csv(csv_path, repo_root=root)
        return success(metadata.to_dict())

    @app.post("/api/motions")
    async def create_motion(
        request_data: CreateMotionRequest,
        _api_key: None = Depends(_require_api_key),
    ) -> JSONResponse:
        if request_data.fps <= 0 or request_data.fps > 240:
            raise ApiError(
                "invalid_request",
                "fps must be greater than 0 and less than or equal to 240.",
                400,
            )

        name = _validate_motion_name(request_data.name)
        parse_motion_json_frames([frame.model_dump() for frame in request_data.motion_json])
        metadata = load_motion_json(
            [frame.model_dump() for frame in request_data.motion_json],
            source_name=name,
            fps=request_data.fps,
        )

        json_path, csv_path = _payload_paths(root, name)
        if not request_data.overwrite and (json_path.exists() or csv_path.exists()):
            raise ApiError(
                "motion_exists",
                f"motion '{name}' already exists.",
                409,
            )

        _write_payload_artifacts(
            json_path=json_path,
            csv_path=csv_path,
            frames=request_data.motion_json,
        )

        return success(
            {
                "motion": metadata.name,
                "motion_json_path": str(json_path.relative_to(root)),
                "motion_csv_path": str(csv_path.relative_to(root)),
                "frames": metadata.frames,
                "duration_seconds": metadata.duration_seconds,
                "fps": request_data.fps,
                "controlled_joint_count": metadata.controlled_joint_count,
                "first_frame_arm_joints": metadata.first_frame_arm_joints,
            }
        )

    @app.post("/api/replay/validate")
    async def validate_replay(
        request_data: ReplayRequest,
        _api_key: None = Depends(_require_api_key),
    ) -> JSONResponse:
        return success(_validate_replay_request(root, request_data))

    @app.post("/api/replay")
    async def replay(
        request_data: ReplayRequest,
        _api_key: None = Depends(_require_api_key),
    ) -> JSONResponse:
        if request_data.dry_run:
            return success(_validate_replay_request(root, request_data))

        validated = _validate_replay_request(root, request_data)
        if validated["source_type"] == "motion_json":
            motion_frames = request_data.motion_json
            if motion_frames is None:
                raise ApiError("invalid_request", "motion_json is required.", 400)

            payload = _serialize_motion_json(motion_frames)
            artifact_stem = request_data.motion or f"payload_{uuid4().hex[:8]}"
            json_path, csv_path = _payload_paths(root, artifact_stem)
            background_task = asyncio.create_task(
                _schedule_payload_artifacts(root, artifact_stem, motion_frames)
            )
            background_task.add_done_callback(_silence_task_errors)
            result = await _run_json_replay(
                repo_root=root,
                json_payload=payload,
                fps=validated["fps"],
                net=validated["net"],
            )
            validated["replay"] = result
            validated["debug_json_path"] = str(json_path.relative_to(root))
            validated["debug_csv_path"] = str(csv_path.relative_to(root))
            if result["returncode"] != 0:
                raise ApiError(
                    "replay_error",
                    f"json_replay exited with code {result['returncode']}: {result['stderr']}",
                    500,
                )
            return success(validated)

        result = await _run_csv_replay(
            repo_root=root,
            csv_path=validated["csv_path"],
            fps=validated["fps"],
            net=validated["net"],
        )
        validated["replay"] = result
        if result["returncode"] != 0:
            raise ApiError(
                "replay_error",
                f"csv_replay exited with code {result['returncode']}: {result['stderr']}",
                500,
            )
        return success(validated)

    return app


app = create_app()
