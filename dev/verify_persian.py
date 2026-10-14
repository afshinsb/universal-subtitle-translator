"""Translate generated fixtures to Persian using an in-memory HTTP mock."""
import json
import re
import shutil
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx
from openai import OpenAI
from app.config import settings
from app.database import create_batch, get_batch, list_jobs_by_batch
from app.services import translator
from app.services.job_runner import run_folder_batch_job
from app.services.subtitle_io import read_srt, WATERMARK_TEXT

assert not settings.openai_api_key
library = Path("/media/fixtures/persian")
library.mkdir(exist_ok=True)
source = next(Path("/media/fixtures/verified-smoke/library").glob("*.mkv"))
video = library / "Development English.mkv"
shutil.copyfile(source, video)
output = video.with_suffix(".fa.srt")
output.unlink(missing_ok=True)
requests = []
def provider(request):
    prompt = json.loads(request.content)["messages"][-1]["content"]
    blocks = re.findall(r"BEGIN\[(\d+)\]\n(.*?)\nEND\[\1\]", prompt, flags=re.DOTALL)
    assert blocks and "FORCED ONLY" not in prompt
    requests.append(request.url.path)
    answer = "\n\n".join(f"BEGIN[{index}]\nسلام دنیا\nEND[{index}]" for index, _ in blocks)
    return httpx.Response(200, json={"id":"fixture","object":"chat.completion","created":0,"model":"fixture",
        "choices":[{"index":0,"message":{"role":"assistant","content":answer},"finish_reason":"stop"}],
        "usage":{"prompt_tokens":10,"completion_tokens":10,"total_tokens":20}})
def client():
    return OpenAI(api_key="sk-fixture-only",base_url="http://fixture.invalid/v1",max_retries=0,
                  http_client=httpx.Client(transport=httpx.MockTransport(provider)))
batch = "prime-persian-fixture-" + uuid4().hex
with patch.object(translator, "get_openai_client", client):
    create_batch(batch, str(library), "Persian", "natural_conversational")
    run_folder_batch_job(batch, str(library), "Persian", "natural_conversational", max_concurrency=1)
assert get_batch(batch)["status"] == "done", list_jobs_by_batch(batch)
cues = [cue for cue in read_srt(output) if cue.text != WATERMARK_TEXT]
assert len(cues) == 2
assert all(cue.text == "\u202bسلام دنیا\u202c" for cue in cues)
assert [(cue.start.ordinal,cue.end.ordinal) for cue in cues] == [(2125,3250),(4375,5500)]
assert requests
print(json.dumps({"persian_fixture":"passed","paid_requests":0,"mock_requests":len(requests),"dialogue_cues":len(cues),"output":str(output),"persistent_batch":batch}))
