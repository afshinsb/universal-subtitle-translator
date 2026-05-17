from pathlib import Path

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
