from pathlib import Path

import pysrt
import pytest

from app.services import job_runner
from app.services.subtitle_io import batch_subtitles
from app.services.translator import (
    TranslationResult,
    build_batch_prompt,
    parse_translated_blocks,
)


def make_result(
    translations: dict[int, str],
    returned_indexes: list[int],
    duplicate_indexes: list[int] | None = None,
    malformed_block_count: int = 0,
) -> TranslationResult:
    return TranslationResult(
        translations=translations,
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        raw_output="",
        returned_indexes=returned_indexes,
        duplicate_indexes=duplicate_indexes or [],
        malformed_block_count=malformed_block_count,
    )


def make_sub(index: int, text: str) -> pysrt.SubRipItem:
    return pysrt.SubRipItem(index=index, text=text)


def run_job_with_subs(monkeypatch, subs, translated=None, write_callback=None):
    updates = []
    logs = []

    monkeypatch.setattr(job_runner, "read_srt", lambda path: pysrt.SubRipFile(subs))
    monkeypatch.setattr(job_runner, "detect_subtitle_language", lambda subs, filename: "English")
    monkeypatch.setattr(job_runner, "validate_subtitles", lambda subs, target_language: {"passed": True, "non_empty": len(subs), "empty": 0, "likely_untranslated": 0, "warnings": []})
    monkeypatch.setattr(job_runner, "update_job", lambda job_id, **fields: updates.append(fields))
    monkeypatch.setattr(job_runner, "add_log", lambda **fields: logs.append(fields))

    if translated is not None:
        monkeypatch.setattr(job_runner, "translate_batch_with_repair", lambda **kwargs: translated)

    def fake_write_srt(saved_subs, path: Path):
        if write_callback:
            write_callback(saved_subs, path)

    monkeypatch.setattr(job_runner, "write_srt", fake_write_srt)

    job_runner.run_translation_job(
        job_id="job-1",
        input_path="input.srt",
        input_filename="input.srt",
        target_language="French",
        style="natural_conversational",
    )

    return updates, logs


def test_parse_translated_blocks_preserves_duplicate_and_malformed_metadata():
    parsed = parse_translated_blocks(
        """
BEGIN[1]
first
END[1]

BEGIN[1]
duplicate
END[1]

BEGIN[2]
missing end
"""
    )

    assert parsed.translations == {1: "duplicate"}
    assert parsed.returned_indexes == [1, 1]
    assert parsed.duplicate_indexes == [1]
    assert parsed.malformed_block_count == 1


def test_prompt_starts_with_begin_1_not_begin_0():
    subs = pysrt.SubRipFile([make_sub(1, "Hello.")])
    batch = list(batch_subtitles(subs, batch_size=10, max_chars=10_000))[0]

    prompt = build_batch_prompt(
        batch=batch,
        target_language="French",
        style="natural_conversational",
        source_language="English",
    )

    assert "BEGIN[1]" in prompt
    assert "END[1]" in prompt
    assert "BEGIN[0]" not in prompt
    assert "END[0]" not in prompt


def test_alignment_validation_detects_shifted_ids_and_reordered_ids():
    batch = [
        {"index": 1, "text": "A"},
        {"index": 2, "text": "B"},
        {"index": 3, "text": "C"},
    ]
    shifted = make_result(
        translations={2: "A", 3: "B", 4: "C"},
        returned_indexes=[2, 3, 4],
    )
    shifted_report = job_runner.validate_translation_alignment(batch, shifted)

    assert not shifted_report["passed"]
    assert shifted_report["missing_indexes"] == [1]
    assert shifted_report["extra_indexes"] == [4]

    reordered = make_result(
        translations={1: "A", 2: "B", 3: "C"},
        returned_indexes=[2, 1, 3],
    )
    reordered_report = job_runner.validate_translation_alignment(batch, reordered)

    assert not reordered_report["passed"]
    assert reordered_report["reordered"] is True


def test_translate_batch_retries_invalid_alignment_before_returning(monkeypatch):
    calls = []
    logs = []
    batch = [
        {"index": 1, "text": "hello"},
        {"index": 2, "text": "there"},
    ]
    invalid = make_result(
        translations={1: "bonjour"},
        returned_indexes=[1, 1],
        duplicate_indexes=[1],
    )
    valid = make_result(
        translations={1: "bonjour", 2: "la"},
        returned_indexes=[1, 2],
    )

    def fake_translate_batch(**kwargs):
        calls.append(kwargs)
        return invalid if len(calls) == 1 else valid

    monkeypatch.setattr(job_runner, "translate_batch", fake_translate_batch)
    monkeypatch.setattr(job_runner, "add_log", lambda **kwargs: logs.append(kwargs))

    translated = job_runner.translate_batch_with_repair(
        job_id="job-1",
        batch=batch,
        source_language="English",
        target_language="French",
        style="natural_conversational",
        batch_number=1,
        batch_count=1,
    )

    assert translated == {1: "bonjour", 2: "la"}
    assert len(calls) == 2
    assert any(log["event"] == "batch_alignment_mismatch" for log in logs)
    assert any(log["event"] == "batch_alignment_validated" for log in logs)


def test_translate_batch_fails_after_repeated_non_repairable_mismatch(monkeypatch):
    batch = [
        {"index": 1, "text": "hello"},
        {"index": 2, "text": "there"},
    ]
    invalid = make_result(
        translations={1: "bonjour"},
        returned_indexes=[1, 1],
        duplicate_indexes=[1],
    )

    monkeypatch.setattr(job_runner, "translate_batch", lambda **kwargs: invalid)
    monkeypatch.setattr(job_runner, "add_log", lambda **kwargs: None)

    with pytest.raises(job_runner.BatchAlignmentError):
        job_runner.translate_batch_with_repair(
            job_id="job-1",
            batch=batch,
            source_language="English",
            target_language="French",
            style="natural_conversational",
            batch_number=1,
            batch_count=1,
        )


def test_write_back_maps_srt_index_one_to_first_list_item(monkeypatch):
    saved_texts = []

    def capture_write(saved_subs, path):
        saved_texts.extend(sub.text for sub in saved_subs)

    updates, _logs = run_job_with_subs(
        monkeypatch,
        subs=[make_sub(1, "One"), make_sub(2, "Two")],
        translated={1: "Un", 2: "Deux"},
        write_callback=capture_write,
    )

    assert saved_texts == ["Un", "Deux"]
    assert updates[-1]["status"] == "done"


def test_duplicate_srt_indexes_fail_safely(monkeypatch):
    monkeypatch.setattr(job_runner, "translate_batch_with_repair", lambda **kwargs: pytest.fail("translation should not start"))

    updates, _logs = run_job_with_subs(
        monkeypatch,
        subs=[make_sub(1, "One"), make_sub(1, "Duplicate one")],
        translated=None,
    )

    assert updates[-1]["status"] == "failed"
    assert "Duplicate SRT subtitle indexes" in updates[-1]["error"]


def test_shifted_model_output_is_rejected_and_never_written(monkeypatch):
    writes = []
    invalid = make_result(
        translations={2: "One", 3: "Two", 4: "Three"},
        returned_indexes=[2, 3, 4],
    )

    monkeypatch.setattr(job_runner, "translate_batch", lambda **kwargs: invalid)

    updates, logs = run_job_with_subs(
        monkeypatch,
        subs=[make_sub(1, "One"), make_sub(2, "Two"), make_sub(3, "Three")],
        write_callback=lambda saved_subs, path: writes.append(path),
    )

    assert writes == []
    assert updates[-1]["status"] == "failed"
    assert "Translation alignment failed" in updates[-1]["error"]
    assert any(log["event"] == "batch_alignment_mismatch" for log in logs)
