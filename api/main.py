from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .csv_motion import (
    CsvMotionError,
    discover_motions,
    load_motion_csv,
    load_motion_csv_as_json,
    load_motion_json,
    resolve_csv_path,
)


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
            "csv_path": request_data.motion or "payload",
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

    @app.post("/api/replay/validate")
    async def validate_replay(request_data: ReplayRequest) -> JSONResponse:
        return success(_validate_replay_request(root, request_data))

    return app


app = create_app()
