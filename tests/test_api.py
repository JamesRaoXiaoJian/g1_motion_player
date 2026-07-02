from pathlib import Path
import pytest
import shutil

from fastapi.testclient import TestClient

from api.main import create_app


REPO_ROOT = Path(__file__).resolve().parents[1]


def make_client() -> TestClient:
    return TestClient(create_app(repo_root=REPO_ROOT))


def make_client_for_root(root: Path) -> TestClient:
    return TestClient(create_app(repo_root=root))


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


def test_motions_detail_returns_metadata():
    response = make_client().get("/api/motions/wave")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["name"] == "wave"
    assert body["data"]["csv_path"] == "assets/csv/wave.csv"
    assert body["data"]["frames"] == 600


def test_create_motion_with_json_payload(tmp_path: Path):
    root = tmp_path
    (root / "assets/csv").mkdir(parents=True, exist_ok=True)
    (root / "assets/json").mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO_ROOT / "assets/csv/wave.csv", root / "assets/csv/wave.csv")
    client = make_client_for_root(root)

    response = client.post(
        "/api/motions",
        json={
            "name": "demo_payload",
            "fps": 30,
            "motion_json": [
                {"time": 0, "poseData": [float(i) for i in range(36)]},
                {"time": 1, "poseData": [float(i) + 1 for i in range(36)]},
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["motion"] == "demo_payload"
    assert body["data"]["motion_json_path"] == "assets/json/demo_payload.json"
    assert body["data"]["motion_csv_path"] == "assets/csv/demo_payload.csv"
    assert body["data"]["frames"] == 2
    assert (root / "assets/json/demo_payload.json").exists()
    assert (root / "assets/csv/demo_payload.csv").exists()

    detail = client.get("/api/motions/demo_payload").json()
    assert detail["ok"] is True
    assert detail["data"]["frames"] == 2
    assert detail["data"]["duration_seconds"] == pytest.approx(2 / 30)


def test_create_motion_rejects_duplicate_name(tmp_path: Path):
    root = tmp_path
    (root / "assets/csv").mkdir(parents=True, exist_ok=True)
    (root / "assets/json").mkdir(parents=True, exist_ok=True)
    client = make_client_for_root(root)

    payload = {
        "name": "demo",
        "fps": 60,
        "motion_json": [{"time": 0, "poseData": [0.0] * 36}],
    }

    first = client.post("/api/motions", json=payload)
    assert first.status_code == 200

    second = client.post("/api/motions", json=payload)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "motion_exists"


def test_create_motion_with_overwrite(tmp_path: Path):
    root = tmp_path
    (root / "assets/csv").mkdir(parents=True, exist_ok=True)
    (root / "assets/json").mkdir(parents=True, exist_ok=True)
    client = make_client_for_root(root)

    payload = {
        "name": "demo",
        "fps": 60,
        "motion_json": [{"time": 0, "poseData": [float(i) for i in range(36)]}],
    }
    create1 = client.post("/api/motions", json=payload)
    assert create1.status_code == 200

    overwrite_payload = {
        "name": "demo",
        "fps": 60,
        "overwrite": True,
        "motion_json": [
            {"time": 0, "poseData": [1.0] * 36},
            {"time": 1, "poseData": [2.0] * 36},
        ],
    }
    overwrite = client.post("/api/motions", json=overwrite_payload)
    assert overwrite.status_code == 200
    assert overwrite.json()["data"]["frames"] == 2


def test_update_motion_replaces_existing_payload(tmp_path: Path):
    root = tmp_path
    (root / "assets/csv").mkdir(parents=True, exist_ok=True)
    (root / "assets/json").mkdir(parents=True, exist_ok=True)
    client = make_client_for_root(root)

    created = client.post(
        "/api/motions",
        json={
            "name": "demo",
            "motion_json": [{"time": 0, "poseData": [0.0] * 36}],
            "fps": 60,
        },
    )
    assert created.status_code == 200

    updated = client.put(
        "/api/motions/demo",
        json={
            "motion_json": [
                {"time": 0, "poseData": [float(i) for i in range(36)]},
                {"time": 1, "poseData": [float(i + 1) for i in range(36)]},
            ],
            "fps": 30,
        },
    )

    assert updated.status_code == 200
    data = updated.json()
    assert data["data"]["motion"] == "demo"
    assert data["data"]["frames"] == 2
    assert data["data"]["duration_seconds"] == pytest.approx(2 / 30)

    detail = client.get("/api/motions/demo").json()
    assert detail["data"]["duration_seconds"] == pytest.approx(2 / 30)


def test_update_motion_rejects_missing_motion(tmp_path: Path):
    root = tmp_path
    (root / "assets/csv").mkdir(parents=True, exist_ok=True)
    (root / "assets/json").mkdir(parents=True, exist_ok=True)
    client = make_client_for_root(root)

    response = client.put(
        "/api/motions/not_exists",
        json={"motion_json": [{"time": 0, "poseData": [0.0] * 36}]},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "motion_not_found"


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
    assert body["data"]["csv_path"] == "assets/csv/wave.csv"
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


def test_replay_with_motion_json_uses_json_replay_and_emits_debug_paths(monkeypatch):
    async def fake_json_replay(
        repo_root: Path,
        json_payload: str,
        fps: float,
        net: str,
    ) -> dict[str, int | str]:
        assert repo_root == REPO_ROOT
        assert "poseData" in json_payload
        assert fps == 60
        assert net == "eno0"
        return {"returncode": 0, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr("api.main._run_json_replay", fake_json_replay)

    response = make_client().post(
        "/api/replay",
        json={
            "motion_json": [
                {"time": 0, "poseData": [float(i) for i in range(36)]},
                {"time": 1, "poseData": [float(i + 1) for i in range(36)]},
            ],
            "dry_run": False,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["source_type"] == "motion_json"
    assert body["data"]["replay"]["stdout"] == "ok"
    assert "debug_json_path" in body["data"]
    assert body["data"]["debug_json_path"].endswith(".json")
    assert body["data"]["debug_csv_path"].endswith(".csv")


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


def test_api_key_auth_controls_mutating_endpoints(monkeypatch):
    monkeypatch.setenv("MOTION_API_KEY", "test-secret")

    client = make_client()

    unauthorized = client.post(
        "/api/motions",
        json={
            "name": "x",
            "motion_json": [{"time": 0, "poseData": [0.0] * 36}],
        },
    )
    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["code"] == "unauthorized"

    authorized = client.post(
        "/api/motions",
        json={
            "name": "x",
            "motion_json": [{"time": 0, "poseData": [0.0] * 36}],
            "overwrite": True,
        },
        headers={"X-API-Key": "test-secret"},
    )
    assert authorized.status_code == 200

    unauthorized_validate = client.post(
        "/api/replay/validate",
        json={"motion": "wave", "dry_run": True},
    )
    assert unauthorized_validate.status_code == 401

    authorized_validate = client.post(
        "/api/replay/validate",
        json={"motion": "wave", "dry_run": True},
        headers={"X-API-Key": "test-secret"},
    )
    assert authorized_validate.status_code == 200

    unauthorized_update = client.put(
        "/api/motions/wave",
        json={"motion_json": [{"time": 0, "poseData": [0.0] * 36}]},
    )
    assert unauthorized_update.status_code == 401

    authorized_update = client.put(
        "/api/motions/wave",
        json={"motion_json": [{"time": 0, "poseData": [0.0] * 36}]},
        headers={"X-API-Key": "test-secret"},
    )
    assert authorized_update.status_code == 200
