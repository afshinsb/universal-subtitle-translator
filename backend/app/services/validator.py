from app.models import has_persian_characters, is_persian_language


def validate_subtitles(subs, target_language: str) -> dict:
    total = len(subs)
    non_empty = 0
    empty = 0
    likely_untranslated = 0

    for sub in subs:
        text = sub.text.strip()

        if not text:
            empty += 1
            continue

        non_empty += 1

        if is_persian_language(target_language):
            if not has_persian_characters(text):
                likely_untranslated += 1

    warnings = []

    if empty > 0:
        warnings.append(f"{empty} subtitle cues are empty.")

    if likely_untranslated > 0:
        warnings.append(f"{likely_untranslated} subtitle cues may still be untranslated.")

    passed = True

    if is_persian_language(target_language):
        if non_empty > 0 and likely_untranslated / non_empty > 0.20:
            passed = False

    return {
        "passed": passed,
        "total": total,
        "non_empty": non_empty,
        "empty": empty,
        "likely_untranslated": likely_untranslated,
        "warnings": warnings,
    }
