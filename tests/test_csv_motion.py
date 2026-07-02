from pathlib import Path
import json

import pytest

from api.csv_motion import (
    CsvMotionError,
    discover_motions,
    load_motion_csv_as_json,
    load_motion_csv,
    load_motion_json,
    resolve_csv_path,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_load_motion_csv_returns_metadata_for_asset_wave():
    metadata = load_motion_csv(REPO_ROOT / "assets" / "csv" / "wave.csv")

    assert metadata.name == "wave"
    assert metadata.csv_path == "assets/csv/wave.csv"
    assert metadata.frames == 600
    assert metadata.columns == 36
    assert metadata.controlled_joint_count == 17
    assert metadata.duration_seconds == pytest.approx(600 / 60.0)
    assert metadata.first_frame_arm_joints[:2] == pytest.approx([0.0868397, 0.12404])


def test_load_motion_csv_with_header_row_is_valid():
    metadata = load_motion_csv(REPO_ROOT / "assets" / "csv" / "wave.csv")

    assert metadata.frames == 600


def test_load_motion_json_from_pose_frames():
    metadata = load_motion_json(
        frames=[
            {"poseData": [float(index) for index in range(36)], "time": 0},
            {"poseData": [float(index) + 1 for index in range(36)], "time": 1},
        ],
        source_name="debug",
        fps=30.0,
    )

    assert metadata.name == "debug"
    assert metadata.frames == 2
    assert metadata.duration_seconds == pytest.approx(2 / 30.0)
    assert metadata.first_frame_arm_joints[:2] == pytest.approx([22.0, 23.0])


def test_load_motion_json_rejects_empty_payload():
    with pytest.raises(CsvMotionError) as excinfo:
        load_motion_json([], source_name="debug")

    assert excinfo.value.code == "invalid_json"


def test_load_motion_json_compatible_with_sample_debug_payload():
    frames = load_motion_csv_as_json(REPO_ROOT / "assets" / "csv" / "wave.csv", fps=50.0)
    metadata = load_motion_json(frames=frames, source_name="wave", fps=50.0)

    assert metadata.name == "wave"
    assert metadata.frames == 600


def test_load_motion_json_rejects_joint_inconsistency():
    pose = [0.0] * 36
    pose[22] = 1.0

    with pytest.raises(CsvMotionError) as excinfo:
        load_motion_json(
            frames=[
                {
                    "poseData": pose,
                    "jointValues": {"left_shoulder_pitch_joint": 10.0},
                }
            ],
            source_name="debug",
            fps=60.0,
        )

    assert excinfo.value.code == "invalid_json"


def test_discover_motions_lists_assets_sorted_by_name():
    motions = discover_motions(REPO_ROOT)

    names = [motion.name for motion in motions]
    assert names == ["wave", "zuoyi"]
    assert all(motion.frames == 600 for motion in motions)


def test_resolve_csv_path_accepts_motion_name():
    resolved = resolve_csv_path(REPO_ROOT, motion="wave", csv_path=None)

    assert resolved == REPO_ROOT / "assets" / "csv" / "wave.csv"


def test_resolve_csv_path_rejects_ambiguous_source():
    with pytest.raises(CsvMotionError) as excinfo:
        resolve_csv_path(REPO_ROOT, motion="wave", csv_path="assets/csv/wave.csv")

    assert excinfo.value.code == "invalid_request"
    assert "mutually exclusive" in excinfo.value.message


def test_resolve_csv_path_rejects_path_outside_repo():
    with pytest.raises(CsvMotionError) as excinfo:
        resolve_csv_path(REPO_ROOT, motion=None, csv_path="../outside.csv")

    assert excinfo.value.code == "invalid_request"
    assert "inside the repository" in excinfo.value.message


def test_resolve_csv_path_rejects_non_csv_suffix():
    with pytest.raises(CsvMotionError) as excinfo:
        resolve_csv_path(REPO_ROOT, motion=None, csv_path="README.md")

    assert excinfo.value.code == "invalid_request"


def test_resolve_csv_path_rejects_directory():
    with pytest.raises(CsvMotionError) as excinfo:
        resolve_csv_path(REPO_ROOT, motion=None, csv_path="assets")

    assert excinfo.value.code == "invalid_request"


def test_resolve_csv_path_rejects_parent_path_motion_name():
    with pytest.raises(CsvMotionError) as excinfo:
        resolve_csv_path(REPO_ROOT, motion="../wave", csv_path=None)

    assert excinfo.value.code == "invalid_request"


def test_resolve_csv_path_rejects_nested_motion_name():
    with pytest.raises(CsvMotionError) as excinfo:
        resolve_csv_path(REPO_ROOT, motion="nested/wave", csv_path=None)

    assert excinfo.value.code == "invalid_request"


def test_load_motion_csv_counts_final_row_without_trailing_newline(tmp_path):
    csv_path = tmp_path / "motion.csv"
    row = ",".join(str(index) for index in range(36))
    csv_path.write_text(f"{row}\n{row}", encoding="utf-8")

    metadata = load_motion_csv(csv_path, repo_root=tmp_path)

    assert metadata.frames == 2


def test_load_motion_csv_rejects_non_utf8_file(tmp_path):
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_bytes(b"\xff\xfe\x00\x00")

    with pytest.raises(CsvMotionError) as excinfo:
        load_motion_csv(bad_csv, repo_root=tmp_path)

    assert excinfo.value.code == "invalid_csv"


def test_load_motion_csv_rejects_malformed_csv(tmp_path):
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text('"unterminated\n', encoding="utf-8")

    with pytest.raises(CsvMotionError) as excinfo:
        load_motion_csv(bad_csv, repo_root=tmp_path)

    assert excinfo.value.code == "invalid_csv"
    assert "valid UTF-8" in excinfo.value.message


def test_load_motion_csv_rejects_short_row_after_valid_row(tmp_path):
    csv_path = tmp_path / "bad.csv"
    valid_row = ",".join("0" for _ in range(36))
    csv_path.write_text(f"{valid_row}\n1,2,3", encoding="utf-8")

    with pytest.raises(CsvMotionError) as excinfo:
        load_motion_csv(csv_path, repo_root=tmp_path)

    assert excinfo.value.code == "invalid_csv"


def test_load_motion_csv_rejects_non_numeric_row_after_valid_row(tmp_path):
    csv_path = tmp_path / "bad.csv"
    valid_row = ",".join("0" for _ in range(36))
    bad_row = ["0"] * 36
    bad_row[7] = "not-a-number"
    csv_path.write_text(f"{valid_row}\n{','.join(bad_row)}", encoding="utf-8")

    with pytest.raises(CsvMotionError) as excinfo:
        load_motion_csv(csv_path, repo_root=tmp_path)

    assert excinfo.value.code == "invalid_csv"


def test_load_motion_csv_rejects_non_finite_values(tmp_path):
    csv_path = tmp_path / "bad.csv"
    row = ["0"] * 36
    row[7] = "nan"
    csv_path.write_text(",".join(row), encoding="utf-8")

    with pytest.raises(CsvMotionError) as excinfo:
        load_motion_csv(csv_path, repo_root=tmp_path)

    assert excinfo.value.code == "invalid_csv"


def test_load_motion_csv_rejects_file_without_valid_frames(tmp_path):
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text("1,2,3\nnot,a,number\n", encoding="utf-8")

    with pytest.raises(CsvMotionError) as excinfo:
        load_motion_csv(bad_csv, repo_root=tmp_path)

    assert excinfo.value.code == "invalid_csv"


def test_csv_to_json_payload_includes_joint_names():
    payload = load_motion_csv_as_json(REPO_ROOT / "assets" / "csv" / "wave.csv", fps=50.0)
    first = payload[0]

    assert len(payload) == 600
    assert first["id"] == 0
    assert first["time"] == 0.0
    assert first["poseData"][0] == pytest.approx(0.0303281)
    assert first["jointValues"]["left_shoulder_pitch_joint"] == pytest.approx(4.975548304182215, rel=1e-9)


def test_debug_json_payload_matches_csv_relation():
    frames = json.loads((REPO_ROOT / "assets" / "json" / "wave.json").read_text(encoding="utf-8"))
    metadata = load_motion_json(frames=frames, source_name="wave", fps=60.0)

    assert metadata.name == "wave"
    assert metadata.frames == 600
    assert metadata.first_frame_arm_joints[:2] == pytest.approx([0.0868397, 0.12404], rel=1e-9)


def test_zuoyi_debug_json_payload_matches_csv_relation():
    frames = json.loads((REPO_ROOT / "assets" / "json" / "zuoyi.json").read_text(encoding="utf-8"))
    metadata = load_motion_json(frames=frames, source_name="zuoyi", fps=60.0)

    csv_metadata = load_motion_csv(REPO_ROOT / "assets" / "csv" / "zuoyi.csv")

    assert metadata.name == "zuoyi"
    assert metadata.frames == 600
    assert metadata.frames == csv_metadata.frames
    assert metadata.first_frame_arm_joints == pytest.approx(csv_metadata.first_frame_arm_joints, rel=1e-9)
