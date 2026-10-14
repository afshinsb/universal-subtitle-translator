from pathlib import Path

from app.config import DEFAULT_SESSION_SECRET, auth_config_checks, settings
from app.routes.files import list_uploads
from app.config import config_status


def test_config_accepts_default_model_without_raw_environment(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setattr(settings, "openai_model", "gpt-4o-mini")
    checks = {check["id"]: check for check in config_status()["checks"]}
    assert checks["openai_model"]["ok"] is True


def test_config_rejects_negative_timeouts(monkeypatch):
    monkeypatch.setattr(settings, "ffmpeg_timeout_seconds", -1)
    checks = {check["id"]: check for check in config_status()["checks"]}
    assert checks["ffmpeg_timeout_seconds"]["blocking"] is True


def test_unicode_credentials_work(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "admin_username", "افشین")
    monkeypatch.setattr(settings, "admin_password", "رمز secure password")
    response = client.post("/login", data={"username": settings.admin_username, "password": settings.admin_password}, follow_redirects=False)
    assert response.status_code == 303
    assert client.get("/config/status").status_code == 200


def test_production_rejects_cookie_forged_with_default_secret(client, monkeypatch):
    import base64
    import json
    from itsdangerous import TimestampSigner
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "dev_mode", False)
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "session_secret", DEFAULT_SESSION_SECRET)
    payload = base64.b64encode(json.dumps({"authenticated": True}).encode())
    cookie = TimestampSigner(DEFAULT_SESSION_SECRET).sign(payload).decode()
    client.cookies.set("ust_session", cookie)
    assert client.get("/config/status").status_code == 503
    assert client.get("/health").status_code == 200


def test_unauthenticated_api_is_private(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "dev_mode", True)
    assert client.get("/jobs").status_code == 401


def test_production_rejects_disabled_auth_without_dev_opt_in(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", False)
    monkeypatch.setattr(settings, "dev_mode", False)
    monkeypatch.setattr(settings, "demo_mode", False)
    assert client.get("/jobs").status_code == 503
    assert client.get("/health").status_code == 200


def test_upload_listing_includes_files_inside_job_folders(tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    upload_file = upload_dir / "job-1" / "movie.en.srt"
    upload_file.parent.mkdir(parents=True)
    upload_file.write_text("subtitle", encoding="utf-8")

    monkeypatch.setattr(settings, "upload_dir", upload_dir)

    uploads = list_uploads()["uploads"]

    assert uploads == [
        {
            "name": "movie.en.srt",
            "relative_path": str(Path("job-1") / "movie.en.srt"),
            "job_id": "job-1",
            "size": len("subtitle"),
        }
    ]


def test_auth_defaults_block_when_dev_and_demo_modes_are_disabled(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "dev_mode", False)
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "admin")
    monkeypatch.setattr(settings, "session_secret", DEFAULT_SESSION_SECRET)

    checks = {check["id"]: check for check in auth_config_checks()}

    assert checks["admin_password"]["blocking"] is True
    assert checks["session_secret"]["blocking"] is True


def test_auth_defaults_warn_but_do_not_block_in_dev_mode(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "dev_mode", True)
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "admin")
    monkeypatch.setattr(settings, "session_secret", DEFAULT_SESSION_SECRET)

    checks = {check["id"]: check for check in auth_config_checks()}

    assert checks["admin_password"]["severity"] == "warning"
    assert checks["admin_password"]["blocking"] is False
    assert checks["session_secret"]["severity"] == "warning"
    assert checks["session_secret"]["blocking"] is False
