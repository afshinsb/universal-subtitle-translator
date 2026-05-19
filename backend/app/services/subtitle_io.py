from pathlib import Path
import re
import os
from uuid import uuid4

import pysrt

from app.models import KNOWN_LANGUAGE_SUFFIXES, language_code

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
    encodings = ("utf-8", "utf-8-sig", "cp1256", "cp1252", "latin-1")

    for encoding in encodings:
        try:
            return pysrt.open(str(path), encoding=encoding)
        except UnicodeDecodeError:
            continue

    return pysrt.open(str(path), encoding="latin-1")


def write_srt(subs, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")

    try:
        subs.save(str(temp_path), encoding="utf-8")
        os.replace(temp_path, path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def clean_subtitle_text(text: str) -> str:
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
    cleaned = normalize_punctuation_spacing(clean_subtitle_text(text), language)

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

    return apply_rtl_direction_marks("\n".join(wrapped_lines), language)


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
):
    batch = []
    char_count = 0
    token_count = 0

    if max_estimated_tokens is None:
        max_estimated_tokens = max(500, min(6000, max_chars // 2))

    for sub in subs:
        text = clean_subtitle_text(sub.text)

        if not text:
            continue

        item = {
            "index": sub.index,
            "text": text,
        }

        estimated_chars = len(text)
        estimated_tokens = estimate_subtitle_tokens(text, language)

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
