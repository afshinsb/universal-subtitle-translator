import re


LANGUAGE_CODES = {
    "persian": "fa",
    "farsi": "fa",
    "fas": "fa",
    "per": "fa",
    "fa": "fa",

    "english": "en",
    "eng": "en",
    "en": "en",

    "arabic": "ar",
    "ara": "ar",
    "ar": "ar",

    "turkish": "tr",
    "tur": "tr",
    "tr": "tr",

    "spanish": "es",
    "spa": "es",
    "es": "es",

    "french": "fr",
    "fre": "fr",
    "fra": "fr",
    "fr": "fr",

    "german": "de",
    "ger": "de",
    "deu": "de",
    "de": "de",

    "italian": "it",
    "ita": "it",
    "it": "it",

    "portuguese": "pt",
    "por": "pt",
    "pt": "pt",

    "russian": "ru",
    "rus": "ru",
    "ru": "ru",

    "japanese": "ja",
    "jpn": "ja",
    "ja": "ja",

    "korean": "ko",
    "kor": "ko",
    "ko": "ko",

    "chinese": "zh",
    "chi": "zh",
    "zho": "zh",
    "zh": "zh",
}

LANGUAGE_NAMES_BY_CODE = {
    "fa": "Persian",
    "en": "English",
    "ar": "Arabic",
    "tr": "Turkish",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "ru": "Russian",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
}

PERSIAN_CHAR_RE = re.compile(r"[\u0600-\u06FF]")

KNOWN_LANGUAGE_SUFFIXES = {
    "en", "eng", "english",
    "fa", "fas", "per", "persian", "farsi",
    "ar", "ara", "arabic",
    "tr", "tur", "turkish",
    "es", "spa", "spanish",
    "fr", "fre", "fra", "french",
    "de", "ger", "deu", "german",
    "it", "ita", "italian",
    "pt", "por", "portuguese",
    "ru", "rus", "russian",
    "ja", "jpn", "japanese",
    "ko", "kor", "korean",
    "zh", "chi", "zho", "chinese",
}

SUPPORTED_LANGUAGES = [
    "Persian",
    "English",
    "Arabic",
    "Turkish",
    "Spanish",
    "French",
    "German",
    "Italian",
    "Portuguese",
    "Russian",
    "Japanese",
    "Korean",
    "Chinese",
]

SUPPORTED_STYLES = [
    "natural_conversational",
    "formal",
    "literal",
    "subtitle_friendly",
]


def normalize_language(language: str) -> str:
    return language.strip().lower()


def language_code(language: str | None) -> str:
    if not language:
        return ""

    normalized = normalize_language(language)
    return LANGUAGE_CODES.get(normalized, normalized[:2])


def known_language_code(language: str | None) -> str | None:
    code = language_code(language)

    if code in LANGUAGE_NAMES_BY_CODE:
        return code

    return None


def language_name_from_suffix(suffix: str | None) -> str | None:
    code = known_language_code(suffix)

    if not code:
        return None

    return LANGUAGE_NAMES_BY_CODE[code]


def has_persian_characters(text: str) -> bool:
    return bool(PERSIAN_CHAR_RE.search(text))


def is_persian_language(language: str | None) -> bool:
    return language_code(language) == "fa"
