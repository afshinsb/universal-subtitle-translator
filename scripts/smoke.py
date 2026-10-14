"""Credential-free smoke test, also runnable inside the release backend image."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from unittest.mock import patch


def run_smoke(root: Path) -> dict:
    import httpx
    from openai import OpenAI
    from app.config import ensure_directories, settings
    from app.database import create_batch, get_batch, init_db, list_jobs_by_batch
    from app.services import translator
    from app.services.job_runner import run_folder_batch_job
    from app.services.subtitle_io import read_srt, WATERMARK_TEXT

    media = root / "library"
    media.mkdir()
    source = root / "fixture.en.srt"
    source.write_text(
        '7\n00:00:02,125 --> 00:00:03,250\n<i>Hello, café!</i>\nSecond line.\n\n'
        '12\n00:00:04,375 --> 00:00:05,500\nHow are you?\n', encoding="utf-8"
    )
    original = source.read_bytes()
    forced = root / "forced.en.srt"
    forced.write_text('1\n00:00:00,000 --> 00:00:01,000\nFORCED ONLY\n', encoding="utf-8")
    video = media / "Film [2026] café.mkv"
    subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=size=16x16:rate=1:duration=6",
        "-i", str(forced), "-i", str(source), "-map", "0:v", "-map", "1:0", "-map", "2:0",
        "-c:v", "ffv1", "-c:s", "srt", "-metadata:s:s:0", "language=eng",
        "-metadata:s:s:1", "language=eng", "-disposition:s:0", "forced",
        "-disposition:s:1", "default", str(video),
    ], check=True, timeout=30)
    prompts = []

    def provider(request):
        assert request.url.path.endswith("/chat/completions")
        prompt = json.loads(request.content)["messages"][-1]["content"]
        prompts.append(prompt)
        blocks = re.findall(r"BEGIN\[(\d+)\]\n(.*?)\nEND\[\1\]", prompt, flags=re.DOTALL)
        assert blocks and "FORCED ONLY" not in prompt
        translations = [f"BEGIN[{index}]\n<i>Bonjour, café !</i><LB>Deuxième ligne.\nEND[{index}]" for index, _ in blocks]
        return httpx.Response(200, json={
            "id": "smoke", "object": "chat.completion", "created": 0, "model": "fixture-model",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "\n\n".join(translations)}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        })

    def client():
        return OpenAI(api_key="sk-fixture-only", base_url="http://fixture.invalid/v1", max_retries=0,
                      http_client=httpx.Client(transport=httpx.MockTransport(provider)))

    data = root / "data"
    with patch.multiple(settings, data_dir=data, upload_dir=data / "uploads", output_dir=data / "outputs",
                        temp_dir=data / "temp", database_path=data / "app.db", media_root=media,
                        openai_model="fixture-model"), patch.object(translator, "get_openai_client", client):
        ensure_directories()
        init_db()
        create_batch("smoke", str(media), "French", "natural_conversational")
        run_folder_batch_job("smoke", str(media), "French", "natural_conversational", max_concurrency=1)
        jobs = list_jobs_by_batch("smoke")
        assert get_batch("smoke")["status"] == "done", jobs
        assert len(jobs) == 1 and jobs[0]["status"] == "done", jobs
        output = video.with_name(video.stem + ".fr.srt")
        assert Path(jobs[0]["output_path"]) == output
        cues = [cue for cue in read_srt(output) if cue.text != WATERMARK_TEXT]
        assert [(cue.start.ordinal, cue.end.ordinal) for cue in cues] == [(2125, 3250), (4375, 5500)]
        assert all("<i>Bonjour, café!</i>\nDeuxième ligne." == cue.text for cue in cues)
        assert source.read_bytes() == original
        saved = output.read_bytes()
        request_count = len(prompts)
        create_batch("repeat", str(media), "French", "natural_conversational")
        run_folder_batch_job("repeat", str(media), "French", "natural_conversational", max_concurrency=1)
        assert list_jobs_by_batch("repeat")[0]["status"] == "skipped"
        assert len(prompts) == request_count and output.read_bytes() == saved
        assert not list(media.glob(".*.tmp"))
        return {"status": "passed", "provider_requests": request_count, "dialogue_cues": len(cues),
                "output_name": output.name, "repeat": "skipped; output preserved"}


if __name__ == "__main__":
    # Never load a real .env or use mounted application data or model credentials.
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    os.environ["OPENAI_API_KEY"] = ""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    with tempfile.TemporaryDirectory(prefix="ust-smoke-") as sandbox:
        print(json.dumps(run_smoke(Path(sandbox)), ensure_ascii=True))
