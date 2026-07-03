from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .csv_motion import ASSETS_DIR, CsvMotionError, MotionMetadata, load_motion_csv


MAX_CSV_BYTES = 10 * 1024 * 1024
DEFAULT_REPLAY_FPS = 50.0
DEFAULT_ROBOT_NET = "eth0"
UPLOAD_DIR = ASSETS_DIR / "uploads"


class ApiError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class ReplayInput:
    csv_text: str
    save_as: str | None
    source_filename: str | None
    fps: float
    dry_run: bool


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
    if exc.code in {"invalid_request", "invalid_csv"}:
        return 400
    return 400


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

    cmd = [str(binary), csv_path, f"{fps:g}", net]
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


def _content_type(request: Request) -> str:
    return request.headers.get("content-type", "").split(";", 1)[0].strip().lower()


def _parse_float(value: Any, name: str, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ApiError("invalid_request", f"{name} must be a number.", 400) from exc
    return parsed


def _parse_bool(value: Any, name: str, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ApiError("invalid_request", f"{name} must be a boolean.", 400)


def _validate_fps(fps: float) -> float:
    if fps <= 0 or fps > 240:
        raise ApiError(
            "invalid_request",
            "fps must be greater than 0 and less than or equal to 240.",
            400,
        )
    return fps


def _decode_csv_bytes(raw: bytes) -> str:
    if len(raw) > MAX_CSV_BYTES:
        raise ApiError("invalid_request", "CSV payload is too large.", 413)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CsvMotionError("invalid_csv", "CSV must be valid UTF-8.") from exc


def _validate_csv_text(csv_text: str) -> str:
    if not csv_text.strip():
        raise ApiError("invalid_request", "CSV payload must not be empty.", 400)
    if len(csv_text.encode("utf-8")) > MAX_CSV_BYTES:
        raise ApiError("invalid_request", "CSV payload is too large.", 413)
    return csv_text


def _validate_save_as(raw_name: str) -> str:
    name = raw_name.strip()
    if name.lower().endswith(".csv"):
        name = name[:-4]
    path = Path(name)
    if (
        not name
        or name in {".", ".."}
        or path.name != name
        or "/" in name
        or "\\" in name
        or path.is_absolute()
    ):
        raise ApiError("invalid_request", "save_as must be a simple CSV file stem.", 400)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise ApiError(
            "invalid_request",
            "save_as may only contain ASCII letters, numbers, '.', '_' and '-'.",
            400,
        )
    if name.startswith("."):
        raise ApiError("invalid_request", "save_as must not start with '.'.", 400)
    return name


def _default_upload_stem(source_filename: str | None) -> str:
    source_stem = Path(source_filename or "upload").stem
    safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", source_stem).strip("._-")
    if not safe_stem:
        safe_stem = "upload"
    return f"{safe_stem}_{uuid4().hex[:8]}"


def _target_csv_path(repo_root: Path, save_as: str | None, source_filename: str | None) -> Path:
    stem = _validate_save_as(save_as) if save_as else _default_upload_stem(source_filename)
    return (repo_root / UPLOAD_DIR / f"{stem}.csv").resolve()


def _store_uploaded_csv(
    repo_root: Path,
    csv_text: str,
    save_as: str | None,
    source_filename: str | None,
) -> MotionMetadata:
    final_path = _target_csv_path(repo_root, save_as, source_filename)
    uploads_dir = (repo_root / UPLOAD_DIR).resolve()
    try:
        final_path.relative_to(uploads_dir)
    except ValueError as exc:
        raise ApiError("invalid_request", "upload path must stay inside assets/uploads.", 400) from exc

    uploads_dir.mkdir(parents=True, exist_ok=True)
    pending_path = final_path.with_name(f".{final_path.stem}.{uuid4().hex}.tmp")
    try:
        pending_path.write_text(csv_text, encoding="utf-8", newline="")
        load_motion_csv(pending_path, repo_root=repo_root)
        pending_path.replace(final_path)
    except Exception:
        pending_path.unlink(missing_ok=True)
        raise

    return load_motion_csv(final_path, repo_root=repo_root)


def _response_payload(metadata: MotionMetadata, replay_input: ReplayInput) -> dict[str, Any]:
    data = metadata.to_dict()
    data.update(
        {
            "source_type": "uploaded_csv",
            "fps": replay_input.fps,
            "dry_run": replay_input.dry_run,
            "duration_seconds": metadata.frames / replay_input.fps,
        }
    )
    return data


def _json_value(data: dict[str, Any], name: str, default: Any = None) -> Any:
    return data.get(name, default)


async def _parse_json_body_replay_request(request: Request) -> ReplayInput:
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise ApiError("invalid_request", "Request body must be valid JSON.", 400) from exc
    if not isinstance(payload, dict):
        raise ApiError("invalid_request", "JSON body must be an object.", 400)

    csv_text = payload.get("csv_data", payload.get("csv_text"))
    if not isinstance(csv_text, str):
        raise ApiError("invalid_request", "JSON body must include csv_data as a string.", 400)

    fps = _validate_fps(_parse_float(_json_value(payload, "fps"), "fps", DEFAULT_REPLAY_FPS))
    return ReplayInput(
        csv_text=_validate_csv_text(csv_text),
        save_as=_json_value(payload, "save_as"),
        source_filename=None,
        fps=fps,
        dry_run=_parse_bool(_json_value(payload, "dry_run"), "dry_run", True),
    )


async def _parse_multipart_replay_request(request: Request) -> ReplayInput:
    try:
        form = await request.form()
    except AssertionError as exc:
        raise ApiError(
            "invalid_request",
            "multipart/form-data requires the python-multipart package.",
            400,
        ) from exc

    file_part = form.get("file")
    source_filename: str | None = None
    if file_part is not None and hasattr(file_part, "read"):
        source_filename = getattr(file_part, "filename", None)
        raw = await file_part.read(MAX_CSV_BYTES + 1)
        csv_text = _decode_csv_bytes(raw)
    else:
        csv_data = form.get("csv_data")
        if not isinstance(csv_data, str):
            raise ApiError(
                "invalid_request",
                "multipart/form-data must include file or csv_data.",
                400,
            )
        csv_text = csv_data

    fps = _validate_fps(_parse_float(form.get("fps"), "fps", DEFAULT_REPLAY_FPS))
    save_as = form.get("save_as")
    return ReplayInput(
        csv_text=_validate_csv_text(csv_text),
        save_as=str(save_as) if save_as else None,
        source_filename=source_filename,
        fps=fps,
        dry_run=_parse_bool(form.get("dry_run"), "dry_run", True),
    )


async def _parse_raw_csv_replay_request(request: Request) -> ReplayInput:
    raw = await request.body()
    csv_text = _decode_csv_bytes(raw)
    query = request.query_params
    fps = _validate_fps(_parse_float(query.get("fps"), "fps", DEFAULT_REPLAY_FPS))
    return ReplayInput(
        csv_text=_validate_csv_text(csv_text),
        save_as=query.get("save_as"),
        source_filename=None,
        fps=fps,
        dry_run=_parse_bool(query.get("dry_run"), "dry_run", True),
    )


async def _parse_replay_request(request: Request) -> ReplayInput:
    content_type = _content_type(request)
    if content_type == "application/json":
        return await _parse_json_body_replay_request(request)
    if content_type == "multipart/form-data":
        return await _parse_multipart_replay_request(request)
    if content_type in {"text/csv", "application/csv"}:
        return await _parse_raw_csv_replay_request(request)
    raise ApiError(
        "invalid_request",
        "POST /api/replay expects application/json, multipart/form-data, or text/csv.",
        400,
    )


def create_app(repo_root: Path | None = None) -> FastAPI:
    root = (repo_root or Path(__file__).resolve().parents[1]).resolve()
    app = FastAPI(
        title="G1 Motion Player CSV Replay API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.exception_handler(ApiError)
    async def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.code, exc.message, exc.status_code)

    @app.exception_handler(CsvMotionError)
    async def handle_csv_error(_: Request, exc: CsvMotionError) -> JSONResponse:
        return error_response(exc.code, exc.message, _status_for_csv_error(exc))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response("invalid_request", str(exc), 400)

    @app.post("/api/replay")
    async def replay(request: Request) -> JSONResponse:
        replay_input = await _parse_replay_request(request)
        metadata = _store_uploaded_csv(
            root,
            replay_input.csv_text,
            replay_input.save_as,
            replay_input.source_filename,
        )
        data = _response_payload(metadata, replay_input)
        if replay_input.dry_run:
            return success(data)

        result = await _run_csv_replay(
            repo_root=root,
            csv_path=data["csv_path"],
            fps=replay_input.fps,
            net=DEFAULT_ROBOT_NET,
        )
        data["replay"] = result
        if result["returncode"] != 0:
            raise ApiError(
                "replay_error",
                f"csv_replay exited with code {result['returncode']}: {result['stderr']}",
                500,
            )
        return success(data)

    return app


app = create_app()
