import re
from dataclasses import dataclass

from openai import OpenAI

from app.config import settings
from app.models import has_persian_characters, is_persian_language

LINE_BREAK_TOKEN = "<LB>"


@dataclass
class TranslationResult:
    translations: dict[int, str]
    input_tokens: int
    output_tokens: int
    total_tokens: int
    raw_output: str
    attempts: int = 1
    retry_attempted: bool = False
    retry_reason: str | None = None


def get_openai_client() -> OpenAI:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is missing. Add it to your .env file.")

    return OpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.openai_timeout_seconds,
    )


def build_style_instruction(style: str, target_language: str) -> str:
    if style == "formal":
        return f"Use formal, polished {target_language}."
    if style == "literal":
        return "Translate accurately and stay close to the original meaning."
    if style == "subtitle_friendly":
        return f"Use short, readable subtitle-friendly {target_language}."
    return f"Use natural, idiomatic {target_language} dialogue with the right tone."


def build_persian_style_instruction(style: str) -> str:
    if style == "formal":
        return "فارسی رسمی، روان و پرداخت‌شده بنویس."
    if style == "literal":
        return "دقیق و نزدیک به معنی اصلی ترجمه کن."
    if style == "subtitle_friendly":
        return "کوتاه و خوانا برای زیرنویس بنویس."
    return "فارسی محاوره‌ای طبیعی با لحن درست بنویس."


def build_format_instruction(target_language: str) -> str:
    if is_persian_language(target_language):
        return (
            "برای چندخطی کردن فقط از توکن <LB> استفاده کن. خط‌ها را کوتاه و خوانا نگه دار. "
            "فاصله‌گذاری علائم نگارشی فارسی/عربی را طبیعی نگه دار و از شکستن کلمات خودداری کن."
        )

    return (
        "For multi-line subtitles, use only the <LB> token. Keep lines short and readable. "
        "For Chinese, Japanese, and Korean, do not insert unnatural spaces between characters. "
        "For Arabic, Persian, Hebrew, Urdu, and other RTL text, keep natural punctuation spacing. "
        "Never change indexes or timing; translate text only."
    )


def build_persian_prompt(
    joined_blocks: str,
    source_instruction: str,
    style_instruction: str,
    format_instruction: str,
    force_persian: bool,
) -> str:
    retry_instruction = ""

    if force_persian:
        retry_instruction = (
            "\nترجمه قبلی به اندازه کافی فارسی نبود؛ دیالوگ معمولی باید با خط فارسی باشد."
        )

    return f"""
تو مترجم حرفه‌ای زیرنویس هستی.
{source_instruction}
هدف: فارسی محاوره‌ای با خط فارسی.
لحن: کوتاه، دقیق، امانت‌دار، طبیعی و بدون سانسور. {style_instruction}
قالب‌بندی: {format_instruction}

قوانین سخت: هر آیتم BEGIN/END را فقط بر اساس متن همان آیتم ترجمه کن. متن آیتم قبلی/بعدی را وارد نکن؛ ادغام، جابه‌جایی، حذف یا اضافه کردن آیتم ممنوع. اگر متن ناقص است همان تکه را ترجمه کن و کامل‌سازی نکن. اسم‌ها، برندها، کدها و اصطلاحات فنی فقط وقتی طبیعی است انگلیسی بمانند. اگر لازم شد چندخطی شود، به جای خط جدید داخل متن از توکن {LINE_BREAK_TOKEN} استفاده کن. خروجی فقط بلوک‌های BEGIN[i] ... END[i] با همان شماره‌ها باشد؛ هیچ توضیحی بیرون بلوک‌ها ننویس.{retry_instruction}

زیرنویس‌ها:

{joined_blocks}
""".strip()


def build_universal_prompt(
    joined_blocks: str,
    target_language: str,
    source_instruction: str,
    style_instruction: str,
    format_instruction: str,
) -> str:
    return f"""
You are a professional subtitle translator.
{source_instruction}
Target: {target_language}.
Style: short, accurate, faithful, natural, uncensored dialogue. {style_instruction}
Formatting: {format_instruction}

Strict rules: translate each BEGIN/END item independently using only that item's text. Never borrow from neighboring items, merge, move, skip, or add items. If an item is incomplete, translate only that fragment; do not complete it. Keep names, numbers, tags, and punctuation intent. If multiple subtitle lines are needed, use {LINE_BREAK_TOKEN} instead of a line break inside the translated text. Return only BEGIN[i] ... END[i] blocks with the same indexes; no text outside blocks.

Subtitles:

{joined_blocks}
""".strip()


def build_batch_prompt(
    batch: list[dict],
    target_language: str,
    style: str,
    source_language: str = "Auto",
    force_persian: bool = False,
) -> str:
    if is_persian_language(target_language):
        style_instruction = build_persian_style_instruction(style)
    else:
        style_instruction = build_style_instruction(style, target_language)

    format_instruction = build_format_instruction(target_language)
    blocks = [
        f"BEGIN[{item['index']}]\n{item['text']}\nEND[{item['index']}]"
        for item in batch
    ]
    joined_blocks = "\n\n".join(blocks)

    if source_language and source_language not in {"Auto", "Unknown", "Detecting"}:
        english_source_instruction = f"Source appears to be {source_language}."
        persian_source_instruction = f"زبان مبدا احتمالا {source_language} است."
    else:
        english_source_instruction = "Detect the source language automatically."
        persian_source_instruction = "زبان مبدا را خودت تشخیص بده."

    if is_persian_language(target_language):
        return build_persian_prompt(
            joined_blocks=joined_blocks,
            source_instruction=persian_source_instruction,
            style_instruction=style_instruction,
            format_instruction=format_instruction,
            force_persian=force_persian,
        )

    return build_universal_prompt(
        joined_blocks=joined_blocks,
        target_language=target_language,
        source_instruction=english_source_instruction,
        style_instruction=style_instruction,
        format_instruction=format_instruction,
    )


def parse_translated_blocks(text: str) -> dict[int, str]:
    pattern = r"BEGIN\[(\d+)\]\s*(.*?)\s*END\[\1\]"
    matches = re.findall(pattern, text, flags=re.DOTALL)

    result = {}

    for index_text, translated_text in matches:
        index = int(index_text)
        result[index] = translated_text.strip().replace(LINE_BREAK_TOKEN, "\n")

    return result


def call_openai(prompt: str) -> TranslationResult:
    client = get_openai_client()

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {
                "role": "system",
                "content": "You translate subtitles. You must obey the requested target language and block format exactly.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=0.1,
    )

    output_text = response.choices[0].message.content or ""
    parsed = parse_translated_blocks(output_text)

    usage = getattr(response, "usage", None)

    input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
    total_tokens = getattr(usage, "total_tokens", 0) if usage else 0

    return TranslationResult(
        translations=parsed,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        raw_output=output_text,
    )


def count_non_persian_outputs(translations: dict[int, str], target_language: str) -> int:
    if not is_persian_language(target_language):
        return 0

    count = 0

    for text in translations.values():
        cleaned = text.strip()

        if cleaned and not has_persian_characters(cleaned):
            count += 1

    return count


def mark_retry(
    result: TranslationResult,
    attempts: int,
    retry_reason: str,
) -> TranslationResult:
    result.attempts = attempts
    result.retry_attempted = attempts > 1
    result.retry_reason = retry_reason
    return result


def translate_batch(
    batch: list[dict],
    target_language: str,
    style: str,
    source_language: str = "Auto",
) -> TranslationResult:
    prompt = build_batch_prompt(
        batch=batch,
        target_language=target_language,
        style=style,
        source_language=source_language,
        force_persian=False,
    )

    result = call_openai(prompt)

    if is_persian_language(target_language):
        non_persian_count = count_non_persian_outputs(result.translations, target_language)

        if result.translations and non_persian_count / len(result.translations) > 0.30:
            retry_reason = (
                f"Persian validation retry: {non_persian_count}/{len(result.translations)} "
                "outputs did not contain Persian-script characters."
            )
            retry_prompt = build_batch_prompt(
                batch=batch,
                target_language=target_language,
                style=style,
                source_language=source_language,
                force_persian=True,
            )

            retry_result = call_openai(retry_prompt)

            retry_non_persian_count = count_non_persian_outputs(
                retry_result.translations,
                target_language,
            )

            if retry_non_persian_count <= non_persian_count:
                return mark_retry(retry_result, attempts=2, retry_reason=retry_reason)

            return mark_retry(result, attempts=2, retry_reason=f"{retry_reason} Retry did not improve output.")

    return result
