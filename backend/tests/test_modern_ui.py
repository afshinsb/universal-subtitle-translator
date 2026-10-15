import time

from app.config import settings
from app.database import get_connection
from app.services import automation, media_intake, download_guard, ui_state


def test_interfaces_share_state_and_preference_persists(client):
    for path in (
        "/ui",
        "/ui/guard",
        "/ui/queue",
        "/ui/downloads",
        "/ui/translate",
        "/ui/batches",
        "/ui/history",
        "/ui/outputs",
        "/ui/settings",
        "/ui/logs",
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert (
            "/static/modern.css" in response.text
            and "/static/theme.css" not in response.text
        )
    assert "/static/theme.css" in client.get("/automation").text
    response = client.post(
        "/ui/interface",
        data={"mode": "modern", "target": "/ui/queue"},
        follow_redirects=False,
    )
    assert response.status_code == 303 and response.headers["location"] == "/ui/queue"
    assert "Max-Age=31536000" in response.headers["set-cookie"]
    assert (
        client.get(
            "/", headers={"accept": "text/html"}, follow_redirects=False
        ).headers["location"]
        == "/ui"
    )
    client.post("/ui/interface", data={"mode": "legacy", "target": "/"})
    assert (
        client.get(
            "/", headers={"accept": "text/html"}, follow_redirects=False
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/ui/interface", data={"mode": "modern", "target": "//evil.test"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/ui/interface",
            data={"mode": "legacy"},
            headers={"origin": "https://evil.test"},
        ).status_code
        == 403
    )


def test_guard_requires_explicit_removal_confirmation_and_scan_is_readonly(
    client, monkeypatch
):
    with get_connection() as c:
        c.execute(
            "UPDATE download_guard_config SET last_scan='completed dry run',last_successful_scan='completed dry run'"
        )
    assert (
        client.post(
            "/automation/download-guard/settings",
            data={"enabled": "true", "auto_remove": "true"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/automation/download-guard/settings",
            data={"enabled": "true", "auto_remove": "true", "confirm_remove": "true"},
        ).status_code
        == 200
    )
    assert download_guard.snapshot()["auto_remove"] == 1
    called = []
    monkeypatch.setattr(media_intake, "services", lambda: {"qbit": {}})
    monkeypatch.setattr(
        download_guard.worker, "request_scan", lambda: called.append("dry")
    )
    result = client.post("/automation/download-guard/scan")
    assert result.status_code == 202 and result.json()["dry_run"] and called == ["dry"]
    assert (
        client.post(
            "/automation/download-guard/scan", headers={"origin": "https://evil.test"}
        ).status_code
        == 403
    )
    assert called == ["dry"]
    client.post(
        "/automation/download-guard/settings",
        data={"enabled": "false", "auto_remove": "false"},
    )
    assert (
        download_guard.snapshot()["enabled"] == 0
        and download_guard.snapshot()["auto_remove"] == 0
    )


def test_no_credentials_in_default_ui_or_read_models(client, monkeypatch, tmp_path):
    key = "sk-ui-private-provider-key"
    monkeypatch.setattr(settings, "openai_api_key", key)
    cfg = automation.config()
    token = cfg["webhook_token"]
    with get_connection() as c:
        c.execute(
            "INSERT INTO automation_queue(id,video_path,origin,status,message,created_at,updated_at) VALUES('q',?,'sonarr','failed',?,?,?)",
            (
                str(tmp_path / "video.mkv"),
                key + " " + token,
                "2026-01-01",
                "2026-01-01",
            ),
        )
    for path in (
        "/ui",
        "/ui/api/status",
        "/ui/api/queue",
        "/automation",
        "/automation/status",
    ):
        response = client.get(path)
        assert key not in response.text and token not in response.text
    assert (
        client.post(
            "/automation/integration-token", headers={"origin": "http://testserver"}
        ).json()["token"]
        == token
    )
    assert (
        client.post(
            "/automation/integration-token", headers={"origin": "http://evil"}
        ).status_code
        == 403
    )
    payload = client.get("/ui/api/queue").json()["items"][0]
    assert (
        "owner" not in payload
        and "lease_until" not in payload
        and "signature" not in payload
    )


def test_modern_requires_same_authentication(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "admin_password", "strong-test-password")
    assert client.get("/ui/api/status").status_code == 401
    assert (
        client.get(
            "/ui", headers={"accept": "text/html"}, follow_redirects=False
        ).status_code
        == 303
    )
    assert client.post("/automation/download-guard/scan").status_code == 401


def test_100_file_intake_burst_persists_before_work_and_paginates(
    client, monkeypatch, tmp_path
):
    automation.worker.stop()
    media_intake.worker.stop()
    root = tmp_path / "library"
    root.mkdir()
    monkeypatch.setattr(settings, "media_intake_enabled", True)
    automation.save_config(False, [str(root)], {}, "events_only")
    automation.save_scope([], "libraries")
    files = [
        {"path": str(root / f"Show.S01E{i:03}.mkv"), "id": i + 1} for i in range(100)
    ]
    payload = {
        "eventType": "Download",
        "series": {"id": 1, "title": "Fixture show"},
        "episodeFiles": files,
    }
    headers = {"X-Automation-Key": automation.config()["webhook_token"]}
    start = time.monotonic()
    first = client.post("/automation/hooks/sonarr", json=payload, headers=headers)
    second = client.post("/automation/hooks/sonarr", json=payload, headers=headers)
    assert first.json()["intake_ids"] == second.json()["intake_ids"]
    assert len(first.json()["intake_ids"]) == 100 and time.monotonic() - start < 10
    assert automation.counts() == {}
    media_intake.init_schema()
    result = client.get("/ui/api/downloads?state=validation_pending&page=4").json()
    assert (
        result["total"] == 100 and result["pages"] == 4 and len(result["items"]) == 25
    )
    assert all(
        x["state"] == "validation_pending" and not x["eligible"]
        for x in result["items"]
    )
    with get_connection() as c:
        assert c.execute("SELECT COUNT(*) FROM media_events").fetchone()[0] == 100
    assert client.get("/ui/api/queue").json()["total"] == 0


def test_queue_pagination_order_search_and_thousands_remain_bounded(client, tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    automation.save_config(False, [str(root)], {}, "events_only")
    with get_connection() as c:
        for i in range(2000):
            c.execute(
                "INSERT INTO automation_queue(id,video_path,origin,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (
                    f"q{i:05}",
                    str(root / f"Show.S01E{i:04}.mkv"),
                    "sonarr",
                    "queued",
                    "2026-10-15",
                    "2026-10-15",
                ),
            )
    data = client.get("/ui/api/queue?page=2&size=25").json()
    assert data["total"] == 2000 and data["pages"] == 80 and len(data["items"]) == 25
    assert [x["id"] for x in data["items"]] == [f"q{i:05}" for i in range(25, 50)]
    assert [x["queue_position"] for x in data["items"]] == list(range(26, 51))
    assert client.get("/ui/api/queue?size=999").json()["size"] == 50
    assert client.get("/ui/api/queue?search=E0100").json()["total"] == 1
    assert client.get("/ui/api/queue?state=not-a-state").status_code == 422
    assert client.get("/ui/api/queue?search=%25").json()["total"] == 0


def test_intake_extraction_phase_is_real_and_download_failure_is_not_work(
    client, tmp_path
):
    with get_connection() as c:
        c.execute(
            "INSERT INTO media_intake(id,video_path,title,state,phase,owner,lease_until,imported_at) VALUES('i',?,'Show','waiting_stable','extracting','worker',?,'2026-10-15')",
            (str(tmp_path / "video.mkv"), time.time() + 100),
        )
        c.execute(
            "INSERT INTO upstream_activity(identity,service,title,state,updated_at) VALUES('bad','sonarr','Fake download','import_rejected','2026-10-15')"
        )
    rows = ui_state.pagination("downloads", state="all")["items"]
    assert {x["state"] for x in rows} == {"extracting", "import_rejected"}
    assert all(not x["eligible"] for x in rows)
    assert automation.counts() == {}


def test_hidden_and_visible_controls_use_existing_backend(client, tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    automation.save_config(False, [str(root)], {}, "events_only")
    job = automation.enqueue(str(root / "Test.mkv"), "sonarr")
    assert client.post("/automation/queue/" + job["id"] + "/cancel").status_code == 200
    assert (
        client.get("/ui/api/queue?state=cancelled").json()["items"][0]["status"]
        == "cancelled"
    )
    assert client.post("/automation/queue/" + job["id"] + "/retry").status_code == 200
    assert client.get("/ui/api/queue").json()["items"][0]["status"] == "queued"


def test_modern_login_uses_shared_account_without_private_state(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "admin_password", "test-login-only-password")
    page = client.get("/login?next=/ui")
    assert "/static/modern.css" in page.text and "initial-state" not in page.text
    assert automation.config()["webhook_token"] not in page.text
    wrong = client.post(
        "/login",
        data={"username": settings.admin_username, "password": "wrong", "next": "/ui"},
    )
    assert wrong.status_code == 401 and "/static/modern.css" in wrong.text
    result = client.post(
        "/login",
        data={
            "username": settings.admin_username,
            "password": "test-login-only-password",
            "next": "/ui",
        },
        follow_redirects=False,
    )
    assert result.status_code == 303 and result.headers["location"] == "/ui"
    assert client.get("/ui/api/status").status_code == 200
    assert (
        "/static/theme.css" in client.get("/login?interface=legacy").text
        or client.get("/login?interface=legacy", follow_redirects=False).status_code
        == 303
    )


def test_live_translation_progress_is_bounded_and_counts_completed_batches(client, tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    automation.save_config(False, [str(root)], {}, "events_only")
    with get_connection() as c:
        for i in range(8):
            c.execute(
                "INSERT INTO jobs(id,input_file,input_path,target_language,status,model,total_subtitles,translated_count,progress_percent,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (f"live{i}", f"Episode{i}.mkv", str(root / f"Episode{i}.mkv"), "Persian", "running", "test-model", 1000, 400, 40, "2026-10-15", "2026-10-15"),
            )
            c.execute(
                "INSERT INTO automation_queue(id,video_path,origin,status,job_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (f"q{i}", str(root / f"Episode{i}.mkv"), "sonarr", "running", f"live{i}", "2026-10-15", "2026-10-15"),
            )
        # Parallel batches may finish out of order and alignment can be logged twice.
        for batch in (3, 1, 3):
            c.execute(
                "INSERT INTO logs(job_id,level,event,message,batch_number,batch_count,created_at) VALUES('live0','INFO','batch_alignment_validated','Aligned',?,25,'2026-10-15')",
                (batch,),
            )
    response = client.get("/ui/api/status")
    assert response.status_code == 200
    live = response.json()["active_media"]
    assert len(live) == 6
    first = next(x for x in live if x["id"] == "q0")
    assert first["progress"] == 40 and first["translated_count"] == 400
    assert first["total_subtitles"] == 1000
    assert first["batches_completed"] == 2 and first["batch_count"] == 25
    assert first["eta_seconds"] is None  # No measured provider latency yet.
    with get_connection() as c:
        c.execute("UPDATE jobs SET translated_count=520,progress_percent=52 WHERE id='live0'")
    refreshed = client.get("/ui/api/queue?state=running").json()["items"][0]
    assert refreshed["progress"] == 52
    assert "owner" not in refreshed and "lease_until" not in refreshed
    html = client.get("/ui/queue").text
    assert 'id="live-translations"' in html and 'id="queue-running-count"' in html
