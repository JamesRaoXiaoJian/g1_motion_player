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
    assert metadata.frames == 600
    assert metadata.columns == 36
    assert metadata.controlled_joint_count == 17
    assert metadata.duration_seconds == pytest.approx(600 / 60.0)
    assert metadata.first_frame_arm_joints[:2] == pytest.approx([0.0868397, 0.12404])


def test_discover_motions_lists_assets_sorted_by_name():
    motions = discover_motions(REPO_ROOT)

    names = [motion.name for motion in motions]
    assert names == ["wave", "zuoyi"]
    assert all(motion.frames == 600 for motion in motions)


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


def test_load_motion_csv_rejects_file_without_valid_frames(tmp_path):
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text("1,2,3\nnot,a,number\n", encoding="utf-8")

    with pytest.raises(CsvMotionError) as excinfo:
        load_motion_csv(bad_csv, repo_root=tmp_path)

    assert excinfo.value.code == "invalid_csv"
    assert "valid 36-column" in excinfo.value.message
