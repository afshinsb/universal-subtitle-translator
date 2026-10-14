import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import auth_config_checks, settings, ensure_directories, run_openai_api_key_test, startup_config_warnings
from app.database import init_db
from app.routes import auth, jobs, files, settings as settings_routes, logs, batches, cleanup as cleanup_routes
from app.services.job_runner import repair_stale_work, request_shutdown
from app.services import automation
from app.routes import automation as automation_routes

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    ensure_directories()
    run_openai_api_key_test()
    for warning in startup_config_warnings():
        logger.warning("Configuration warning: %s", warning)
    init_db()
    repair_stale_work(reason="backend startup")
    automation.init_schema()
    automation.worker.start()
    try:
        yield
    finally:
        request_shutdown()
        automation.worker.stop()


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

PUBLIC_PATH_PREFIXES = ("/static/",)
PUBLIC_PATHS = {"/health", "/login", "/logout"}


def wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path

    if path.startswith("/automation/hooks/") or path in PUBLIC_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PATH_PREFIXES):
        return await call_next(request)

    # A cookie signed with the shipped development secret is forgeable. Apply
    # production setup checks before trusting it, including for existing sessions.
    if any(check["blocking"] and not check["ok"] for check in auth_config_checks()):
        return JSONResponse(
            status_code=503,
            content={"error": "Authentication setup is incomplete. Check AUTH_ENABLED, ADMIN_PASSWORD and SESSION_SECRET."},
        )

    if not settings.auth_enabled:
        return await call_next(request)

    if request.session.get("authenticated") is True:
        return await call_next(request)

    if wants_html(request):
        next_url = quote(str(request.url.path), safe="/")

        if request.url.query:
            next_url = f"{next_url}%3F{quote(request.url.query, safe='=&')}"

        return RedirectResponse(url=f"/login?next={next_url}", status_code=303)

    return JSONResponse(
        status_code=401,
        content={"error": "Authentication required.", "detail": "Log in to access this resource."},
    )


app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="ust_session",
    max_age=60 * 60 * 12,
    same_site="lax",
    https_only=settings.session_https_only,
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    return JSONResponse(
        status_code=422,
        content={
            "error": "Validation failed.",
            "detail": exc.errors(),
        },
    )


@app.exception_handler(Exception)
async def unexpected_exception_handler(request, exc):
    logger.exception("Unhandled application error", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error.",
            "detail": "An unexpected error occurred. Check application logs for details.",
        },
    )


app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(files.router)
app.include_router(settings_routes.router)
app.include_router(logs.router)
app.include_router(batches.router)
app.include_router(cleanup_routes.router)
app.include_router(automation_routes.router)


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
    }
