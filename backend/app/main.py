import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings, ensure_directories, run_openai_api_key_test, startup_config_warnings
from app.database import init_db
from app.routes import jobs, files, settings as settings_routes, logs, batches, cleanup as cleanup_routes
from app.services.job_runner import repair_stale_work

logger = logging.getLogger(__name__)
app = FastAPI(title=settings.app_name, version=settings.app_version)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.on_event("startup")
def startup_event():
    ensure_directories()
    run_openai_api_key_test()
    for warning in startup_config_warnings():
        logger.warning("Configuration warning: %s", warning)
    init_db()
    repair_stale_work(reason="backend startup")


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


app.include_router(jobs.router)
app.include_router(files.router)
app.include_router(settings_routes.router)
app.include_router(logs.router)
app.include_router(batches.router)
app.include_router(cleanup_routes.router)


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
    }
