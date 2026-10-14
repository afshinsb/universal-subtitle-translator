"""Run via docker exec in development: retained fixtures, HTTP events, mocked provider."""
import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx
from openai import OpenAI

from app.config import settings
from app.services import automation, translator
from app.services.subtitle_io import read_srt

parser = argparse.ArgumentParser()
parser.add_argument("phase", choices=["prepare", "complete"])
args = parser.parse_args()
assert settings.dev_mode and settings.media_root == Path("/media")
assert not settings.openai_api_key
original_config = automation.config()
assert not original_config["enabled"], "Pause automation while running this fixture demonstration."
manifest = Path("/app/data/automation-demo.json")


def event(service, payload):
    response = httpx.post("http://backend:2288/automation/hooks/" + service, json=payload,
                          headers={"X-Automation-Key": original_config["webhook_token"]}, timeout=10)
    assert response.status_code == 200, response.text
    return response.json()


def state(item_id):
    return next(item for item in automation.list_queue(10000) if item["id"] == item_id)


if args.phase == "prepare":
    root = Path("/media/fixtures") / ("automation-demo-" + uuid4().hex[:8])
    root.mkdir()
    delayed = root / "Delayed Episode.mkv"
    subprocess.run(["ffmpeg","-nostdin","-v","error","-f","lavfi","-i",
        "color=size=16x16:rate=1:duration=6","-c:v","ffv1",str(delayed)], check=True, timeout=30)
    embedded = root / "Embedded Film.mkv"
    existing = next(Path("/media/fixtures/verified-smoke/library").glob("*.mkv"))
    shutil.copyfile(existing, embedded)
    pending_id = event("sonarr", {"eventType":"Download","episodeFile":{"path":str(delayed)}})["queue_ids"][0]
    embedded_id = event("radarr", {"eventType":"Download","movieFile":{"path":str(embedded)}})["queue_ids"][0]
    with patch.object(automation, "config", lambda: {**original_config, "enabled":True}):
        automation.process_one(pending_id)
    assert state(pending_id)["status"] == "waiting_source"
    assert state(pending_id)["attempts"] == 0
    manifest.write_text(json.dumps({"root":str(root),"pending_id":pending_id,"embedded_id":embedded_id}))
    print(json.dumps({"phase":"prepared","delayed_status":"waiting_source","attempts":0,
                      "fixture_root":str(root),"paid_requests":0}))
else:
    saved = json.loads(manifest.read_text())
    root = Path(saved["root"])
    pending = state(saved["pending_id"])
    assert pending["status"] == "waiting_source", "Pending import must survive the restart."
    delayed = root / "Delayed Episode.mkv"
    delayed.with_suffix(".en.srt").write_text(
        "7\n00:00:02,125 --> 00:00:03,250\nHello, café!\n\n"
        "12\n00:00:04,375 --> 00:00:05,500\nHow are you?\n", encoding="utf-8")
    event("bazarr", {"eventType":"SubtitleDownloaded","video_path":str(delayed),"language":"en"})
    prompts = []
    def provider(request):
        prompt = json.loads(request.content)["messages"][-1]["content"]
        prompts.append(prompt)
        blocks = re.findall(r"BEGIN\[(\d+)\]\n(.*?)\nEND\[\1\]", prompt, re.DOTALL)
        assert blocks and "FORCED ONLY" not in prompt
        text = "\n\n".join(f"BEGIN[{index}]\nسلام دنیا\nEND[{index}]" for index, _ in blocks)
        return httpx.Response(200, json={"id":"fixture","object":"chat.completion","created":0,"model":"fixture",
            "choices":[{"index":0,"message":{"role":"assistant","content":text},"finish_reason":"stop"}],
            "usage":{"prompt_tokens":10,"completion_tokens":10,"total_tokens":20}})
    def client():
        return OpenAI(api_key="sk-fixture-only",base_url="http://fixture.invalid/v1",max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(provider)))
    with patch.object(automation, "config", lambda: {**original_config,"enabled":True}), \
            patch.object(settings, "openai_api_key", "sk-fixture-only"), \
            patch.object(translator, "get_openai_client", client):
        assert automation.process_one(saved["pending_id"])
        assert automation.process_one(saved["embedded_id"])
    assert state(saved["pending_id"])["status"] == "done"
    assert state(saved["embedded_id"])["status"] == "done"
    for name in ["Delayed Episode", "Embedded Film"]:
        cues = read_srt(root / (name + ".fa.srt"))
        assert len(cues) == 2
        assert [(cue.start.ordinal,cue.end.ordinal) for cue in cues] == [(2125,3250),(4375,5500)]
        assert all("سلام دنیا" in cue.text for cue in cues)
    assert [cue.index for cue in read_srt(delayed.with_suffix(".fa.srt"))] == [7,12]
    before = delayed.with_suffix(".fa.srt").read_bytes()
    event("sonarr", {"eventType":"Download","episodeFile":{"path":str(delayed)}})
    assert state(saved["pending_id"])["status"] == "done"
    assert delayed.with_suffix(".fa.srt").read_bytes() == before
    assert not automation.config()["enabled"] and not settings.openai_api_key
    print(json.dumps({"phase":"completed","restart_persistence":"passed","delayed_bazarr":"done",
        "embedded_english":"done","duplicate_preservation":"passed","mock_requests":len(prompts),
        "paid_requests":0,"fixture_root":str(root),"automation_left":"paused"}))
