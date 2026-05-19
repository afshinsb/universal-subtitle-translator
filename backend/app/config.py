import os
import shutil
import tempfile
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = BASE_DIR / ".env"

load_dotenv(ENV_PATH)


PLACEHOLDER_VALUES = {
    "",
    "changeme",
    "change_me",
    "change-me",
    "placeholder",
    "your-api-key",
    "your_api_key",
    "your_openai_api_key",
    "replace_your_api_with_this_text",
    "replace_your_api_key_here",
    "replace_with_your_openai_api_key",
    "replace_your_password_with_this_text",
    "replace_your_session_secret_with_this_text",
    "sk-your-api-key",
    "sk-...",
}

SRT_BATCH_SIZE_MIN = 1
SRT_BATCH_SIZE_MAX = 200
SRT_BATCH_SIZE_RECOMMENDED_MAX = 100
SRT_MAX_CHARS_MIN = 500
SRT_MAX_CHARS_MAX = 100000
SRT_MAX_CHARS_RECOMMENDED_MIN = 2000
SRT_MAX_CHARS_RECOMMENDED_MAX = 30000
DEFAULT_SESSION_SECRET = "default-insecure-session-secret-change-before-release"


def env_value(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip()


def parse_int_env(name: str, default: int) -> int:
    value = env_value(name)

    if value in {None, ""}:
        return default

    try:
        return int(value)
    except ValueError:
        return default


def parse_float_env(name: str, default: float) -> float:
    value = env_value(name)

    if value in {None, ""}:
        return default

    try:
        return float(value)
    except ValueError:
        return default


def parse_bool_env(name: str, default: bool = False) -> bool:
    value = env_value(name)

    if value in {None, ""}:
        return default

    return value.lower() in {"1", "true", "yes", "on"}


class Settings:
    app_name: str = env_value("APP_NAME", "Universal Subtitle Translator") or "Universal Subtitle Translator"
    app_version: str = env_value("APP_VERSION", "1.8.0") or "1.8.0"
    demo_mode: bool = parse_bool_env("DEMO_MODE", False)
    app_host: str = env_value("APP_HOST", "0.0.0.0") or "0.0.0.0"
    app_port: int = parse_int_env("APP_PORT", 2288)

    project_author: str = env_value("PROJECT_AUTHOR", "Afshin Saberi") or "Afshin Saberi"
    project_year: str = env_value("PROJECT_YEAR", "2026") or "2026"
    project_license: str = env_value("PROJECT_LICENSE", "MIT") or "MIT"
    project_github_handle: str = env_value("PROJECT_GITHUB_HANDLE", "afshinsb") or "afshinsb"
    project_github_url: str = env_value(
        "PROJECT_GITHUB_URL",
        "https://github.com/afshinsb/universal-subtitle-translator",
    ) or "https://github.com/afshinsb/universal-subtitle-translator"
    project_issue_url: str = env_value(
        "PROJECT_ISSUE_URL",
        f"{project_github_url}/issues",
    ) or f"{project_github_url}/issues"
    project_about_url: str = env_value("PROJECT_ABOUT_URL", "/about") or "/about"

    openai_api_key: str | None = env_value("OPENAI_API_KEY")
    openai_model: str = env_value("OPENAI_MODEL", "gpt-4o-mini") or ""
    auth_enabled: bool = parse_bool_env("AUTH_ENABLED", True)
    admin_username: str = env_value("ADMIN_USERNAME", "admin") or "admin"
    admin_password: str | None = env_value("ADMIN_PASSWORD", "admin") or "admin"
    session_secret: str | None = env_value("SESSION_SECRET", DEFAULT_SESSION_SECRET) or DEFAULT_SESSION_SECRET

    data_dir: Path = Path(env_value("DATA_DIR", str(BASE_DIR / "data")) or str(BASE_DIR / "data"))
    upload_dir: Path = Path(env_value("UPLOAD_DIR", str(BASE_DIR / "data" / "uploads")) or str(BASE_DIR / "data" / "uploads"))
    output_dir: Path = Path(env_value("OUTPUT_DIR", str(BASE_DIR / "data" / "outputs")) or str(BASE_DIR / "data" / "outputs"))
    temp_dir: Path = Path(env_value("TEMP_DIR", str(BASE_DIR / "data" / "temp")) or str(BASE_DIR / "data" / "temp"))
    database_path: Path = Path(env_value("DATABASE_PATH", str(BASE_DIR / "data" / "app.db")) or str(BASE_DIR / "data" / "app.db"))
    media_root: Path | None = (
        Path(env_value("MEDIA_ROOT") or "").resolve()
        if env_value("MEDIA_ROOT")
        else None
    )

    default_source_language: str = env_value("DEFAULT_SOURCE_LANGUAGE", "Auto") or "Auto"
    default_target_language: str = env_value("DEFAULT_TARGET_LANGUAGE", "Persian") or "Persian"
    default_style: str = env_value("DEFAULT_STYLE", "natural_conversational") or "natural_conversational"

    srt_batch_size: int = parse_int_env("SRT_BATCH_SIZE", 40)
    srt_max_chars: int = parse_int_env("SRT_MAX_CHARS", 12000)
    batch_file_concurrency: int = parse_int_env("BATCH_FILE_CONCURRENCY", 10)
    max_upload_mb: int = parse_int_env("MAX_UPLOAD_MB", 10240)
    ffmpeg_timeout_seconds: int = parse_int_env("FFMPEG_TIMEOUT_SECONDS", 120)
    openai_timeout_seconds: int = parse_int_env("OPENAI_TIMEOUT_SECONDS", 120)
    cancel_timeout_seconds: int = parse_int_env("CANCEL_TIMEOUT_SECONDS", 30)
    openai_input_cost_per_1m: float = parse_float_env("OPENAI_INPUT_COST_PER_1M", 0)
    openai_output_cost_per_1m: float = parse_float_env("OPENAI_OUTPUT_COST_PER_1M", 0)


settings = Settings()
OPENAI_API_TEST_RESULT: dict[str, str | bool] = {
    "status": "not_run",
    "ok": True,
    "message": "OpenAI API key has not been tested in this process.",
    "fix": "No action needed.",
}


def project_footer() -> dict:
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "author": settings.project_author,
        "year": settings.project_year,
        "license": settings.project_license,
        "github_handle": settings.project_github_handle,
        "github_url": settings.project_github_url,
        "issue_url": settings.project_issue_url,
        "about_url": settings.project_about_url,
    }


def raw_setting(name: str) -> str | None:
    value = os.getenv(name)

    if value is None:
        return None

    return value.strip()


def is_placeholder(value: str | None) -> bool:
    if value is None:
        return False

    normalized = value.strip().lower()
    return (
        normalized in PLACEHOLDER_VALUES
        or normalized.startswith("your_")
        or normalized.startswith("your-")
        or normalized.startswith("replace_")
        or normalized.startswith("replace-")
    )


def openai_api_key_state() -> tuple[bool, str, str, str]:
    key = settings.openai_api_key

    if key is None:
        return (
            False,
            "missing",
            "OpenAI API key is missing.",
            "Add OPENAI_API_KEY to your .env file, then restart the app.",
        )

    if not key.strip():
        return (
            False,
            "blank",
            "OpenAI API key is blank.",
            "Set OPENAI_API_KEY in your .env file, then restart the app.",
        )

    if is_placeholder(key):
        return (
            False,
            "placeholder",
            "OpenAI API key still looks like a placeholder.",
            "Replace OPENAI_API_KEY in your .env file with your real key, then restart the app.",
        )

    if not (key.startswith("sk-") or key.startswith("sk-proj-")) or len(key) < 20:
        return (
            False,
            "invalid_format",
            "OpenAI API key format looks invalid.",
            "Check OPENAI_API_KEY in your .env file. It should be your OpenAI key, then restart the app.",
        )

    return (
        True,
        "configured",
        "OpenAI API key is configured.",
        "No action needed.",
    )


def auth_config_checks() -> list[dict]:
    if not settings.auth_enabled:
        return [
            {
                "id": "auth_enabled",
                "label": "Authentication",
                "ok": True,
                "severity": "ok",
                "blocking": False,
                "message": "Authentication is disabled.",
                "fix": "Remove AUTH_ENABLED=false or set AUTH_ENABLED=true in .env to require login.",
                "value": "disabled",
            }
        ]

    checks = [
        {
            "id": "auth_enabled",
            "label": "Authentication",
            "ok": True,
            "severity": "ok",
            "blocking": False,
            "message": "Authentication is enabled.",
            "fix": "No action needed.",
            "value": "enabled",
        }
    ]

    username_ok = bool(settings.admin_username) and not is_placeholder(settings.admin_username)
    checks.append(
        {
            "id": "admin_username",
            "label": "Admin username",
            "ok": username_ok,
            "severity": "ok" if username_ok else "error",
            "blocking": not username_ok,
            "message": "ADMIN_USERNAME is configured." if username_ok else "ADMIN_USERNAME is missing or still looks like a placeholder.",
            "fix": "No action needed." if username_ok else "Set ADMIN_USERNAME in .env, then restart the app.",
            "value": "configured" if username_ok else "missing",
        }
    )

    password_is_default = settings.admin_password == "admin"
    password_ok = bool(settings.admin_password) and not is_placeholder(settings.admin_password)
    checks.append(
        {
            "id": "admin_password",
            "label": "Admin password",
            "ok": password_ok and not password_is_default,
            "severity": "warning" if password_ok and password_is_default else ("ok" if password_ok else "error"),
            "blocking": not password_ok,
            "message": (
                "ADMIN_PASSWORD is still set to the default password."
                if password_ok and password_is_default
                else ("ADMIN_PASSWORD is configured." if password_ok else "ADMIN_PASSWORD is missing or still looks like a placeholder.")
            ),
            "fix": (
                "Change ADMIN_PASSWORD in .env before exposing this app beyond your machine."
                if password_ok and password_is_default
                else ("No action needed." if password_ok else "Set ADMIN_PASSWORD in .env, then restart the app.")
            ),
            "value": "configured" if password_ok else "missing",
        }
    )

    secret_is_default = settings.session_secret == DEFAULT_SESSION_SECRET
    secret_ok = bool(settings.session_secret) and not is_placeholder(settings.session_secret) and len(settings.session_secret or "") >= 32
    checks.append(
        {
            "id": "session_secret",
            "label": "Session secret",
            "ok": secret_ok and not secret_is_default,
            "severity": "warning" if secret_ok and secret_is_default else ("ok" if secret_ok else "error"),
            "blocking": not secret_ok,
            "message": (
                "SESSION_SECRET is still using the default development value."
                if secret_ok and secret_is_default
                else ("SESSION_SECRET is configured." if secret_ok else "SESSION_SECRET is missing, too short, or still looks like a placeholder.")
            ),
            "fix": (
                "Set SESSION_SECRET to a random 32+ character value before exposing this app beyond your machine."
                if secret_ok and secret_is_default
                else ("No action needed." if secret_ok else "Set SESSION_SECRET to a random 32+ character value in .env, then restart the app.")
            ),
            "value": "configured" if secret_ok else "missing",
        }
    )

    return checks


def run_openai_api_key_test() -> None:
    api_key_ok, _, _, _ = openai_api_key_state()
    model_raw = raw_setting("OPENAI_MODEL")

    if not api_key_ok or model_raw in {None, ""} or is_placeholder(model_raw):
        OPENAI_API_TEST_RESULT.update(
            {
                "status": "skipped",
                "ok": True,
                "message": "OpenAI API test was skipped because required settings are not ready.",
                "fix": "Fix the OpenAI settings above, then restart the app.",
            }
        )
        return

    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.openai_api_key,
            timeout=min(max(settings.openai_timeout_seconds, 1), 10),
        )
        client.models.retrieve(settings.openai_model)
        OPENAI_API_TEST_RESULT.update(
            {
                "status": "passed",
                "ok": True,
                "message": "OpenAI API key and model test passed.",
                "fix": "No action needed.",
            }
        )
    except Exception:
        OPENAI_API_TEST_RESULT.update(
            {
                "status": "failed",
                "ok": False,
                "message": "API key is configured, but the test failed.",
                "fix": "Check the key, model name, billing/quota, or network access, then restart the app.",
            }
        )


def check_writable_path(path: Path, setting_name: str, label: str, *, directory: bool = True) -> dict:
    target = path if directory else path.parent

    try:
        target.mkdir(parents=True, exist_ok=True)

        if not target.is_dir():
            raise OSError(f"{target} is not a directory")

        with tempfile.NamedTemporaryFile(prefix=".ust-write-test-", dir=target, delete=True):
            pass

        return {
            "id": setting_name.lower(),
            "label": label,
            "ok": True,
            "severity": "ok",
            "blocking": False,
            "message": f"{label} is writable.",
            "fix": "No action needed.",
            "value": str(path),
        }
    except Exception:
        return {
            "id": setting_name.lower(),
            "label": label,
            "ok": False,
            "severity": "error",
            "blocking": True,
            "message": f"{label} is not writable.",
            "fix": f"Check {setting_name} in .env or Docker volume permissions, then restart the app.",
            "value": str(path),
        }


def check_int_setting(
    name: str,
    value: int,
    *,
    minimum: int,
    maximum: int,
    recommended_minimum: int | None = None,
    recommended_maximum: int | None = None,
) -> dict:
    raw = raw_setting(name)
    label = name.replace("_", " ")

    if raw not in {None, ""}:
        try:
            int(raw)
        except ValueError:
            return {
                "id": name.lower(),
                "label": label,
                "ok": False,
                "severity": "error",
                "blocking": True,
                "message": f"{name} must be a whole number.",
                "fix": f"Update {name} in .env, then restart the app.",
                "value": raw,
            }

    if value < minimum or value > maximum:
        return {
            "id": name.lower(),
            "label": label,
            "ok": False,
            "severity": "error",
            "blocking": True,
            "message": f"{name} must be between {minimum} and {maximum}.",
            "fix": f"Update {name} in .env, then restart the app.",
            "value": str(value),
        }

    if recommended_minimum and value < recommended_minimum:
        return {
            "id": name.lower(),
            "label": label,
            "ok": False,
            "severity": "warning",
            "blocking": False,
            "message": f"{name} is unusually low.",
            "fix": f"Consider setting {name} to at least {recommended_minimum} in .env.",
            "value": str(value),
        }

    if recommended_maximum and value > recommended_maximum:
        return {
            "id": name.lower(),
            "label": label,
            "ok": False,
            "severity": "warning",
            "blocking": False,
            "message": f"{name} is unusually high.",
            "fix": f"Consider setting {name} to {recommended_maximum} or lower in .env.",
            "value": str(value),
        }

    return {
        "id": name.lower(),
        "label": label,
        "ok": True,
        "severity": "ok",
        "blocking": False,
        "message": f"{name} is in range.",
        "fix": "No action needed.",
        "value": str(value),
    }


def config_status() -> dict:
    checks = []
    checks.extend(auth_config_checks())
    api_key_ok, api_key_state, api_message, api_fix = openai_api_key_state()
    checks.append(
        {
            "id": "openai_api_key",
            "label": "OpenAI API key",
            "ok": api_key_ok,
            "severity": "ok" if api_key_ok else "error",
            "blocking": not api_key_ok,
            "message": api_message,
            "fix": api_fix,
            "value": api_key_state,
        }
    )

    if api_key_ok and OPENAI_API_TEST_RESULT["status"] == "failed":
        checks.append(
            {
                "id": "openai_api_test",
                "label": "OpenAI API test",
                "ok": False,
                "severity": "error",
                "blocking": True,
                "message": OPENAI_API_TEST_RESULT["message"],
                "fix": OPENAI_API_TEST_RESULT["fix"],
                "value": "failed",
            }
        )
    elif api_key_ok:
        checks.append(
            {
                "id": "openai_api_test",
                "label": "OpenAI API test",
                "ok": True,
                "severity": "ok",
                "blocking": False,
                "message": OPENAI_API_TEST_RESULT["message"],
                "fix": OPENAI_API_TEST_RESULT["fix"],
                "value": str(OPENAI_API_TEST_RESULT["status"]),
            }
        )

    model_raw = raw_setting("OPENAI_MODEL")
    model_ok = model_raw not in {None, ""} and not is_placeholder(model_raw)
    checks.append(
        {
            "id": "openai_model",
            "label": "OpenAI model",
            "ok": model_ok,
            "severity": "ok" if model_ok else "error",
            "blocking": not model_ok,
            "message": "OPENAI_MODEL is configured." if model_ok else "OPENAI_MODEL is missing or still looks like a placeholder.",
            "fix": "No action needed." if model_ok else "Add OPENAI_MODEL to your .env file, then restart the app.",
            "value": settings.openai_model if model_ok else "missing",
        }
    )

    checks.extend(
        [
            check_writable_path(settings.data_dir, "DATA_DIR", "Data folder"),
            check_writable_path(settings.upload_dir, "UPLOAD_DIR", "Upload folder"),
            check_writable_path(settings.output_dir, "OUTPUT_DIR", "Output folder"),
            check_writable_path(settings.database_path, "DATABASE_PATH", "Database folder", directory=False),
            check_int_setting(
                "SRT_BATCH_SIZE",
                settings.srt_batch_size,
                minimum=SRT_BATCH_SIZE_MIN,
                maximum=SRT_BATCH_SIZE_MAX,
                recommended_maximum=SRT_BATCH_SIZE_RECOMMENDED_MAX,
            ),
            check_int_setting(
                "SRT_MAX_CHARS",
                settings.srt_max_chars,
                minimum=SRT_MAX_CHARS_MIN,
                maximum=SRT_MAX_CHARS_MAX,
                recommended_minimum=SRT_MAX_CHARS_RECOMMENDED_MIN,
                recommended_maximum=SRT_MAX_CHARS_RECOMMENDED_MAX,
            ),
        ]
    )

    checks.append(
        {
            "id": "default_source_language",
            "label": "Default source language",
            "ok": True,
            "severity": "ok",
            "blocking": False,
            "message": "Default source language is configured.",
            "fix": "No action needed.",
            "value": settings.default_source_language,
        }
    )

    checks.append(
        {
            "id": "default_target_language",
            "label": "Default target language",
            "ok": True,
            "severity": "ok",
            "blocking": False,
            "message": "Default target language is configured.",
            "fix": "No action needed.",
            "value": settings.default_target_language,
        }
    )

    blocking = [check for check in checks if check["blocking"] and not check["ok"]]
    warnings = [check for check in checks if check["severity"] == "warning"]

    return {
        "app": {
            "name": settings.app_name,
            "version": settings.app_version,
            "demo_mode": settings.demo_mode,
        },
        "ok": not blocking,
        "can_translate": not blocking,
        "summary": "Ready to translate." if not blocking else "Some setup items need attention before translation can start.",
        "checks": checks,
        "blocking_count": len(blocking),
        "warning_count": len(warnings),
    }


def translation_blockers() -> list[dict]:
    return [
        check
        for check in config_status()["checks"]
        if check["blocking"] and not check["ok"]
    ]


def runtime_warnings() -> list[dict[str, str]]:
    warnings = [
        {
            "level": "warning" if check["severity"] == "warning" else "error",
            "title": check["message"],
            "message": check["fix"],
            "blocking": check["blocking"],
        }
        for check in config_status()["checks"]
        if not check["ok"]
    ]

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        warnings.append(
            {
                "level": "warning",
                "title": "FFmpeg not found",
                "message": "Video and batch subtitle extraction require both ffmpeg and ffprobe on PATH.",
                "blocking": False,
            }
        )

    if settings.media_root is not None and not settings.media_root.is_dir():
        warnings.append(
            {
                "level": "warning",
                "title": "Media root is unavailable",
                "message": f"MEDIA_ROOT is set to {settings.media_root}, but that folder does not exist.",
                "blocking": False,
            }
        )

    return warnings


def startup_config_warnings() -> list[str]:
    return [
        f"{warning['title']} {warning['message']}"
        for warning in runtime_warnings()
    ]


def system_readiness() -> list[dict[str, str | bool]]:
    readiness = [
        {
            "label": check["label"],
            "ok": check["ok"],
            "value": check["value"],
            "detail": f"{check['message']} {check['fix']}",
        }
        for check in config_status()["checks"]
    ]

    ffmpeg_available = shutil.which("ffmpeg") is not None
    ffprobe_available = shutil.which("ffprobe") is not None
    media_root_ok = settings.media_root is None or settings.media_root.is_dir()

    readiness.extend(
        [
            {
                "label": "FFmpeg",
                "ok": ffmpeg_available,
                "value": "Available" if ffmpeg_available else "Not found",
                "detail": "Required for embedded subtitle extraction.",
            },
            {
                "label": "ffprobe",
                "ok": ffprobe_available,
                "value": "Available" if ffprobe_available else "Not found",
                "detail": "Required for video subtitle stream inspection.",
            },
            {
                "label": "Media root",
                "ok": media_root_ok,
                "value": str(settings.media_root) if settings.media_root else "Unrestricted",
                "detail": "Restricts backend-accessible batch folders when configured.",
            },
            {
                "label": "Upload limit",
                "ok": settings.max_upload_mb > 0,
                "value": f"{settings.max_upload_mb} MB",
                "detail": "Maximum accepted single upload size.",
            },
            {
                "label": "Temp folder",
                "ok": True,
                "value": str(settings.temp_dir),
                "detail": "Stores app-managed temporary files and cleanup-safe artifacts.",
            },
        ]
    )

    return readiness


def ensure_directories() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
