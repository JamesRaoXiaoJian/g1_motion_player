from pathlib import Path
import pytest

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
    assert body["data"]["motions"][0]["frames"] == 600


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
    assert body["data"]["frames"] == 600
    assert body["data"]["controlled_joint_count"] == 17
    assert body["data"]["first_frame_arm_joints"][:2] == [0.0868397, 0.12404]
    assert body["data"]["source_type"] == "motion_csv"


def test_validate_accepts_motion_json_payload():
    response = make_client().post(
        "/api/replay/validate",
        json={
            "motion_json": [
                {"time": 0, "poseData": [float(i) for i in range(36)]},
                {"time": 1, "poseData": [float(i + 1) for i in range(36)]},
            ],
            "fps": 30,
            "net": "eno0",
            "dry_run": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["error"] is None
    assert body["data"]["source_type"] == "motion_json"
    assert body["data"]["frames"] == 2
    assert body["data"]["duration_seconds"] == 2 / 30


def test_validate_rejects_multiple_sources():
    response = make_client().post(
        "/api/replay/validate",
        json={
            "motion": "wave",
            "motion_json": [
                {"time": 0, "poseData": [0] * 36},
            ],
            "fps": 60,
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_request"


def test_validate_rejects_motion_json_inconsistent_joint_values():
    response = make_client().post(
        "/api/replay/validate",
        json={
            "motion_json": [
                {
                    "time": 0,
                    "poseData": [0.0] * 22 + [1.0] + [0.0] * 13,
                    "jointValues": {"left_shoulder_pitch_joint": 10.0},
                }
            ],
            "fps": 30,
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "invalid_json"


def test_motion_json_endpoint_returns_payload():
    response = make_client().get("/api/motions/wave/json?fps=50")

    assert response.status_code == 200
    body = response.json()

    assert body["ok"] is True
    assert body["data"]["motion"] == "wave"
    assert body["data"]["fps"] == 50.0
    assert body["data"]["frames"][0]["id"] == 0
    assert body["data"]["frames"][0]["time"] == 0.0
    assert body["data"]["frames"][0]["jointValues"]["left_shoulder_pitch_joint"] == pytest.approx(4.9755, rel=1e-3)
    assert body["data"]["frame_count"] == 600


def test_motion_json_endpoint_returns_zuoyi_payload():
    response = make_client().get("/api/motions/zuoyi/json?fps=50")

    assert response.status_code == 200
    body = response.json()

    assert body["ok"] is True
    assert body["data"]["motion"] == "zuoyi"
    assert body["data"]["fps"] == 50.0
    assert body["data"]["frames"][0]["id"] == 0
    assert body["data"]["frames"][0]["time"] == 0.0
    assert body["data"]["frame_count"] == 600


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
