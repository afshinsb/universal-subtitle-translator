from pathlib import Path
import codecs
from copy import copy
import re
import os
from uuid import uuid4

import pysrt

from app.models import KNOWN_LANGUAGE_SUFFIXES, language_code

WATERMARK_TEXT = '<font color="red">Translated by AFSHIN SABERI enjoy :)\nTheAfshin.com</font>'
WATERMARK_DURATION_MS = 3000
WATERMARK_MIN_FIRST_START_MS = 1000
WATERMARK_TIMING_GAP_MS = 100
WATERMARK_END_GAP_MS = 500

CJK_RE = re.compile(r"[\u3040-\u30FF\u3400-\u4DBF\u4E00-\u9FFF\uAC00-\uD7AF]")
RTL_RE = re.compile(r"[\u0590-\u08FF\uFB1D-\uFDFF\uFE70-\uFEFF]")
DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
CJK_BREAK_RE = re.compile(r"([。！？!?；;，,、])")

RTL_LANGUAGE_CODES = {"fa", "ar", "ur", "he"}
CJK_LANGUAGE_CODES = {"zh", "ja", "ko"}
DEVANAGARI_LANGUAGE_CODES = {"hi", "ur"}
RTL_EMBEDDING_MARK = "\u202b"
POP_DIRECTIONAL_FORMATTING = "\u202c"


def text_profile(text: str, language: str | None = None) -> str:
    code = language_code(language)

    if code in CJK_LANGUAGE_CODES or CJK_RE.search(text):
        return "cjk"

    if code in RTL_LANGUAGE_CODES or RTL_RE.search(text):
        return "rtl"

    if code in DEVANAGARI_LANGUAGE_CODES or DEVANAGARI_RE.search(text):
        return "devanagari"

    return "latin"


def estimate_subtitle_tokens(text: str, language: str | None = None) -> int:
    cleaned = clean_subtitle_text(text)

    if not cleaned:
        return 0

    profile = text_profile(cleaned, language)

    if profile == "cjk":
        cjk_chars = len(CJK_RE.findall(cleaned))
        other_chars = max(0, len(cleaned) - cjk_chars)
        return max(1, cjk_chars + (other_chars // 4))

    if profile == "rtl":
        words = len(re.findall(r"[\w\u0590-\u08FF]+", cleaned, flags=re.UNICODE))
        return max(1, int(words * 1.35) + len(cleaned) // 18)

    if profile == "devanagari":
        words = len(re.findall(r"[\w\u0900-\u097F]+", cleaned, flags=re.UNICODE))
        return max(1, int(words * 1.4) + len(cleaned) // 16)

    words = len(re.findall(r"\S+", cleaned))
    return max(1, int(words * 1.3) + len(cleaned) // 24)


def read_srt(path: Path):
    with path.open("rb") as source:
        prefix = source.read(4)
    if prefix.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        encodings = ("utf-32",)
    elif prefix.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        encodings = ("utf-16",)
    else:
        encodings = ("utf-8-sig", "cp1256", "cp1252", "latin-1")

    for encoding in encodings:
        try:
            # ERROR_PASS silently discards malformed cues and their dialogue.
            return pysrt.open(str(path), encoding=encoding, error_handling=pysrt.ERROR_RAISE)
        except UnicodeDecodeError:
            continue
        except pysrt.Error as exc:
            raise RuntimeError("Invalid SRT structure; check cue numbers and timestamps.") from exc

    raise RuntimeError("Invalid SRT text encoding.")


def time_from_ms(milliseconds: int) -> pysrt.SubRipTime:
    return pysrt.SubRipTime(milliseconds=max(0, milliseconds))


def credit_watermark_cues(subs) -> list[pysrt.SubRipItem]:
    if not subs:
        return []

    first_start_ms = max(0, subs[0].start.ordinal)
    last_end_ms = max(0, max(sub.end.ordinal for sub in subs))
    cues = []

    if first_start_ms >= WATERMARK_MIN_FIRST_START_MS:
        start_duration_ms = min(WATERMARK_DURATION_MS, max(0, first_start_ms - WATERMARK_TIMING_GAP_MS))

        if start_duration_ms > 0:
            cues.append(
                pysrt.SubRipItem(
                    start=time_from_ms(0),
                    end=time_from_ms(start_duration_ms),
                    text=WATERMARK_TEXT,
                )
            )

    end_start_ms = last_end_ms + WATERMARK_END_GAP_MS
    cues.append(
        pysrt.SubRipItem(
            start=time_from_ms(end_start_ms),
            end=time_from_ms(end_start_ms + WATERMARK_DURATION_MS),
            text=WATERMARK_TEXT,
        )
    )

    return cues


def with_credit_watermarks(subs):
    if not subs:
        return pysrt.SubRipFile()

    watermarked = pysrt.SubRipFile()
    start_cues = credit_watermark_cues(subs)

    if len(start_cues) == 2:
        watermarked.append(start_cues[0])

    for sub in subs:
        watermarked.append(copy(sub))

    watermarked.append(start_cues[-1])

    for index, sub in enumerate(watermarked, start=1):
        sub.index = index

    return watermarked


def write_srt(subs, path: Path, *, overwrite: bool = True, add_credit: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    output_subs = with_credit_watermarks(subs) if add_credit else subs

    try:
        output_subs.save(str(temp_path), encoding="utf-8")
        with temp_path.open("rb+") as output:
            os.fsync(output.fileno())
        if overwrite:
            os.replace(temp_path, path)
        else:
            # Link publication is atomic and refuses an existing destination,
            # even if another process creates it after the initial check.
            os.link(temp_path, path)
        if hasattr(os, "O_DIRECTORY"):
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        temp_path.unlink(missing_ok=True)


def repair_persian_italic_markup(text: str) -> str:
    """Restore a missing tag delimiter without changing Persian dialogue."""
    return re.sub(r"<(i|b|u)(?=[\u0600-\u06ff])", r"<\1>", text)


def clean_subtitle_text(text: str) -> str:
    text = repair_persian_italic_markup(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_punctuation_spacing(text: str, language: str | None = None) -> str:
    profile = text_profile(text, language)
    code = language_code(language)

    lines = []
    for line in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()
        line = re.sub(r"\s+([,.;:!?،؛؟。！？、])", r"\1", line)

        if profile == "rtl":
            line = line.replace("?", "؟").replace(";", "؛")

            if code in {"fa", "ar", "ur"}:
                line = re.sub(r"(?<=\S),(?=\s|$)", "،", line)

        if profile == "cjk":
            line = re.sub(r"([\u3040-\u30FF\u3400-\u4DBF\u4E00-\u9FFF])\s+([\u3040-\u30FF\u3400-\u4DBF\u4E00-\u9FFF])", r"\1\2", line)
            line = re.sub(r"\s*([。！？、，；：])\s*", r"\1", line)

        lines.append(line)

    return "\n".join(lines).strip()


def apply_rtl_direction_marks(text: str, language: str | None = None) -> str:
    if text_profile(text, language) != "rtl":
        return text

    marked_lines = []

    for line in text.split("\n"):
        cleaned = line.strip()

        if not cleaned:
            continue

        if cleaned.startswith(RTL_EMBEDDING_MARK) and cleaned.endswith(POP_DIRECTIONAL_FORMATTING):
            marked_lines.append(cleaned)
        else:
            marked_lines.append(f"{RTL_EMBEDDING_MARK}{cleaned}{POP_DIRECTIONAL_FORMATTING}")

    return "\n".join(marked_lines)


def subtitle_line_limit(language: str | None, text: str = "") -> int:
    profile = text_profile(text, language)

    if profile == "cjk":
        return 22

    if profile == "rtl":
        return 38

    if profile == "devanagari":
        return 36

    return 42


def split_cjk_line(line: str, limit: int) -> list[str]:
    if len(line) <= limit:
        return [line]

    parts = []
    current = ""

    for chunk in CJK_BREAK_RE.split(line):
        if not chunk:
            continue

        candidate = current + chunk

        if current and len(candidate) > limit:
            parts.append(current)
            current = chunk
        else:
            current = candidate

    if current:
        parts.append(current)

    wrapped = []
    for part in parts:
        while len(part) > limit:
            wrapped.append(part[:limit])
            part = part[limit:]

        if part:
            wrapped.append(part)

    return wrapped


def split_spaced_line(line: str, limit: int) -> list[str]:
    if len(line) <= limit:
        return [line]

    words = line.split(" ")
    wrapped = []
    current = ""

    for word in words:
        if len(word) > limit:
            if current:
                wrapped.append(current)
                current = ""

            while len(word) > limit:
                wrapped.append(word[:limit])
                word = word[limit:]

            if word:
                current = word
            continue

        if not current:
            current = word
            continue

        candidate = f"{current} {word}"

        if len(candidate) <= limit:
            current = candidate
        else:
            wrapped.append(current)
            current = word

    if current:
        wrapped.append(current)

    return wrapped


def wrap_subtitle_text(text: str, language: str | None = None) -> str:
    text = repair_persian_italic_markup(text)
    tags = {}

    def protect_tag(match):
        token = chr(0xF0000 + len(tags))
        tags[token] = match.group()
        return token

    protected = re.sub(r"<[^>\n]+>", protect_tag, text)
    cleaned = normalize_punctuation_spacing(clean_subtitle_text(protected), language)

    if not cleaned:
        return ""

    limit = subtitle_line_limit(language, cleaned)
    profile = text_profile(cleaned, language)
    wrapped_lines = []

    for line in cleaned.split("\n"):
        if not line:
            continue

        if profile == "cjk":
            wrapped_lines.extend(split_cjk_line(line, limit))
        else:
            wrapped_lines.extend(split_spaced_line(line, limit))

    wrapped = "\n".join(wrapped_lines)
    for token, tag in tags.items():
        wrapped = wrapped.replace(token, tag)
    return apply_rtl_direction_marks(wrapped, language)


def make_output_filename(input_filename: str, target_language: str) -> str:
    """
    Examples:
    Movie.en.srt       -> Movie.fa.srt
    Movie.eng.srt      -> Movie.fa.srt
    Movie.english.srt  -> Movie.fa.srt
    Movie.srt          -> Movie.fa.srt
    """

    input_path = Path(input_filename)
    stem = input_path.stem

    parts = stem.split(".")

    # Remove one or more language suffixes before .srt
    # Example: Movie.en.srt -> Movie
    # Example: Movie.english.srt -> Movie
    while parts and parts[-1].strip().lower() in KNOWN_LANGUAGE_SUFFIXES:
        parts = parts[:-1]

    clean_stem = ".".join(parts).strip()

    if not clean_stem:
        clean_stem = input_path.stem

    code = language_code(target_language)

    return f"{clean_stem}.{code}.srt"


def batch_subtitles(
    subs,
    batch_size: int,
    max_chars: int,
    language: str | None = None,
    max_estimated_tokens: int | None = None,
    context_cues: int = 0,
    context_gap_seconds: int = 15,
):
    batch = []
    char_count = 0
    token_count = 0

    if max_estimated_tokens is None:
        max_estimated_tokens = max(500, min(6000, max_chars // 2))

    source_cues = list(subs)
    for position, sub in enumerate(source_cues):
        text = clean_subtitle_text(sub.text)

        if not text:
            continue

        item = {
            "index": sub.index,
            "text": text,
        }

        if context_cues:
            # Stop at scene-sized gaps; do not borrow unrelated dialogue.
            before = []
            previous_start = sub.start.ordinal
            for cue in reversed(source_cues[max(0, position-context_cues):position]):
                if previous_start - cue.end.ordinal > context_gap_seconds * 1000:
                    break
                before.insert(0, clean_subtitle_text(cue.text)[:500])
                previous_start = cue.start.ordinal
            after = []
            previous_end = sub.end.ordinal
            for cue in source_cues[position+1:position+1+context_cues]:
                if cue.start.ordinal - previous_end > context_gap_seconds * 1000:
                    break
                after.append(clean_subtitle_text(cue.text)[:500])
                previous_end = cue.end.ordinal
            item["context_before"] = before
            item["context_after"] = after

        context_text = " ".join(item.get("context_before", []) + item.get("context_after", []))
        estimated_chars = len(text) + len(context_text)
        estimated_tokens = estimate_subtitle_tokens(text, language) + estimate_subtitle_tokens(context_text, language)

        should_yield = (
            len(batch) >= batch_size
            or char_count + estimated_chars > max_chars
            or token_count + estimated_tokens > max_estimated_tokens
        )

        if batch and should_yield:
            yield batch
            batch = []
            char_count = 0
            token_count = 0

        batch.append(item)
        char_count += estimated_chars
        token_count += estimated_tokens

    if batch:
        yield batch
