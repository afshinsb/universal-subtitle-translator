from pathlib import Path

import pytest

from app.services import media_scanner


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("dummy", encoding="utf-8")
    return path


def test_target_subtitle_skip(tmp_path, monkeypatch):
    video = touch(tmp_path / "Movie.mkv")
    touch(tmp_path / "Movie.fa.srt")

    result = media_scanner.inspect_media_file(video, "Persian")

    assert result["item"] is None
    assert result["skipped"]["reason"] == media_scanner.TARGET_SUBTITLE_EXISTS_REASON


def test_target_subtitle_skip_accepts_language_alias(tmp_path, monkeypatch):
    video = touch(tmp_path / "Movie.mkv")
    touch(tmp_path / "Movie.persian.srt")

    result = media_scanner.inspect_media_file(video, "Persian")

    assert result["item"] is None
    assert result["skipped"]["reason"] == media_scanner.TARGET_SUBTITLE_EXISTS_REASON


def test_language_aliases_are_normalized():
    assert media_scanner.normalize_language_code("eng") == "en"
    assert media_scanner.normalize_language_code("fas") == "fa"
    assert media_scanner.normalize_language_code("zho") == "zh"
    assert media_scanner.normalize_language_code("not-a-language") == "unknown"


def test_external_priority_prefers_english(tmp_path, monkeypatch):
    video = touch(tmp_path / "Movie.mkv")
    en = touch(tmp_path / "Movie.en.srt")
    fr = touch(tmp_path / "Movie.fr.srt")

    monkeypatch.setattr(media_scanner, "count_srt_subtitles", lambda path: 3)
    monkeypatch.setattr(media_scanner, "embedded_subtitles", lambda *args, **kwargs: [])

    result = media_scanner.inspect_media_file(video, "Persian")

    assert result["skipped"] is None
    assert result["item"]["source_kind"] == "external"
    assert result["item"]["source_language"] == "en"
    assert result["item"]["source_subtitle_path"] == str(en)
    assert result["item"]["source_subtitle_path"] != str(fr)


def test_embedded_priority_prefers_english(tmp_path, monkeypatch):
    video = touch(tmp_path / "Episode.mkv")

    monkeypatch.setattr(media_scanner, "matching_external_subtitles", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        media_scanner,
        "embedded_subtitles",
        lambda *args, **kwargs: [
            {"index": 3, "language": "fr", "codec_name": "subrip"},
            {"index": 5, "language": "en", "codec_name": "subrip"},
        ],
    )

    result = media_scanner.inspect_media_file(video, "Persian")

    assert result["skipped"] is None
    assert result["item"]["source_kind"] == "embedded"
    assert result["item"]["source_language"] == "en"
    assert result["item"]["source_stream_index"] == 5


def test_overwrite_allows_existing_target_subtitle(tmp_path, monkeypatch):
    video = touch(tmp_path / "Movie.mkv")
    touch(tmp_path / "Movie.fa.srt")
    en = touch(tmp_path / "Movie.en.srt")

    monkeypatch.setattr(media_scanner, "count_srt_subtitles", lambda path: 2)
    monkeypatch.setattr(media_scanner, "embedded_subtitles", lambda *args, **kwargs: [])

    result = media_scanner.inspect_media_file(video, "Persian", overwrite=True)

    assert result["skipped"] is None
    assert result["item"]["source_kind"] == "external"
    assert result["item"]["source_subtitle_path"] == str(en)


def test_media_root_allows_scan_inside_mounted_root(tmp_path, monkeypatch):
    media_root = tmp_path / "media"
    show_folder = media_root / "Shows"
    show_folder.mkdir(parents=True)

    monkeypatch.setattr(media_scanner.settings, "media_root", media_root.resolve())

    result = media_scanner.scan_media_folder(str(show_folder), "Persian")

    assert result["total_files"] == 0
    assert result["skipped_files"] == 0


def test_media_root_rejects_scan_outside_mounted_root(tmp_path, monkeypatch):
    media_root = tmp_path / "media"
    outside_folder = tmp_path / "outside"
    media_root.mkdir()
    outside_folder.mkdir()

    monkeypatch.setattr(media_scanner.settings, "media_root", media_root.resolve())

    with pytest.raises(RuntimeError, match="outside MEDIA_ROOT"):
        media_scanner.scan_media_folder(str(outside_folder), "Persian")


def test_scan_media_path_accepts_single_video_file(tmp_path, monkeypatch):
    video = touch(tmp_path / "Movie.mkv")
    subtitle = touch(tmp_path / "Movie.en.srt")

    monkeypatch.setattr(media_scanner, "count_srt_subtitles", lambda path: 2)
    monkeypatch.setattr(media_scanner, "embedded_subtitles", lambda *args, **kwargs: [])

    result = media_scanner.scan_media_path(str(video), "Persian")

    assert result["total_files"] == 1
    assert result["items"][0]["source_subtitle_path"] == str(subtitle)
    assert result["items"][0]["relative_path"] == "Movie.mkv"


def test_read_only_media_outputs_fall_back_to_output_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    media_root = tmp_path / "media"
    show_folder = media_root / "Shows"
    video = touch(show_folder / "Movie.mkv")
    touch(show_folder / "Movie.en.srt")

    monkeypatch.setattr(media_scanner.settings, "media_root", media_root.resolve())
    monkeypatch.setattr(media_scanner.settings, "output_dir", data_dir / "outputs")
    monkeypatch.setattr(media_scanner, "is_folder_writable", lambda path: False)
    monkeypatch.setattr(media_scanner, "count_srt_subtitles", lambda path: 2)
    monkeypatch.setattr(media_scanner, "embedded_subtitles", lambda *args, **kwargs: [])

    result = media_scanner.scan_media_folder(str(media_root), "Persian")
    item = result["items"][0]

    assert item["video_path"] == str(video.resolve())
    assert item["output_location"] == "output_dir"
    assert item["output_path"] == str(data_dir / "outputs" / "Shows" / "Movie.fa.srt")
    assert "not writable" in item["output_note"]


def test_read_only_media_extracts_embedded_subtitles_to_temp_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    media_root = tmp_path / "media"
    show_folder = media_root / "Shows"
    touch(show_folder / "Episode.mkv")

    monkeypatch.setattr(media_scanner.settings, "media_root", media_root.resolve())
    monkeypatch.setattr(media_scanner.settings, "output_dir", data_dir / "outputs")
    monkeypatch.setattr(media_scanner.settings, "temp_dir", data_dir / "temp")
    monkeypatch.setattr(media_scanner, "is_folder_writable", lambda path: False)
    monkeypatch.setattr(media_scanner, "matching_external_subtitles", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        media_scanner,
        "embedded_subtitles",
        lambda *args, **kwargs: [{"index": 1, "language": "en", "codec_name": "subrip"}],
    )

    result = media_scanner.scan_media_folder(str(media_root), "Persian")
    item = result["items"][0]

    assert item["source_subtitle_location"] == "temp_dir"
    assert item["source_subtitle_path"] == str(data_dir / "temp" / "extracted" / "Shows" / "Episode.en.srt")
    assert item["output_path"] == str(data_dir / "outputs" / "Shows" / "Episode.fa.srt")
