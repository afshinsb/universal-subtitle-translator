"""Isolated browser QA server: real routes/SQLite, mocked provider, no credentials.

Run only in a disposable test container with /qa storage and localhost binding.
Never mount production/development data or pass real provider credentials here.
"""

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/app")


def main():
    import httpx
    import uvicorn
    from openai import OpenAI
    from app.config import settings, ensure_directories
    from app.database import init_db
    from app.services import automation, translator
    from app.main import app
    import app.main as application
    application.run_openai_api_key_test=lambda:None

    assert settings.dev_mode and not settings.openai_api_key, (
        "Fixture QA must have no real key"
    )
    root = Path("/qa")
    library = root / "fixtures"
    library.mkdir(exist_ok=True)
    settings.data_dir = root / "data"
    settings.database_path = settings.data_dir / "app.db"
    settings.upload_dir = settings.data_dir / "uploads"
    settings.output_dir = settings.data_dir / "outputs"
    settings.temp_dir = settings.data_dir / "temp"
    settings.media_root = root
    settings.auth_enabled = False
    settings.media_intake_enabled = False
    settings.openai_api_key = "sk-fixture-only-not-a-real-key"
    settings.openai_daily_budget_usd = 0
    ensure_directories()
    init_db()
    automation.init_schema()
    automation.save_config(False, [str(library)], {}, "events_only")
    automation.save_scope([], "libraries")
    english = "7\n00:00:01,125 --> 00:00:02,250\nHello, how are you?\n\n12\n00:00:03,375 --> 00:00:04,500\nAre you kidding me?\n"
    source = library / "fixture.en.srt"
    source.write_text(english)
    video = library / "Fixture.mkv"
    if not video.exists():
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=size=16x16:rate=1:duration=6",
                "-i",
                str(source),
                "-map",
                "0:v",
                "-map",
                "1:0",
                "-c:v",
                "ffv1",
                "-c:s",
                "srt",
                "-metadata:s:s:0",
                "language=eng",
                str(video),
            ],
            check=True,
            timeout=30,
        )
    for i in range(100):
        path = (
            library
            / f"UI Fixture Series.S01E{i + 1:03}.1080p.WEB-DL.Long-Filename.For.Responsive.Layout.Verification.mkv"
        )
        if not path.exists():
            path.write_bytes(video.read_bytes())
            path.with_suffix(".en.srt").write_text(english)
        automation.enqueue(str(path), "sonarr" if i % 5 else "radarr")

    def provider(request):
        assert request.url.path.endswith("/chat/completions")
        payload = json.loads(request.content)
        prompt = payload["messages"][-1]["content"]
        blocks = re.findall(r"BEGIN\[(\d+)\]\n(.*?)\nEND\[\1\]", prompt, re.DOTALL)
        assert blocks
        text = "\n\n".join(
            f"BEGIN[{index}]\nسلام، خوبی؟\nEND[{index}]" for index, _ in blocks
        )
        return httpx.Response(
            200,
            json={
                "id": "fixture",
                "object": "chat.completion",
                "created": 0,
                "model": payload["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": text},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 20,
                    "total_tokens": 40,
                },
            },
        )

    translator.get_openai_client = lambda: OpenAI(
        api_key="sk-fixture-only",
        base_url="http://fixture.invalid/v1",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(provider)),
    )
    (root / "source-hash.json").write_text(
        json.dumps(
            {
                "source": str(source),
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
        )
    )
    uvicorn.run(app, host="0.0.0.0", port=2290, log_level="warning")


if __name__ == "__main__":
    main()
