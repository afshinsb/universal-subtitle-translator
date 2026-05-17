import json
import subprocess
import time
from pathlib import Path
from typing import Callable

from app.config import settings


def stop_process(process: subprocess.Popen, terminate: bool = True) -> None:
    if process.poll() is not None:
        return

    if terminate:
        process.terminate()
    else:
        process.kill()

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()

        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def run_command(
    command: list[str],
    cancel_check: Callable[[], bool] | None = None,
) -> subprocess.CompletedProcess:
    executable = Path(command[0]).name if command else "command"

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"{executable} was not found on PATH.") from exc

    started_at = time.monotonic()

    try:
        while True:
            if time.monotonic() - started_at > settings.ffmpeg_timeout_seconds:
                stop_process(process, terminate=False)
                raise RuntimeError(
                    f"{executable} timed out after {settings.ffmpeg_timeout_seconds} seconds."
                )

            if cancel_check and cancel_check():
                stop_process(process)
                raise RuntimeError(f"{executable} cancelled.")

            try:
                stdout, stderr = process.communicate(timeout=0.25)
                return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                continue
    except Exception:
        stop_process(process, terminate=False)
        raise


def get_media_info(video_path: Path, cancel_check: Callable[[], bool] | None = None) -> dict:
    command = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_streams",
        str(video_path),
    ]

    result = run_command(command, cancel_check=cancel_check)

    if result.returncode != 0:
        raise RuntimeError(result.stderr)

    return json.loads(result.stdout)


TEXT_SUBTITLE_CODECS = {"subrip", "ass", "ssa", "webvtt", "mov_text"}


def list_text_subtitle_streams(
    video_path: Path,
    cancel_check: Callable[[], bool] | None = None,
) -> list[dict]:
    info = get_media_info(video_path, cancel_check=cancel_check)

    subtitle_streams = []

    for stream in info.get("streams", []):
        if stream.get("codec_type") != "subtitle":
            continue

        codec_name = stream.get("codec_name", "")
        tags = stream.get("tags", {})
        language = tags.get("language", "").lower()
        index = stream.get("index")

        if codec_name in TEXT_SUBTITLE_CODECS:
            subtitle_streams.append(
                {
                    "index": index,
                    "language": language,
                    "codec_name": codec_name,
                }
            )

    return subtitle_streams


def find_text_subtitle_stream(
    video_path: Path,
    preferred_language: str = "eng",
    cancel_check: Callable[[], bool] | None = None,
) -> int | None:
    subtitle_streams = list_text_subtitle_streams(video_path, cancel_check=cancel_check)

    for stream in subtitle_streams:
        if stream["language"] == preferred_language:
            return stream["index"]

    if subtitle_streams:
        return subtitle_streams[0]["index"]

    return None


def extract_subtitle(
    video_path: Path,
    output_srt_path: Path,
    preferred_language: str = "eng",
    stream_index: int | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> Path:
    if stream_index is None:
        stream_index = find_text_subtitle_stream(video_path, preferred_language, cancel_check=cancel_check)

    if stream_index is None:
        raise RuntimeError("No extractable text subtitle stream found.")

    output_srt_path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-map",
        f"0:{stream_index}",
        str(output_srt_path),
    ]

    try:
        result = run_command(command, cancel_check=cancel_check)
    except Exception:
        output_srt_path.unlink(missing_ok=True)
        raise

    if result.returncode != 0:
        output_srt_path.unlink(missing_ok=True)
        raise RuntimeError(result.stderr)

    return output_srt_path
