"""Automation uses generated files, isolated SQLite and an in-memory provider."""
import json
import re
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import OpenAI

from app.config import settings, ensure_directories
from app.database import init_db, get_connection
from app.main import app
from app.services import automation, translator
from app.services.subtitle_io import read_srt

ENGLISH = "7\n00:00:02,125 --> 00:00:03,250\nHello, café!\n\n12\n00:00:04,375 --> 00:00:05,500\nHow are you?\n"


@pytest.fixture
def library(monkeypatch, tmp_path):
    root = tmp_path / "fixtures"
    root.mkdir()
    monkeypatch.setattr(settings, "auth_enabled", False)
    monkeypatch.setattr(settings, "dev_mode", True)
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(automation.worker, "start", lambda: None)
    monkeypatch.setattr(automation.worker, "stop", lambda: None)
    monkeypatch.setattr(automation, "list_text_subtitle_streams", lambda path: [])
    ensure_directories()
    init_db()
    automation.init_schema()
    automation.save_config(True, [str(root)], {"/tv": str(root), "/movies": str(root)})
    return root


@pytest.fixture
def api(library):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def provider(monkeypatch):
    prompts = []

    def request(req):
        prompt = json.loads(req.content)["messages"][-1]["content"]
        prompts.append(prompt)
        blocks = re.findall(r"BEGIN\[(\d+)\]\n(.*?)\nEND\[\1\]", prompt, re.DOTALL)
        assert blocks
        content = "\n\n".join(f"BEGIN[{index}]\nسلام دنیا\nEND[{index}]" for index, _ in blocks)
        return httpx.Response(200, json={"id": "fixture", "object": "chat.completion", "created": 0,
            "model": "fixture", "choices": [{"index": 0, "message": {"role": "assistant",
                "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}})

    monkeypatch.setattr(settings, "openai_api_key", "sk-fixture-only")
    monkeypatch.setattr(translator, "get_openai_client", lambda: OpenAI(api_key="sk-fixture-only",
        base_url="http://fixture.invalid/v1", max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(request))))
    return prompts


def media(root, name="Episode"):
    video = root / (name + ".mkv")
    video.write_bytes(b"fixture video; ffprobe is mocked")
    return video


def headers():
    return {"X-Automation-Key": automation.config()["webhook_token"]}


def due(item):
    with get_connection() as conn:
        conn.execute("UPDATE automation_queue SET next_run=0 WHERE id=?", (item["id"],))


def queued(item):
    return next(row for row in automation.list_queue() if row["id"] == item["id"])


def test_delayed_bazarr_end_to_end_duplicates_and_context(api, library, provider):
    video = media(library)
    event = {"eventType": "Download", "episodeFile": {"path": "/tv/Episode.mkv"}}
    first = api.post("/automation/hooks/sonarr", json=event, headers=headers())
    assert first.status_code == 200
    assert api.post("/automation/hooks/sonarr", json=event, headers=headers()).json() == first.json()
    assert len(automation.list_queue()) == 1
    assert automation.process_one()
    item = automation.list_queue()[0]
    assert item["status"] == "waiting_source" and item["attempts"] == 0
    assert not provider
    video.with_suffix(".en.srt").write_text(ENGLISH)
    response = api.post("/automation/hooks/bazarr", json={
        "eventType": "SubtitleDownloaded", "video_path": "/tv/Episode.mkv", "language": "eng"
    }, headers=headers())
    assert response.status_code == 200
    assert response.json()["queue_ids"] == first.json()["queue_ids"]
    assert automation.process_one()
    assert automation.list_queue()[0]["status"] == "done"
    output = video.with_suffix(".fa.srt")
    cues = read_srt(output)
    assert [(cue.index, cue.start.ordinal, cue.end.ordinal) for cue in cues] == [(7,2125,3250),(12,4375,5500)]
    assert all("سلام دنیا" in cue.text for cue in cues)
    assert "REFERENCE CONTEXT" in provider[0]
    assert "Iranian Persian" in provider[0]
    assert json.loads(provider[0].split("REFERENCE CONTEXT")[1].split("\n",2)[1])[0]["after"] == ["How are you?"]
    saved = output.read_bytes()
    automation.reconcile()
    api.post("/automation/hooks/sonarr", json=event, headers=headers())
    assert not automation.process_one()
    assert len(provider) == 1 and output.read_bytes() == saved


def test_embedded_source_avoids_forced_commentary_and_foreign(library, provider, monkeypatch):
    video = media(library)
    streams = [
        {"index":1,"language":"eng","forced":True,"comment":False,"default":True},
        {"index":2,"language":"fra","forced":False,"comment":False,"default":True},
        {"index":3,"language":"eng","forced":False,"comment":True,"default":True},
        {"index":4,"language":"eng","forced":False,"comment":False,"default":False},
    ]
    monkeypatch.setattr(automation, "list_text_subtitle_streams", lambda path: streams)
    extracted = []
    def extract(path, output, stream_index):
        extracted.append(stream_index)
        output.write_text(ENGLISH)
    monkeypatch.setattr(automation, "extract_subtitle", extract)
    automation.enqueue(str(video))
    automation.process_one()
    assert extracted == [4]
    assert automation.list_queue()[0]["status"] == "done"
    assert len(provider) == 1


def test_sidecar_preference_and_foreign_only_wait(library, monkeypatch):
    video = media(library)
    video.with_suffix(".en.sdh.srt").write_text(ENGLISH)
    video.with_suffix(".en.srt").write_text(ENGLISH)
    assert automation.select_source(video, "item") == video.with_suffix(".en.srt")
    video.with_suffix(".en.srt").unlink()
    assert automation.select_source(video, "item") == video.with_suffix(".en.sdh.srt")
    video.with_suffix(".en.sdh.srt").unlink()
    video.with_suffix(".fr.srt").write_text(ENGLISH)
    item = automation.enqueue(str(video))
    automation.process_one()
    assert queued(item)["status"] == "waiting_source"
    assert queued(item)["attempts"] == 0


def test_missing_media_and_provider_remain_pending(api, library):
    item = automation.enqueue(str(library / "Late.mkv"))
    automation.process_one()
    assert queued(item)["status"] == "waiting_media"
    video = media(library, "Late")
    video.with_suffix(".en.srt").write_text(ENGLISH)
    automation.enqueue(str(video), "bazarr")
    automation.process_one()
    assert queued(item)["status"] == "waiting_config"
    assert queued(item)["attempts"] == 0


def test_retry_backoff_exhaustion_and_manual_retry(library, monkeypatch):
    item = automation.enqueue(str(media(library)))
    def fail(item):
        raise RuntimeError("Temporary provider failure")
    monkeypatch.setattr(automation, "process", fail)
    for attempt in range(1,6):
        assert automation.process_one()
        current = queued(item)
        assert current["attempts"] == attempt
        assert current["status"] == ("failed" if attempt == 5 else "retry")
        assert current["next_run"] > 0
        if attempt != 5:
            assert not automation.process_one()
            due(item)
    automation.retry(item["id"])
    assert queued(item)["status"] == "queued" and queued(item)["attempts"] == 0


def test_concurrent_duplicate_events_and_exclusive_leases(library):
    video = media(library)
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(lambda _: automation.enqueue(str(video))["id"], range(12)))
    assert len(set(ids)) == 1
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda _: automation.claim(), range(8)))
    assert sum(item is not None for item in claims) == 1
    running = next(item for item in claims if item)
    assert automation.claim() is None
    with get_connection() as conn:
        conn.execute("UPDATE automation_queue SET lease_until=0 WHERE id=?", (running["id"],))
    # Re-initializing schema simulates a new process opening the same database.
    automation.init_schema()
    recovered = automation.claim()
    assert recovered["id"] == running["id"] and recovered["owner"] != running["owner"]
    automation.finish(running, "done", "stale worker")
    assert queued(running)["status"] == "running"


def test_paused_queue_and_reconciliation(library):
    video = media(library)
    assert automation.reconcile() == 1
    automation.save_config(False, [str(library)], {})
    assert not automation.process_one()
    assert automation.list_queue()[0]["video_path"] == str(video)


def test_hook_auth_tests_ignored_events_and_path_boundaries(api, library, tmp_path):
    assert api.post("/automation/hooks/sonarr", json={"eventType":"Test"}).status_code == 401
    assert api.post("/automation/hooks/sonarr", json={"eventType":"Test"}, headers=headers()).json()["test"]
    assert api.post("/automation/hooks/sonarr", json={"eventType":"Grab"}, headers=headers()).json()["status"] == "ignored"
    assert api.post("/automation/hooks/bazarr", json={"eventType":"SubtitleDownloaded","language":"fa"},
                    headers=headers()).json()["status"] == "ignored"
    for path in ["/outside/Film.mkv", "/tv/../../outside/Film.mkv", "relative.mkv"]:
        assert api.post("/automation/hooks/sonarr", json={"eventType":"Download",
            "episodeFile":{"path":path}}, headers=headers()).status_code == 422
    (library / "escape").symlink_to(tmp_path)
    with pytest.raises(ValueError):
        automation.enqueue(str(library / "escape" / "Outside.mkv"))
    assert not automation.list_queue()


def test_radarr_basic_auth_and_invalid_payloads(api, library):
    import base64
    credential = base64.b64encode(("automation:" + automation.config()["webhook_token"]).encode()).decode()
    response = api.post("/automation/hooks/radarr", json={"eventType":"Download",
        "movieFile":{"path":"/movies/Film.mkv"}}, headers={"Authorization":"Basic "+credential})
    assert response.status_code == 200
    assert automation.list_queue()[0]["status"] == "queued"
    assert api.post("/automation/hooks/radarr", json=[], headers=headers()).status_code == 422
    assert api.post("/automation/hooks/radarr", content=b"x"*65537, headers=headers()).status_code == 413
    assert api.post("/automation/settings", data={"enabled":"true","roots":str(library),
        "path_mappings":"{}"}, headers={"Origin":"https://other.invalid"}).status_code == 403


def test_development_rejects_real_libraries(library, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "media_root", library.parent)
    real = library.parent / "movies"
    real.mkdir()
    with pytest.raises(ValueError, match="fixtures"):
        automation.save_config(True, [str(real)], {})


def test_existing_output_not_overwritten(library, provider):
    video = media(library)
    output = video.with_suffix(".fa.srt")
    output.write_text(ENGLISH.replace("Hello, café!", "سلام").replace("How are you?", "چطوری؟"))
    saved = output.read_bytes()
    item = automation.enqueue(str(video))
    automation.process_one()
    assert queued(item)["status"] == "skipped"
    assert output.read_bytes() == saved and not provider
    with pytest.raises(ValueError):
        automation.retry(item["id"])


def test_automation_ui_status_and_session_auth(api, library, monkeypatch):
    assert api.get("/automation").status_code == 200
    status = api.get("/automation/status").json()
    assert "webhook_token" not in status and status["enabled"]
    monkeypatch.setattr(settings, "auth_enabled", True)
    assert api.get("/automation/status").status_code == 401
    assert api.post("/automation/scan").status_code == 401

def test_failed_provider_alignment_retries_without_partial_output(library, provider, monkeypatch):
    video = media(library)
    video.with_suffix(".en.srt").write_text(ENGLISH)
    item = automation.enqueue(str(video))
    original = translator.call_openai
    bad = translator.TranslationResult({99:"سلام"},0,0,0,"",[99],[],0)
    monkeypatch.setattr(translator, "call_openai", lambda prompt: bad)
    automation.process_one()
    assert queued(item)["status"] == "retry"
    assert not video.with_suffix(".fa.srt").exists()
    monkeypatch.setattr(translator, "call_openai", original)
    due(item)
    automation.process_one()
    assert queued(item)["status"] == "done"
    assert [cue.index for cue in read_srt(video.with_suffix(".fa.srt"))] == [7,12]


def test_relay_uses_service_environment_and_bazarr_language(monkeypatch):
    from scripts.automation_event import build_event
    monkeypatch.setenv("sonarr_eventtype", "Download")
    monkeypatch.setenv("sonarr_episodefile_path", "/tv/My Episode.mkv")
    assert build_event("sonarr")["episodeFile"]["path"] == "/tv/My Episode.mkv"
    assert build_event("bazarr", "/movies/My Film.mkv", "en:hi")["language"] == "en"

def test_multifile_import_validation_is_all_or_nothing(api, library):
    response = api.post("/automation/hooks/sonarr", json={"eventType":"Rename","episodeFiles":[
        {"path":"/tv/Valid.mkv"},{"path":"/outside/Invalid.mkv"}]}, headers=headers())
    assert response.status_code == 422 and not automation.list_queue()
    response = api.post("/automation/hooks/sonarr", json={"eventType":"Rename","episodeFiles":[
        {"path":"/tv/A.mkv"},{"path":"/tv/B.mkv"}]}, headers=headers())
    assert response.status_code == 200 and len(automation.list_queue()) == 2


def test_embedded_metadata_identifies_hearing_impaired_and_commentary(monkeypatch, tmp_path):
    from app.services import ffmpeg_service
    monkeypatch.setattr(ffmpeg_service, "get_media_info", lambda *a, **kw: {"streams":[
        {"index":1,"codec_type":"subtitle","codec_name":"subrip","tags":{"language":"eng","title":"English SDH"}},
        {"index":2,"codec_type":"subtitle","codec_name":"subrip","tags":{"language":"eng","title":"Director Commentary"}}]})
    streams = ffmpeg_service.list_text_subtitle_streams(tmp_path / "film.mkv")
    assert streams[0]["hearing_impaired"]
    assert streams[1]["comment"]


def test_explicit_library_write_opt_in(library, monkeypatch):
    monkeypatch.setattr(settings, "media_root", library.parent)
    monkeypatch.setattr(settings, "automation_allow_library_writes", True)
    real = library.parent / "movies"
    real.mkdir()
    cfg = automation.save_config(False, [str(real)], {"/movies":str(real)})
    assert not cfg["enabled"]
    assert automation.map_path("/movies/Film.mkv") == real / "Film.mkv"


def test_selected_file_scope_does_not_claim_other_pending_imports(library):
    first = media(library, "First")
    selected = media(library, "Selected")
    other = automation.enqueue(str(first))
    chosen = automation.enqueue(str(selected))
    automation.save_scope([str(selected)])
    assert automation.reconcile() == 1
    assert automation.claim()["id"] == chosen["id"]
    assert queued(other)["status"] == "queued"
    automation.save_scope([])
    assert automation.claim() is None


def test_real_processing_gate_is_independent_of_write_permission(library, monkeypatch):
    monkeypatch.setattr(settings, "media_root", library.parent)
    monkeypatch.setattr(settings, "automation_allow_library_writes", True)
    monkeypatch.setattr(settings, "automation_real_library_processing", False)
    real = library.parent / "movies"
    real.mkdir()
    video = media(real)
    automation.save_config(True, [str(real)], {})
    assert not automation.permitted_file(video)
    with pytest.raises(ValueError, match="disabled"):
        automation.enqueue(str(video))
    monkeypatch.setattr(settings, "automation_real_library_processing", True)
    assert automation.permitted_file(video)


def test_pause_prevents_publication_of_inflight_response(library, provider, monkeypatch):
    video = media(library)
    video.with_suffix(".en.srt").write_text(ENGLISH)
    item = automation.enqueue(str(video))
    original = translator.call_openai
    def pause_during_reply(prompt):
        result = original(prompt)
        automation.pause()
        return result
    monkeypatch.setattr(translator, "call_openai", pause_during_reply)
    automation.process_one()
    assert not automation.config()["enabled"]
    assert not video.with_suffix(".fa.srt").exists()
    assert queued(item)["status"] != "done"


def test_context_stops_at_scene_gaps():
    import pysrt
    from app.services.subtitle_io import batch_subtitles
    cues = pysrt.SubRipFile([
        pysrt.SubRipItem(7,start=pysrt.SubRipTime(seconds=1),end=pysrt.SubRipTime(seconds=2),text="Old scene"),
        pysrt.SubRipItem(12,start=pysrt.SubRipTime(seconds=90),end=pysrt.SubRipTime(seconds=91),text="New scene"),
        pysrt.SubRipItem(20,start=pysrt.SubRipTime(seconds=92),end=pysrt.SubRipTime(seconds=93),text="Same scene")])
    batch = list(batch_subtitles(cues,10,12000,context_cues=2))[0]
    assert batch[1]["context_before"] == []
    assert batch[1]["context_after"] == ["Same scene"]
    assert batch[2]["context_before"] == ["New scene"]


def test_scope_limit_and_pause_http(api, library):
    assert api.post("/automation/scope", data={"allowed_files":""}).status_code == 200
    assert automation.claim() is None
    assert api.post("/automation/pause").json()["paused"]
    assert not automation.config()["enabled"]
    with pytest.raises(ValueError, match="50"):
        automation.save_scope([str(library/"film.mkv")]*51)


def test_blocked_real_file_cannot_starve_allowed_fixture(library, monkeypatch):
    monkeypatch.setattr(settings, "media_root", library.parent)
    monkeypatch.setattr(settings, "automation_allow_library_writes", True)
    monkeypatch.setattr(settings, "automation_real_library_processing", True)
    real = library.parent/"movies"
    real.mkdir()
    actual = media(real,"Real")
    fixture = media(library,"Fixture")
    automation.save_config(True,[str(real),str(library)],{})
    real_item = automation.enqueue(str(actual))
    selected = automation.enqueue(str(fixture))
    automation.save_scope([str(actual),str(fixture)])
    monkeypatch.setattr(settings,"automation_real_library_processing",False)
    assert automation.claim()["id"] == selected["id"]
    assert queued(real_item)["status"] == "queued"


def test_persian_sidecar_variant_prevents_duplicate_translation(library, provider):
    video = media(library)
    existing = video.with_suffix(".fa.sdh.srt")
    existing.write_text(ENGLISH.replace("Hello, café!","سلام").replace("How are you?","چطوری؟"))
    saved = existing.read_bytes()
    item = automation.enqueue(str(video))
    automation.process_one()
    assert queued(item)["status"] == "skipped"
    assert existing.read_bytes() == saved
    assert not video.with_suffix(".fa.srt").exists() and not provider


def test_embedded_persian_prevents_duplicate_translation(library, provider, monkeypatch):
    video = media(library)
    video.with_suffix(".en.srt").write_text(ENGLISH)
    monkeypatch.setattr(automation,"list_text_subtitle_streams",lambda path:[
        {"index":1,"language":"fas","forced":False,"comment":False,"default":True}])
    item = automation.enqueue(str(video))
    automation.process_one()
    assert queued(item)["status"] == "skipped"
    assert not video.with_suffix(".fa.srt").exists() and not provider
