"""Modern pages reuse the existing authenticated backend and manual workflows."""

from fastapi import APIRouter, HTTPException, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.routes import jobs, batches, logs, settings as settings_routes
from app.routes.automation import check_origin
from app.services import ui_state
from app.template_context import configure_templates

router = APIRouter(prefix="/ui")
templates = configure_templates(Jinja2Templates(directory="app/templates"))
PAGES = {
    "overview": "Overview",
    "automation": "Automation",
    "queue": "Translation queue",
    "downloads": "Media intake",
    "guard": "Download Guard",
    "history": "History",
    "translate": "Translate",
    "batches": "Batch translation",
    "outputs": "Outputs",
    "settings": "Settings",
    "logs": "Logs",
    "about": "About",
}


def render(request, page, **context):
    response = templates.TemplateResponse(
        request=request,
        name="modern/page.html",
        context={
            "page": page,
            "title": PAGES[page],
            "environment": "Development" if settings.dev_mode else "Production",
            "modern": True,
            "state": ui_state.snapshot(),
            **context,
        },
    )
    response.set_cookie(
        "ust_interface",
        "modern",
        max_age=31536000,
        httponly=True,
        samesite="lax",
        secure=settings.session_https_only,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/interface")
def interface(request: Request, mode: str = Form(...), target: str = Form("/")):
    check_origin(request)
    if (
        mode not in {"modern", "legacy"}
        or not target.startswith("/")
        or target.startswith("//")
        or "?" in target
        or "\\" in target
    ):
        raise HTTPException(422, "Invalid interface destination")
    if mode == "modern" and not (target == "/ui" or target.startswith("/ui/")):
        target = "/ui"
    if mode == "legacy" and (
        target.startswith("/ui")
        or target
        not in {
            "/",
            "/automation",
            "/batches",
            "/outputs",
            "/settings",
            "/logs",
            "/about",
        }
    ):
        target = "/"
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        "ust_interface",
        mode,
        max_age=31536000,
        httponly=True,
        samesite="lax",
        secure=settings.session_https_only,
    )
    return response


@router.get("/api/status")
def status():
    return ui_state.snapshot()


@router.get("/api/{domain}")
def records(
    domain: str, page: int = 1, state: str = "active", search: str = "", size: int = 25
):
    try:
        return ui_state.pagination(domain, page, state, search, size)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("")
@router.get("/")
def overview(request: Request):
    return render(request, "overview")


@router.get("/jobs/{job_id}")
def job(request: Request, job_id: str):
    response = jobs.job_page(request, job_id)
    return render(
        request,
        "translate",
        manual="shared/job.html",
        **{k: v for k, v in response.context.items() if k != "request"},
    )


@router.get("/jobs/{job_id}/logs")
def job_logs(request: Request, job_id: str):
    response = logs.job_logs_page(request, job_id)
    return render(
        request,
        "logs",
        manual="shared/logs.html",
        **{k: v for k, v in response.context.items() if k != "request"},
    )


@router.get("/batches/{batch_id}")
def batch(request: Request, batch_id: str):
    response = batches.batch_page(request, batch_id)
    return render(
        request,
        "batches",
        manual="shared/batch.html",
        **{k: v for k, v in response.context.items() if k != "request"},
    )


@router.get("/{page}")
def page(request: Request, page: str):
    if page not in PAGES:
        raise HTTPException(404, "Page not found")
    handlers = {
        "translate": (jobs.home, "index"),
        "batches": (batches.batches_page, "batches"),
        "outputs": (jobs.outputs_page, "outputs"),
        "settings": (settings_routes.settings_page, "settings"),
        "logs": (logs.logs_page, "logs"),
        "about": (jobs.about_page, "about"),
    }
    if page in handlers:
        handler, name = handlers[page]
        response = handler(request)
        return render(
            request,
            page,
            manual="shared/" + name + ".html",
            **{k: v for k, v in response.context.items() if k != "request"},
        )
    return render(request, page)
