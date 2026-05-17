import re
from pathlib import Path

from app.models import SUPPORTED_LANGUAGES, language_name_from_suffix


SCRIPT_LANGUAGES = [
    ("Korean", r"[\uAC00-\uD7AF]"),
    ("Japanese", r"[\u3040-\u30FF]"),
    ("Chinese", r"[\u4E00-\u9FFF]"),
    ("Russian", r"[\u0400-\u04FF]"),
]

PERSIAN_SPECIFIC_RE = re.compile(r"[\u067E\u0686\u0698\u06AF\u06A9\u200C\u06CC]")
ARABIC_SCRIPT_RE = re.compile(r"[\u0600-\u06FF]")

LATIN_PROFILES = {
    "English": {
        "the", "and", "you", "that", "what", "for", "with", "this", "have",
        "not", "are", "was", "your", "just", "like", "know", "from", "they",
        "we", "he", "she", "it", "is", "to", "of", "in", "on", "me", "my",
    },
    "Spanish": {
        "el", "la", "los", "las", "que", "de", "del", "y", "en", "un",
        "una", "por", "para", "con", "no", "es", "estoy", "esta", "estas",
        "como", "pero", "si", "yo", "tu", "usted", "porque", "bien",
    },
    "French": {
        "le", "la", "les", "des", "de", "du", "et", "est", "que", "qui",
        "pas", "pour", "vous", "nous", "avec", "une", "un", "dans", "ce",
        "je", "tu", "il", "elle", "mais", "oui", "non", "bien",
    },
    "German": {
        "der", "die", "das", "und", "ist", "nicht", "ich", "du", "sie",
        "wir", "ein", "eine", "mit", "auf", "f\u00fcr", "den", "dem", "zu",
        "was", "wie", "aber", "ja", "nein", "haben", "sein",
    },
    "Italian": {
        "il", "lo", "la", "gli", "le", "di", "che", "e", "\u00e8", "non",
        "per", "con", "un", "una", "sono", "io", "tu", "lui", "lei",
        "noi", "voi", "ma", "si", "come", "bene",
    },
    "Portuguese": {
        "o", "a", "os", "as", "que", "de", "do", "da", "e", "em", "um",
        "uma", "n\u00e3o", "para", "com", "por", "eu", "voc\u00ea", "ele", "ela",
        "n\u00f3s", "mas", "sim", "como", "bem",
    },
    "Turkish": {
        "bir", "ve", "bu", "ne", "ben", "sen", "o", "biz", "siz", "onlar",
        "de", "da", "i\u00e7in", "ile", "mi", "m\u0131", "\u00e7ok", "var", "yok",
        "ama", "evet", "hay\u0131r", "gibi",
    },
}

def visible_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\{\\.*?\}", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def detect_from_filename(filename: str) -> str | None:
    parts = Path(filename).stem.lower().split(".")

    for part in reversed(parts):
        language = language_name_from_suffix(part)

        if language:
            return language

    return None


def detect_from_text(text: str) -> str | None:
    cleaned = visible_text(text)

    if not cleaned:
        return None

    persian_specific = len(PERSIAN_SPECIFIC_RE.findall(cleaned))
    arabic_script = len(ARABIC_SCRIPT_RE.findall(cleaned))

    if arabic_script >= 8:
        if persian_specific / arabic_script >= 0.08:
            return "Persian"
        return "Arabic"

    for language, pattern in SCRIPT_LANGUAGES:
        if len(re.findall(pattern, cleaned)) >= 8:
            return language

    lowered = cleaned.lower()
    words = re.findall(r"[a-z\u00C0-\u00FF]+", lowered)

    if not words:
        return None

    scores = {
        language: sum(1 for word in words if word in profile)
        for language, profile in LATIN_PROFILES.items()
    }

    if re.search(r"[\u00E7\u011F\u0131\u00F6\u015F\u00FC]", lowered):
        scores["Turkish"] += 4
    if re.search(r"[\u00F1\u00BF\u00A1]", lowered):
        scores["Spanish"] += 3
    if re.search(r"[\u00E0\u00E2\u00E7\u00E9\u00E8\u00EA\u00EB\u00EE\u00EF\u00F4\u00F9\u00FB\u00FC\u00FF\u0153]", lowered):
        scores["French"] += 2
    if re.search(r"[\u00E4\u00F6\u00FC\u00DF]", lowered):
        scores["German"] += 3
    if re.search(r"[\u00E3\u00F5\u00E1\u00E2\u00EA\u00F4\u00E7]", lowered):
        scores["Portuguese"] += 2

    best_language, best_score = max(scores.items(), key=lambda item: item[1])

    if best_score >= 3:
        return best_language

    return None


def detect_subtitle_language(subs, filename: str | None = None) -> str:
    sample_parts = []

    for sub in subs:
        text = visible_text(sub.text)

        if text:
            sample_parts.append(text)

        if sum(len(part) for part in sample_parts) >= 6000:
            break

    detected = detect_from_text(" ".join(sample_parts))

    if detected in SUPPORTED_LANGUAGES:
        return detected

    if filename:
        detected = detect_from_filename(filename)

        if detected in SUPPORTED_LANGUAGES:
            return detected

    return "Unknown"
