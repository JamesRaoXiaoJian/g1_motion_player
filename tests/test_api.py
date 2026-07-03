from pathlib import Path
import shutil

from fastapi.testclient import TestClient

from api.main import create_app


REPO_ROOT = Path(__file__).resolve().parents[1]


def make_client_for_root(root: Path) -> TestClient:
    return TestClient(create_app(repo_root=root))


def _copy_sample_assets(root: Path) -> None:
    assets = root / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO_ROOT / "assets" / "wave.csv", assets / "wave.csv")


def _sample_csv_text() -> str:
    return (REPO_ROOT / "assets" / "wave.csv").read_text(encoding="utf-8")


def test_replay_accepts_json_body_csv_data_and_saves_upload(tmp_path: Path):
    _copy_sample_assets(tmp_path)
    client = make_client_for_root(tmp_path)

    response = client.post(
        "/api/replay",
        json={
            "csv_data": _sample_csv_text(),
            "save_as": "json_upload",
            "fps": 60,
            "net": "eth0",
            "dry_run": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["error"] is None
    assert body["data"]["source_type"] == "uploaded_csv"
    assert body["data"]["csv_path"] == "assets/uploads/json_upload.csv"
    assert body["data"]["fps"] == 60
    assert body["data"]["duration_seconds"] == 10.0
    assert body["data"]["net"] == "eth0"
    assert body["data"]["dry_run"] is True
    assert body["data"]["frames"] == 600
    assert body["data"]["controlled_joint_count"] == 17
    assert (tmp_path / "assets" / "uploads" / "json_upload.csv").exists()


def test_replay_accepts_multipart_csv_upload(tmp_path: Path):
    _copy_sample_assets(tmp_path)
    client = make_client_for_root(tmp_path)

    with (REPO_ROOT / "assets" / "wave.csv").open("rb") as handle:
        response = client.post(
            "/api/replay",
            files={"file": ("wave.csv", handle, "text/csv")},
            data={"save_as": "multipart_upload", "net": "eno0", "dry_run": "true"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["csv_path"] == "assets/uploads/multipart_upload.csv"
    assert body["data"]["fps"] == 50
    assert body["data"]["duration_seconds"] == 12.0
    assert body["data"]["frames"] == 600
    assert (tmp_path / "assets" / "uploads" / "multipart_upload.csv").exists()


def test_replay_dry_run_false_calls_csv_replay(monkeypatch, tmp_path: Path):
    _copy_sample_assets(tmp_path)
    client = make_client_for_root(tmp_path)

    async def fake_run_csv_replay(
        repo_root: Path,
        csv_path: str,
        fps: float,
        net: str,
    ) -> dict[str, int | str]:
        assert repo_root == tmp_path.resolve()
        assert csv_path == "assets/uploads/run_upload.csv"
        assert fps == 50
        assert net == "eno0"
        return {"returncode": 0, "stdout": "started", "stderr": ""}

    monkeypatch.setattr("api.main._run_csv_replay", fake_run_csv_replay)

    response = client.post(
        "/api/replay",
        json={
            "csv_data": _sample_csv_text(),
            "save_as": "run_upload",
            "net": "eno0",
            "dry_run": False,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["replay"]["stdout"] == "started"


def test_replay_rejects_missing_csv_payload(tmp_path: Path):
    _copy_sample_assets(tmp_path)
    client = make_client_for_root(tmp_path)

    response = client.post("/api/replay", json={"dry_run": True})

    assert response.status_code == 400
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "invalid_request"


def test_replay_rejects_invalid_csv(tmp_path: Path):
    _copy_sample_assets(tmp_path)
    client = make_client_for_root(tmp_path)

    response = client.post(
        "/api/replay",
        json={
            "csv_data": "1,2,3\n",
            "save_as": "bad_upload",
            "dry_run": True,
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "invalid_csv"
    assert not (tmp_path / "assets" / "uploads" / "bad_upload.csv").exists()


def test_replay_rejects_path_like_save_as(tmp_path: Path):
    _copy_sample_assets(tmp_path)
    client = make_client_for_root(tmp_path)

    response = client.post(
        "/api/replay",
        json={
            "csv_data": _sample_csv_text(),
            "save_as": "../bad",
            "dry_run": True,
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_old_motion_endpoints_are_not_registered(tmp_path: Path):
    _copy_sample_assets(tmp_path)
    client = make_client_for_root(tmp_path)

    assert {route.path for route in client.app.routes} == {"/api/replay"}
    assert client.get("/api/motions").status_code == 404
    assert client.post("/api/replay/validate", json={}).status_code == 404
    assert client.post("/api/motions", json={}).status_code == 404
