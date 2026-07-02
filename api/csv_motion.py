from __future__ import annotations

import csv
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


EXPECTED_COLUMNS = 36
DEFAULT_METADATA_FPS = 60.0
POSE_JOINT_DEGREES_SCALE = 180.0 / math.pi
CSV_HEADER = (
    "root_pos_x",
    "root_pos_y",
    "root_pos_z",
    "root_quat_x",
    "root_quat_y",
    "root_quat_z",
    "root_quat_w",
    "left_hip_pitch_joint",
    "left_hip_roll_joint",
    "left_hip_yaw_joint",
    "left_knee_joint",
    "left_ankle_joint",
    "left_ankle_roll_joint",
    "right_hip_pitch_joint",
    "right_hip_roll_joint",
    "right_hip_yaw_joint",
    "right_knee_joint",
    "right_ankle_joint",
    "right_ankle_roll_joint",
    "waist_yaw_joint",
    "waist_roll_joint",
    "waist_pitch_joint",
    "left_shoulder_pitch_joint",
    "left_shoulder_roll_joint",
    "left_shoulder_yaw_joint",
    "left_elbow_joint",
    "left_wrist_roll_joint",
    "left_wrist_pitch_joint",
    "left_wrist_yaw_joint",
    "right_shoulder_pitch_joint",
    "right_shoulder_roll_joint",
    "right_shoulder_yaw_joint",
    "right_elbow_joint",
    "right_wrist_roll_joint",
    "right_wrist_pitch_joint",
    "right_wrist_yaw_joint",
)
SDK_JOINT_COLUMNS = CSV_HEADER[7:]

ARM_JOINT_INDICES = (
    15,
    16,
    17,
    18,
    19,
    20,
    21,
    22,
    23,
    24,
    25,
    26,
    27,
    28,
    12,
    13,
    14,
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


@dataclass(frozen=True)
class ParsedMotionCsv:
    frames: int
    first_frame: list[float]
    rows: list[list[float]]


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


def _looks_like_header(row: list[str]) -> bool:
    normalized = [cell.strip() for cell in row]
    normalized_without_bom = [cell.lstrip("\ufeff").strip() for cell in row]
    if normalized == list(CSV_HEADER):
        return True
    if normalized_without_bom == list(CSV_HEADER):
        return True
    return False


def _parse_motion_csv_rows(path: Path) -> ParsedMotionCsv:
    frames = 0
    first_frame: list[float] | None = None
    rows: list[list[float]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle, strict=True)
        for row in reader:
            if not row:
                continue
            if len(row) != EXPECTED_COLUMNS:
                raise CsvMotionError(
                    "invalid_csv",
                    "CSV rows must contain exactly 36 columns.",
                )
            if _looks_like_header(row):
                continue
            try:
                values = [float(cell) for cell in row]
            except ValueError as exc:
                raise CsvMotionError(
                    "invalid_csv",
                    "CSV rows must contain numeric values.",
                ) from exc
            if not all(math.isfinite(value) for value in values):
                raise CsvMotionError(
                    "invalid_csv",
                    "CSV must contain only finite numeric values.",
                )
            frames += 1
            rows.append(values)
            if first_frame is None:
                first_frame = values[7:36]
    if first_frame is None:
        raise CsvMotionError(
            "invalid_csv",
            "CSV must contain at least one valid 36-column numeric frame.",
        )
    return ParsedMotionCsv(frames=frames, first_frame=first_frame, rows=rows)


def _coerce_pose_data(raw: Any) -> list[float]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise CsvMotionError(
            "invalid_json",
            "Each frame poseData must be an array of 36 numeric values.",
        )
    if len(raw) != EXPECTED_COLUMNS:
        raise CsvMotionError(
            "invalid_json",
            "Each frame poseData must contain exactly 36 numeric values.",
        )
    try:
        values = [float(item) for item in raw]
    except (TypeError, ValueError) as exc:
        raise CsvMotionError(
            "invalid_json",
            "Each frame poseData must contain numeric values.",
        ) from exc
    if not all(math.isfinite(value) for value in values):
        raise CsvMotionError(
            "invalid_json",
            "JSON motion poseData must contain only finite numeric values.",
        )
    return values


def _coerce_joint_values(raw: Any) -> dict[str, float] | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise CsvMotionError(
            "invalid_json",
            "Each frame jointValues must be an object of joint-name to number.",
        )
    values: dict[str, float] = {}
    for key, value in raw.items():
        if key not in SDK_JOINT_COLUMNS:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise CsvMotionError(
                "invalid_json",
                "Each frame jointValues must contain numeric values.",
            ) from exc
        if not math.isfinite(numeric):
            raise CsvMotionError(
                "invalid_json",
                "JSON motion jointValues must contain only finite numeric values.",
            )
        values[key] = numeric
    return values


def _assert_json_frame_consistency(pose_data: list[float], joint_values: dict[str, float] | None) -> None:
    if not joint_values:
        return
    expected = {
        name: value * POSE_JOINT_DEGREES_SCALE for name, value in zip(SDK_JOINT_COLUMNS, pose_data[7:36])
    }
    for joint_name, expected_value in expected.items():
        if joint_name not in joint_values:
            continue
        if not math.isclose(joint_values[joint_name], expected_value, rel_tol=1e-6, abs_tol=1e-6):
            raise CsvMotionError(
                "invalid_json",
                f"jointValues[{joint_name}] does not match poseData.",
            )


def parse_motion_json_frames(frames: Sequence[Mapping[str, Any]]) -> list[list[float]]:
    if not frames:
        raise CsvMotionError("invalid_json", "motion_json must contain at least one frame.")
    rows: list[list[float]] = []
    for frame in frames:
        if not isinstance(frame, Mapping):
            raise CsvMotionError("invalid_json", "motion_json entries must be objects.")
        pose_data = _coerce_pose_data(frame.get("poseData"))
        joint_values = _coerce_joint_values(frame.get("jointValues"))
        _assert_json_frame_consistency(pose_data, joint_values)
        rows.append(pose_data)
    return rows


def load_motion_csv(path: Path, repo_root: Path | None = None) -> MotionMetadata:
    if not path.exists():
        raise CsvMotionError("csv_not_found", f"CSV file does not exist: {path}")
    if not path.is_file():
        raise CsvMotionError("csv_not_found", f"CSV path is not a file: {path}")

    try:
        parsed = _parse_motion_csv_rows(path)
    except (UnicodeDecodeError, csv.Error, OSError) as exc:
        raise CsvMotionError(
            "invalid_csv",
            "CSV must contain valid UTF-8 numeric rows.",
        ) from exc
    if not parsed.frames:
        raise CsvMotionError(
            "invalid_csv",
            "CSV must contain at least one valid 36-column numeric frame.",
        )

    first_frame = parsed.first_frame
    first_frame_arm_joints = [first_frame[index] for index in ARM_JOINT_INDICES]
    return MotionMetadata(
        name=path.stem,
        csv_path=_repo_relative(path, repo_root or path.parent.parent),
        frames=parsed.frames,
        duration_seconds=parsed.frames / DEFAULT_METADATA_FPS,
        columns=EXPECTED_COLUMNS,
        controlled_joint_count=len(ARM_JOINT_INDICES),
        first_frame_arm_joints=first_frame_arm_joints,
    )


def load_motion_json(
    frames: Sequence[Mapping[str, Any]],
    source_name: str,
    fps: float = DEFAULT_METADATA_FPS,
) -> MotionMetadata:
    rows = parse_motion_json_frames(frames)
    if not rows:
        raise CsvMotionError("invalid_json", "motion_json must contain at least one frame.")
    first_frame = rows[0][7:36]
    first_frame_arm_joints = [first_frame[index] for index in ARM_JOINT_INDICES]
    return MotionMetadata(
        name=source_name,
        csv_path=source_name,
        frames=len(rows),
        duration_seconds=len(rows) / fps,
        columns=EXPECTED_COLUMNS,
        controlled_joint_count=len(ARM_JOINT_INDICES),
        first_frame_arm_joints=first_frame_arm_joints,
    )


def csv_rows_to_json_payload(
    frames: Sequence[Sequence[float]],
    source_name: str | None = None,
    fps: float = DEFAULT_METADATA_FPS,
) -> list[dict[str, Any]]:
    if fps <= 0:
        raise CsvMotionError("invalid_request", "fps must be greater than 0.")
    result: list[dict[str, Any]] = []
    for index, row in enumerate(frames):
        if len(row) != EXPECTED_COLUMNS:
            raise CsvMotionError(
                "invalid_csv",
                "CSV rows must contain exactly 36 columns.",
            )
        row_values = [float(value) for value in row]
        result.append(
            {
                "id": index,
                "time": round(index / fps, 6),
                "poseData": row_values,
                "jointValues": {
                    name: float(value) * POSE_JOINT_DEGREES_SCALE
                    for name, value in zip(SDK_JOINT_COLUMNS, row_values[7:36])
                },
            }
        )
    return result


def load_motion_csv_as_json(path: Path, fps: float = DEFAULT_METADATA_FPS) -> list[dict[str, Any]]:
    parsed = _parse_motion_csv_rows(path)
    return csv_rows_to_json_payload(parsed.rows, source_name=path.stem, fps=fps)


def discover_motions(repo_root: Path) -> list[MotionMetadata]:
    assets_dir = repo_root / "assets"
    motions: list[MotionMetadata] = []
    for csv_path in sorted(assets_dir.glob("*.csv")):
        try:
            motions.append(load_motion_csv(csv_path, repo_root=repo_root))
        except CsvMotionError:
            continue
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
        motion_path = Path(motion_name)
        if (
            not motion_name
            or motion_name in {".", ".."}
            or motion_path.name != motion_name
            or "/" in motion_name
            or "\\" in motion_name
            or motion_path.is_absolute()
        ):
            raise CsvMotionError(
                "invalid_request",
                "motion must be a motion name, not a path.",
            )
        assets_dir = (repo_root / "assets").resolve()
        resolved = (assets_dir / f"{motion_name}.csv").resolve()
        if not _is_inside_repo(resolved, assets_dir):
            raise CsvMotionError(
                "invalid_request",
                "motion must be a motion name, not a path.",
            )
        if not resolved.exists() or not resolved.is_file():
            raise CsvMotionError("motion_not_found", f"Motion not found: {motion_name}")
        return resolved

    raw_path = Path(str(csv_path))
    resolved = raw_path if raw_path.is_absolute() else repo_root / raw_path
    if not _is_inside_repo(resolved, repo_root):
        raise CsvMotionError(
            "invalid_request",
            "csv_path must point to a CSV file inside the repository.",
        )
    if resolved.exists() and not resolved.is_file():
        raise CsvMotionError(
            "invalid_request",
            "csv_path must point to a CSV file.",
        )
    if resolved.suffix.lower() != ".csv":
        raise CsvMotionError(
            "invalid_request",
            "csv_path must point to a CSV file.",
        )
    if not resolved.exists() or not resolved.is_file():
        raise CsvMotionError("csv_not_found", f"CSV file does not exist: {csv_path}")
    return resolved
