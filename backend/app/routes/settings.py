from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app.config import config_status, runtime_warnings, settings, system_readiness
from app.models import SUPPORTED_LANGUAGES, SUPPORTED_STYLES
from app.routes.batches import active_scan_count
from app.services.job_runner import active_runtime_counts, stale_runtime_counts
from app.template_context import configure_templates

router = APIRouter()
templates = configure_templates(Jinja2Templates(directory="app/templates"))


@router.get("/config/status")
def config_status_endpoint():
    return config_status()


@router.get("/settings")
def settings_page(request: Request):
    readiness = system_readiness()
    system_is_healthy = all(check["ok"] for check in readiness)
    active_counts = active_runtime_counts()
    active_counts["scans"] = active_scan_count()
    cleanup_disabled = bool(active_counts["total"] or active_counts["scans"])
    stale_counts = stale_runtime_counts()

    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "settings": settings,
            "languages": SUPPORTED_LANGUAGES,
            "styles": SUPPORTED_STYLES,
            "runtime_warnings": runtime_warnings(),
            "readiness": readiness,
            "system_is_healthy": system_is_healthy,
            "cleanup_disabled": cleanup_disabled,
            "cleanup_active_counts": active_counts,
            "cleanup_stale_counts": stale_counts,
        },
    )
