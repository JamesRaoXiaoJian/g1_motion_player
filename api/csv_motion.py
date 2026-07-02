from __future__ import annotations

import csv
import math
from dataclasses import asdict, dataclass
from pathlib import Path


EXPECTED_COLUMNS = 36
DEFAULT_METADATA_FPS = 60.0
ASSETS_DIR = Path("assets")
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
    return normalized == list(CSV_HEADER) or normalized_without_bom == list(CSV_HEADER)


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


def discover_motions(repo_root: Path) -> list[MotionMetadata]:
    assets_dir = (repo_root / ASSETS_DIR).resolve()
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
        assets_dir = (repo_root / ASSETS_DIR).resolve()
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
