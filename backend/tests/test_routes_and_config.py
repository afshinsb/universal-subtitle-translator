from pathlib import Path

from app.config import DEFAULT_SESSION_SECRET, auth_config_checks, settings
from app.routes.files import list_uploads


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
