from fastapi import HTTPException

from app.models import SUPPORTED_LANGUAGES, SUPPORTED_STYLES


def validate_language(language: str) -> str:
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail=f"Unsupported language: {language}")

    return language


def validate_style(style: str) -> str:
    if style not in SUPPORTED_STYLES:
        raise HTTPException(status_code=400, detail=f"Unsupported style: {style}")

    return style


def parse_checkbox(value: bool | str | None) -> bool:
    if isinstance(value, bool):
        return value

    if value is None:
        return False

    return value.strip().lower() in {"1", "true", "yes", "on"}
