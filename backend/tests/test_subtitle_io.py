import pysrt

from app.services.subtitle_io import (
    batch_subtitles,
    estimate_subtitle_tokens,
    wrap_subtitle_text,
)


def without_direction_marks(text: str) -> str:
    return text.replace("\u202b", "").replace("\u202c", "")


def make_sub(text: str, index: int = 1):
    return pysrt.SubRipItem(index=index, text=text)


def test_batching_uses_real_srt_indexes_not_list_positions():
    subs = [
        make_sub("First", index=1),
        make_sub("Second", index=2),
        make_sub("Fifth", index=5),
    ]

    batches = list(batch_subtitles(subs, batch_size=10, max_chars=10_000))

    assert [item["index"] for item in batches[0]] == [1, 2, 5]
    assert 0 not in [item["index"] for item in batches[0]]


def test_cjk_token_estimate_is_higher_than_latin_for_same_length():
    cjk = "这是一个很长的中文字幕，需要按照字符估算。"
    latin = "This is a long subtitle that is estimated by words."

    assert estimate_subtitle_tokens(cjk, "Chinese") > estimate_subtitle_tokens(latin, "English")


def test_batching_respects_estimated_token_limit_for_cjk():
    subs = [
        make_sub("这是一个很长的中文字幕，需要更小的批次来避免提示过大。")
        for _ in range(6)
    ]

    batches = list(
        batch_subtitles(
            subs,
            batch_size=10,
            max_chars=10_000,
            language="Chinese",
            max_estimated_tokens=60,
        )
    )

    assert len(batches) > 1
    assert sum(len(batch) for batch in batches) == 6


def test_wrap_cjk_without_adding_spaces():
    text = "这是一个非常长的中文字幕句子，需要换行但不应该在汉字之间加入空格。"

    wrapped = wrap_subtitle_text(text, "Chinese")

    assert "\n" in wrapped
    assert " " not in wrapped
    assert all(len(line) <= 22 for line in wrapped.splitlines())


def test_wrap_rtl_removes_bad_punctuation_spacing():
    text = "این یک جمله فارسی طولانی است ؟ باید خوانا باشد و فاصله گذاری نشانه ها درست شود ."

    wrapped = wrap_subtitle_text(text, "Persian")

    assert " ؟" not in wrapped
    assert " ." not in wrapped
    visible_wrapped = without_direction_marks(wrapped)

    assert all(line.startswith("\u202b") and line.endswith("\u202c") for line in wrapped.splitlines())
    assert all(len(line) <= 38 for line in visible_wrapped.splitlines())


def test_wrap_rtl_converts_common_ascii_punctuation():
    wrapped = wrap_subtitle_text("مرحبا, كيف الحال? جيد; نعم.", "Arabic")
    visible_wrapped = without_direction_marks(wrapped)

    assert "؟" in visible_wrapped
    assert "،" in visible_wrapped
    assert "؛" in visible_wrapped
    assert "?" not in visible_wrapped
    assert "," not in visible_wrapped
    assert ";" not in visible_wrapped


def test_wrap_long_unspaced_text_has_no_extreme_line():
    text = "A" * 120

    wrapped = wrap_subtitle_text(text, "English")

    assert all(len(line) <= 42 for line in wrapped.splitlines())
