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
        raise ApiError(
            "invalid_request",
            "fps must be greater than 0 and less than or equal to 240.",
            400,
        )
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
