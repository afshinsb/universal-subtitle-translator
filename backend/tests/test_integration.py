import shutil
import subprocess
import sys
import time
import re

import pytest

from app.services import ffmpeg_service


def test_browser_upload_download_pipeline(client, monkeypatch):
    from app.config import settings
    from app.services import translator
    monkeypatch.setattr(settings, "openai_api_key", "sk-fixture-key-for-local-tests")

    def model_reply(prompt):
        indexes = re.findall(r"BEGIN\[(\d+)\]\n", prompt)
        text = "\n".join(f"BEGIN[{index}]\nBonjour !\nEND[{index}]" for index in indexes)
        parsed = translator.parse_translated_blocks(text)
        return translator.TranslationResult(parsed.translations, 0, 0, 0, text, parsed.returned_indexes, [], 0)

    monkeypatch.setattr(translator, "call_openai", model_reply)
    source = b"7\n00:00:01,234 --> 00:00:02,567\nHello!\n"
    response = client.post("/jobs", data={"target_language": "French", "style": "formal"},
                           files={"file": ("Movie.en.srt", source, "application/x-subrip")}, follow_redirects=False)
    assert response.status_code == 303, response.text
    location = response.headers["location"]
    for _ in range(200):
        status = client.get(location + "/status").json()
        if status["status"] in {"done", "failed"}:
            break
        time.sleep(0.01)
    assert status["status"] == "done", status
    assert status["output_file"] == "Movie.fr.srt"
    download = client.get(location + "/download")
    assert download.status_code == 200
    assert "00:00:01,234 --> 00:00:02,567" in download.text
    assert "Bonjour!" in download.text
    assert list(settings.output_dir.glob("*/Movie.fr.srt"))


def test_complete_media_pipeline(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("Install FFmpeg and ffprobe for the media smoke test.")
    from scripts.smoke import run_smoke
    assert run_smoke(tmp_path)["status"] == "passed"


def test_ffmpeg_timeout_terminates_child(monkeypatch):
    monkeypatch.setattr(ffmpeg_service.settings, "ffmpeg_timeout_seconds", 0.1)
    with pytest.raises(RuntimeError, match="timed out"):
        ffmpeg_service.run_command([sys.executable, "-c", "import time; time.sleep(10)"])


def test_failed_extraction_preserves_existing_sidecar(tmp_path, monkeypatch):
    source = tmp_path / "video.mkv"
    output = tmp_path / "video.en.srt"
    output.write_bytes(b"user data")
    monkeypatch.setattr(ffmpeg_service, "run_command", lambda *a, **kw: subprocess.CompletedProcess([], 1, "", "fixture failure"))
    with pytest.raises(RuntimeError, match="fixture failure"):
        ffmpeg_service.extract_subtitle(source, output, stream_index=1)
    assert output.read_bytes() == b"user data"
    assert sorted(path.name for path in tmp_path.iterdir()) == [output.name]
