"""Retained realistic fixtures; execute in ust-dev-backend with OPENAI_API_KEY cleared."""
import argparse
import hashlib
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
from app.database import get_connection
from app.services import automation, translator
from app.services.subtitle_io import read_srt

parser = argparse.ArgumentParser()
parser.add_argument("phase", choices=["prepare","wait","subtitle","finish"])
args = parser.parse_args()
assert settings.dev_mode and not settings.openai_api_key
cfg = automation.config()
assert not cfg["enabled"] and not settings.automation_real_library_processing
manifest_path = Path("/app/data/integration-fixtures.json")
english = "7\n00:00:02,125 --> 00:00:03,250\nHello, café!\n\n12\n00:00:04,375 --> 00:00:05,500\nHow are you?\n"
if args.phase == "prepare":
    root = Path("/media/fixtures") / ("integration-" + uuid4().hex[:8])
    for folder in [root/"movies",root/"episodes"]:
        folder.mkdir(parents=True)
    movie = root/"movies"/"Fixture Film (2026).mkv"
    shutil.copyfile(next(Path("/media/fixtures/verified-smoke/library").glob("*.mkv")),movie)
    videos = [movie]
    for episode in [1,2,3]:
        video = root/"episodes"/f"Fixture Show - S01E{episode:02}.mkv"
        subprocess.run(["ffmpeg","-nostdin","-v","error","-f","lavfi","-i",
            "color=size=16x16:rate=1:duration=6","-c:v","ffv1",str(video)],check=True,timeout=30)
        if episode != 2:
            video.with_suffix(".en.srt").write_text(english)
        videos.append(video)
    existing = videos[3].with_suffix(".fa.srt")
    existing.write_text(english.replace("Hello, café!","سلام").replace("How are you?","چطوری؟"))
    mappings = {**cfg["path_mappings"],"/movies/ust-fixtures":str(root/"movies"),"/tv/ust-fixtures":str(root/"episodes")}
    automation.save_config(False,cfg["roots"],mappings)
    automation.save_scope([str(path) for path in videos])
    manifest_path.write_text(json.dumps({"root":str(root),"videos":[str(p) for p in videos],
        "existing_hash":hashlib.sha256(existing.read_bytes()).hexdigest()}))
    print(json.dumps({"phase":"prepared","fixture_root":str(root),"files":4,"real_processing":False}))
    raise SystemExit
saved = json.loads(manifest_path.read_text())
videos = [Path(value) for value in saved["videos"]]
if args.phase == "subtitle":
    waiting = next(row for row in automation.list_queue(10000) if row["video_path"] == str(videos[2]))
    assert waiting["status"] == "waiting_source" and waiting["attempts"] == 0
    videos[2].with_suffix(".en.srt").write_text(english)
    print(json.dumps({"phase":"subtitle-arrived","restart_pending":"preserved"}))
    raise SystemExit
cfg = automation.config()
calls = []
transient = args.phase == "finish"
def provider(request):
    global transient
    prompt = json.loads(request.content)["messages"][-1]["content"]
    calls.append(prompt)
    if transient:
        transient = False
        return httpx.Response(503,json={"error":{"message":"Simulated temporary failure"}})
    blocks = re.findall(r"BEGIN\[(\d+)\]\n(.*?)\nEND\[\1\]",prompt,re.DOTALL)
    assert blocks and "FORCED ONLY" not in prompt
    text = "\n\n".join(f"BEGIN[{index}]\nسلام دنیا\nEND[{index}]" for index,_ in blocks)
    return httpx.Response(200,json={"id":"mock","object":"chat.completion","created":0,"model":"fixture",
        "choices":[{"index":0,"message":{"role":"assistant","content":text},"finish_reason":"stop"}],
        "usage":{"prompt_tokens":10,"completion_tokens":10,"total_tokens":20}})
def client():
    return OpenAI(api_key="sk-fixture-only",base_url="http://fixture.invalid/v1",max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(provider)))
rows = {row["video_path"]:row for row in automation.list_queue(10000)}
with patch.object(automation,"config",lambda:{**cfg,"enabled":True}), \
        patch.object(settings,"openai_api_key","sk-fixture-only"), \
        patch.object(translator,"get_openai_client",client):
    targets = videos if args.phase == "wait" else [videos[2]]
    for video in targets:
        item = rows[str(video)]
        assert automation.process_one(item["id"])
        if args.phase == "finish":
            current = next(row for row in automation.list_queue(10000) if row["id"] == item["id"])
            assert current["status"] == "retry" and not video.with_suffix(".fa.srt").exists()
            with get_connection() as conn:
                conn.execute("UPDATE automation_queue SET next_run=0 WHERE id=?",(item["id"],))
            assert automation.process_one(item["id"])
rows = {row["video_path"]:row for row in automation.list_queue(10000)}
assert rows[str(videos[3])]["status"] == "skipped"
assert hashlib.sha256(videos[3].with_suffix(".fa.srt").read_bytes()).hexdigest() == saved["existing_hash"]
if args.phase == "wait":
    assert rows[str(videos[2])]["status"] == "waiting_source"
    assert rows[str(videos[2])]["attempts"] == 0
else:
    for video in videos[:3]:
        assert rows[str(video)]["status"] == "done"
        cues = read_srt(video.with_suffix(".fa.srt"))
        assert len(cues) == 2
        assert [(c.start.ordinal,c.end.ordinal) for c in cues] == [(2125,3250),(4375,5500)]
        assert all("سلام دنیا" in cue.text for cue in cues)
    assert [c.index for c in read_srt(videos[1].with_suffix(".fa.srt"))] == [7,12]
assert not automation.config()["enabled"]
print(json.dumps({"phase":args.phase,"states":{p.name:rows[str(p)]["status"] for p in videos},
    "mock_requests":len(calls),"paid_requests":0,"existing_persian":"preserved"}))
