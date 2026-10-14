"""Fixture-only verification inside ust-dev-backend; never calls a paid provider."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/smoke")
from smoke import run_smoke
from app.config import settings
from app.database import create_batch, get_batch
from app.services.ffmpeg_service import list_text_subtitle_streams, extract_subtitle
from app.services.media_scanner import scan_media_folder, sidecar_subtitles
from app.services.subtitle_io import read_srt

assert not settings.openai_api_key
fixture = Path("/media/fixtures/verified-smoke")
if fixture.exists():
    shutil.rmtree(fixture)
fixture.mkdir()
print("fixture_translation:", json.dumps(run_smoke(fixture)))
video = next((fixture / "library").glob("*.mkv"))
streams = list_text_subtitle_streams(video)
assert any(s["language"] == "eng" for s in streams)
external = video.with_name(video.stem + ".en.srt")
shutil.copyfile(fixture / "fixture.en.srt", external)
assert len(read_srt(external)) == 2
assert external in sidecar_subtitles(video.parent, video.stem)
scan = scan_media_folder(str(video.parent), "Persian")
assert scan["total_files"] == 1
print("fixture_scan:", json.dumps({"files": scan["total_files"], "streams": streams, "external_srt": external.name}))
for library in [Path("/media/movies"), Path("/media/shows")]:
    directories = sum(1 for p in library.iterdir() if p.is_dir())
    candidate = next((p for p in library.rglob("*") if p.suffix.lower() in {".mkv", ".mp4", ".avi", ".m4v"} and p.is_file()), None)
    result = {"library": str(library), "directories": directories, "sample_found": candidate is not None}
    if candidate:
        streams = list_text_subtitle_streams(candidate)
        sidecars = sidecar_subtitles(candidate.parent, candidate.stem)
        result.update(text_subtitle_streams=len(streams), english_streams=sum(s["language"] == "eng" for s in streams), readable_sidecars=len(sidecars))
        english = next((s for s in streams if s["language"] == "eng"), None)
        if english:
            output = settings.temp_dir / (library.name + "-real-extracted.srt")
            output.unlink(missing_ok=True)
            extract_subtitle(candidate, output, stream_index=english["index"])
            result["extracted_cues"] = len(read_srt(output))
        if sidecars:
            result["sidecar_cues"] = len(read_srt(sidecars[0]))
    assert not __import__("os").access(library, __import__("os").W_OK)
    print("real_media:", json.dumps(result))
marker = "prime-dev-persistence-validation"
if not get_batch(marker):
    create_batch(marker, "/media/fixtures", "Persian", "natural_conversational")
assert get_batch(marker)
for executable in ["ffmpeg", "ffprobe"]:
    print(subprocess.check_output([executable, "-version"], text=True).splitlines()[0])
print("persistence_marker:", marker)
