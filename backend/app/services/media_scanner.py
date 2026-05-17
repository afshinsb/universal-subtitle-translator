import os
from pathlib import Path
from typing import Callable

from app.config import settings
from app.models import known_language_code, language_code
from app.services.ffmpeg_service import list_text_subtitle_streams
from app.services.subtitle_io import read_srt

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".webm"}

DEFAULT_SOURCE_PREFERENCE = "en,fr,es,de,it,pt,tr,ar,ru,ja,ko,zh,*"
TARGET_SUBTITLE_EXISTS_REASON = "Already has selected target subtitle"

def normalize_language_code(value: str | None) -> str:
    return known_language_code(value) or "unknown"


def parse_source_preference(value: str | None) -> list[str]:
    if not value:
        value = DEFAULT_SOURCE_PREFERENCE

    result = []

    for part in value.split(","):
        normalized = part.strip().lower()

        if not normalized:
            continue

        if normalized in {"any", "*"}:
            result.append("*")
        else:
            result.append(normalize_language_code(normalized))

    if "*" not in result:
        result.append("*")

    return result or ["en", "fr", "*"]


def preference_rank(language: str, preferences: list[str]) -> int:
    normalized = normalize_language_code(language)

    for index, preferred in enumerate(preferences):
        if preferred == "*" or preferred == normalized:
            return index

    return len(preferences)


def subtitle_language_from_name(path: Path, video_stem: str | None = None) -> str:
    parts = path.stem.split(".")

    if video_stem and parts and parts[0].lower() == video_stem.lower():
        parts = parts[1:]

    for part in reversed(parts):
        code = normalize_language_code(part)

        if code != "unknown":
            return code

    return "unknown"


def count_srt_subtitles(path: Path) -> int:
    subs = read_srt(path)
    return len([sub for sub in subs if sub.text.strip()])


def translated_output_name(base_stem: str, target_language: str) -> str:
    return f"{base_stem}.{language_code(target_language)}.srt"


def extracted_source_name(base_stem: str, source_language: str) -> str:
    code = normalize_language_code(source_language)

    if code == "unknown":
        code = "und"

    return f"{base_stem}.{code}.srt"


def safe_relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return path.name


def translated_output_exists(folder: Path, base_stem: str, target_language: str) -> Path | None:
    target_code = language_code(target_language)
    direct = folder / translated_output_name(base_stem, target_language)

    if direct.exists():
        return direct

    for path in folder.glob(f"{base_stem}*.srt"):
        if subtitle_language_from_name(path, base_stem) == target_code:
            return path

    return None


def matching_external_subtitles(video_path: Path, target_language: str) -> list[dict]:
    folder = video_path.parent
    target_code = language_code(target_language)
    matches = []

    for path in sorted(folder.glob(f"{video_path.stem}*.srt")):
        language = subtitle_language_from_name(path, video_path.stem)

        if language == target_code:
            continue

        try:
            total_subtitles = count_srt_subtitles(path)
        except Exception:
            continue

        matches.append(
            {
                "path": path,
                "language": language,
                "total_subtitles": total_subtitles,
            }
        )

    return [match for match in matches if match["total_subtitles"] > 0]


def choose_external_subtitle(
    subtitles: list[dict],
    preferences: list[str],
) -> dict | None:
    if not subtitles:
        return None

    return sorted(
        subtitles,
        key=lambda item: (preference_rank(item["language"], preferences), str(item["path"]).lower()),
    )[0]


def embedded_subtitles(
    video_path: Path,
    cancel_check: Callable[[], bool] | None = None,
) -> list[dict]:
    streams = list_text_subtitle_streams(video_path, cancel_check=cancel_check)

    for stream in streams:
        stream["language"] = normalize_language_code(stream.get("language"))

    return streams


def choose_embedded_subtitle(streams: list[dict], preferences: list[str]) -> dict | None:
    if not streams:
        return None

    return sorted(
        streams,
        key=lambda item: (preference_rank(item["language"], preferences), item["index"]),
    )[0]


def inspect_media_file(
    video_path: str | Path,
    target_language: str,
    source_preference: str | None = None,
    overwrite: bool = False,
    root: Path | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> dict:
    if cancel_check and cancel_check():
        raise RuntimeError("Scan cancelled.")

    video_path = Path(video_path).resolve()

    if not video_path.exists() or not video_path.is_file():
        raise RuntimeError("Media file does not exist or is not a file.")

    if video_path.suffix.lower() not in VIDEO_EXTENSIONS:
        raise RuntimeError("File is not a supported video file.")

    root = root.resolve() if root else video_path.parent
    preferences = parse_source_preference(source_preference)
    relative_video = safe_relative_path(video_path, root)
    subfolder = safe_relative_path(video_path.parent, root)
    target_code = language_code(target_language)

    if subfolder == ".":
        subfolder = ""

    output_path = video_path.parent / translated_output_name(video_path.stem, target_language)
    existing_output = translated_output_exists(video_path.parent, video_path.stem, target_language)

    def skipped_result(reason: str, skipped_output_path: Path | None = output_path) -> dict:
        return {
            "item": None,
            "skipped": {
                "video_path": str(video_path),
                "relative_path": relative_video,
                "subfolder": subfolder,
                "status": "skipped",
                "step": "skipped",
                "reason": reason,
                "output_path": str(skipped_output_path) if skipped_output_path else None,
            },
        }

    if existing_output and not overwrite:
        return skipped_result(TARGET_SUBTITLE_EXISTS_REASON, existing_output)

    embedded_streams = []
    embedded_error = None

    try:
        embedded_streams = embedded_subtitles(video_path, cancel_check=cancel_check)
    except Exception as exc:
        embedded_error = exc

    has_target_embedded = any(
        stream.get("language") == target_code
        for stream in embedded_streams
    )

    if has_target_embedded and not overwrite:
        return skipped_result(TARGET_SUBTITLE_EXISTS_REASON, None)

    external_subtitles = matching_external_subtitles(video_path, target_language)
    selected_external = choose_external_subtitle(external_subtitles, preferences)

    if selected_external:
        return {
            "item": {
                "video_path": str(video_path),
                "relative_path": relative_video,
                "subfolder": subfolder,
                "source_kind": "external",
                "step": "found external subtitle",
                "source_language": selected_external["language"],
                "source_selection_reason": "External subtitle preferred by language priority",
                "source_subtitle_path": str(selected_external["path"]),
                "source_subtitle_name": selected_external["path"].name,
                "output_path": str(output_path),
                "output_name": output_path.name,
                "total_subtitles": selected_external["total_subtitles"],
            },
            "skipped": None,
        }

    if embedded_error:
        return skipped_result(f"Could not inspect embedded subtitles: {embedded_error}")

    embedded = choose_embedded_subtitle(embedded_streams, preferences)

    if not embedded:
        return skipped_result("No external or extractable embedded subtitle found.")

    extracted_path = video_path.parent / extracted_source_name(video_path.stem, embedded["language"])

    return {
        "item": {
            "video_path": str(video_path),
            "relative_path": relative_video,
            "subfolder": subfolder,
            "source_kind": "embedded",
            "step": "extracting embedded subtitle",
            "source_language": embedded["language"],
            "source_selection_reason": "Embedded subtitle selected by language priority",
            "source_stream_index": embedded["index"],
            "source_stream_codec": embedded["codec_name"],
            "source_subtitle_path": str(extracted_path),
            "source_subtitle_name": extracted_path.name,
            "output_path": str(output_path),
            "output_name": output_path.name,
            "total_subtitles": 0,
        },
        "skipped": None,
    }


def scan_media_folder(
    folder_path: str,
    target_language: str,
    source_preference: str | None = None,
    overwrite: bool = False,
    progress_callback: Callable[[dict], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> dict:
    root = Path(folder_path).resolve()

    if not root.exists() or not root.is_dir():
        raise RuntimeError("Folder does not exist or is not a directory.")

    if settings.media_root is not None:
        media_root = settings.media_root

        if media_root not in root.parents and root != media_root:
            raise RuntimeError(f"Folder is outside MEDIA_ROOT: {media_root}")

    items = []
    skipped = []
    progress = {
        "folders_scanned": 0,
        "files_checked": 0,
        "candidate_files_found": 0,
    }

    def report(current_path: Path | None = None) -> None:
        if not progress_callback:
            return

        safe_current_path = ""

        if current_path:
            safe_current_path = safe_relative_path(current_path, root)

        progress_callback(
            {
                **progress,
                "current_path": safe_current_path,
                "items_found": len(items),
                "skipped_found": len(skipped),
            }
        )

    report(root)

    for current_dir, dirnames, filenames in os.walk(root):
        if cancel_check and cancel_check():
            raise RuntimeError("Scan cancelled.")

        dirnames.sort()
        progress["folders_scanned"] += 1
        current_folder = Path(current_dir)
        report(current_folder)

        for filename in sorted(filenames):
            if cancel_check and cancel_check():
                raise RuntimeError("Scan cancelled.")

            path = current_folder / filename
            progress["files_checked"] += 1

            if path.suffix.lower() not in VIDEO_EXTENSIONS:
                report(path)
                continue

            progress["candidate_files_found"] += 1
            report(path)
            scan_result = inspect_media_file(
                video_path=path,
                target_language=target_language,
                source_preference=source_preference,
                overwrite=overwrite,
                root=root,
                cancel_check=cancel_check,
            )

            if scan_result["item"]:
                items.append(scan_result["item"])

            if scan_result["skipped"]:
                skipped.append(scan_result["skipped"])

            report(path)

    return {
        "items": items,
        "skipped": skipped,
        "total_files": len(items),
        "skipped_files": len(skipped),
        "total_subtitles": sum(item["total_subtitles"] for item in items),
    }
