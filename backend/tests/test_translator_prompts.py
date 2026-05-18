from app.services.translator import (
    build_batch_prompt,
    build_language_style_guidance,
)


def sample_batch():
    return [{"index": 1, "text": "Hello there."}]


def test_language_style_guidance_is_specific_for_spanish_subtitle_friendly():
    guidance = build_language_style_guidance("Spanish", "subtitle_friendly")

    assert "Spanish subtitle" in guidance
    assert "short sentences" in guidance


def test_universal_prompt_includes_language_style_guidance():
    prompt = build_batch_prompt(
        batch=sample_batch(),
        target_language="Japanese",
        style="formal",
        source_language="English",
    )

    assert "Target: Japanese." in prompt
    assert "Language/style guidance:" in prompt
    assert "formal Japanese" in prompt
    assert "politeness" in prompt


def test_persian_prompt_includes_persian_script_guidance():
    prompt = build_batch_prompt(
        batch=sample_batch(),
        target_language="Persian",
        style="literal",
        source_language="English",
    )

    assert "Language/style guidance:" in prompt
    assert "Persian script" in prompt
    assert "BEGIN[1]" in prompt


def test_unknown_language_gets_safe_fallback_guidance():
    guidance = build_language_style_guidance("Esperanto", "formal")

    assert "Esperanto" in guidance
    assert "concise and readable" in guidance
