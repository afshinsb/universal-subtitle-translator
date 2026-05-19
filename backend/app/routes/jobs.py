from pathlib import Path
from uuid import uuid4
import threading
import asyncio

from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi import HTTPException
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates

from app.config import runtime_warnings, settings, translation_blockers
from app.database import create_job, get_job, list_jobs
from app.models import SUPPORTED_LANGUAGES, SUPPORTED_STYLES
from app.services.job_runner import cancel_job, run_single_file_job
from app.services.media_scanner import VIDEO_EXTENSIONS
from app.template_context import configure_templates
from app.routes.utils import validate_language, validate_style

router = APIRouter()
templates = configure_templates(Jinja2Templates(directory="app/templates"))
UPLOAD_CHUNK_SIZE = 1024 * 1024


def public_job(job: dict) -> dict:
    hidden_fields = {"input_path", "output_path"}
    return {key: value for key, value in job.items() if key not in hidden_fields}


@router.get("/")
def home(request: Request):
    jobs = list_jobs(limit=10)
    blockers = translation_blockers()
    recent_outputs = [
        {
            "name": job.get("output_file"),
            "source": job.get("input_file"),
        }
        for job in list_jobs(limit=50)
        if job.get("status") == "done" and job.get("output_file")
    ][:8]

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "jobs": jobs,
            "languages": SUPPORTED_LANGUAGES,
            "styles": SUPPORTED_STYLES,
            "default_target_language": settings.default_target_language,
            "default_style": settings.default_style,
            "runtime_warnings": runtime_warnings(),
            "translation_blockers": blockers,
            "can_translate": not blockers,
            "max_upload_mb": settings.max_upload_mb,
            "recent_outputs": recent_outputs,
        },
    )


@router.get("/about")
def about_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="about.html",
        context={
            "languages": SUPPORTED_LANGUAGES,
            "video_extensions": sorted(VIDEO_EXTENSIONS),
            "translation_providers": ["OpenAI"],
        },
    )


@router.get("/outputs")
def outputs_page(request: Request):
    outputs = [
        job
        for job in list_jobs(limit=100)
        if job.get("status") == "done" and job.get("output_file")
    ]

    return templates.TemplateResponse(
        request=request,
        name="outputs.html",
        context={"outputs": outputs},
    )


@router.post("/jobs")
async def create_translation_job(
    file: UploadFile = File(...),
    target_language: str = Form(settings.default_target_language),
    style: str = Form(settings.default_style),
    overwrite_existing: bool = Form(False),
):
    target_language = validate_language(target_language)
    style = validate_style(style)

    job_id = str(uuid4())

    safe_filename = Path(file.filename or "").name
    suffix = Path(safe_filename).suffix.lower()
    supported_extensions = {".srt", *VIDEO_EXTENSIONS}

    if suffix not in supported_extensions:
        raise HTTPException(
            status_code=400,
            detail="Only .srt subtitle files and supported video files are supported.",
        )

    blockers = translation_blockers()

    if blockers:
        first_blocker = blockers[0]
        raise HTTPException(
            status_code=400,
            detail=f"{first_blocker['message']} {first_blocker['fix']}",
        )

    input_dir = settings.upload_dir / job_id
    output_dir = settings.output_dir / job_id
    input_dir.mkdir(parents=True, exist_ok=True)
    input_path = input_dir / safe_filename
    max_bytes = settings.max_upload_mb * 1024 * 1024

    written = 0

    try:
        with input_path.open("wb") as output_file:
            while chunk := await file.read(UPLOAD_CHUNK_SIZE):
                written += len(chunk)

                if written > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"File is larger than the browser upload limit of {settings.max_upload_mb} MB. "
                            "For large videos or media libraries, mount the folder in Docker and use Batch mode with a path such as /media/Shows."
                        ),
                    )

                await asyncio.to_thread(output_file.write, chunk)
    except Exception:
        input_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    create_job(
        job_id=job_id,
        input_file=safe_filename,
        input_path=str(input_path),
        target_language=target_language,
        source_language="Detecting",
        style=style,
        model=settings.openai_model,
    )

    thread = threading.Thread(
        target=run_single_file_job,
        kwargs={
            "job_id": job_id,
            "input_path": str(input_path),
            "input_filename": safe_filename,
            "target_language": target_language,
            "style": style,
            "overwrite_existing": overwrite_existing,
            "output_dir": str(output_dir),
        },
        daemon=True,
    )
    thread.start()

    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


@router.get("/jobs")
def jobs_page():
    return {
        "jobs": [public_job(job) for job in list_jobs(limit=50)],
    }


@router.get("/jobs/{job_id}")
def job_page(request: Request, job_id: str):
    job = get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return templates.TemplateResponse(
        request=request,
        name="job.html",
        context={"job": job},
    )


@router.get("/jobs/{job_id}/status")
def job_status(job_id: str):
    job = get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return public_job(job)


@router.post("/jobs/{job_id}/cancel")
def cancel_translation_job(job_id: str):
    job = get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] in {"done", "failed", "cancelled", "skipped", "interrupted"}:
        return {"status": job["status"]}

    cancel_job(job_id)
    refreshed = get_job(job_id)
    return {"status": refreshed["status"] if refreshed else "cancel_requested"}


@router.get("/jobs/{job_id}/download")
def download_job_output(job_id: str):
    job = get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != "done":
        raise HTTPException(status_code=409, detail="Job is not complete yet")

    output_path = job.get("output_path")
    output_file = job.get("output_file")

    if not output_path or not output_file:
        raise HTTPException(status_code=404, detail="Output file not found")

    if not Path(output_path).is_file():
        raise HTTPException(status_code=404, detail="Output file no longer exists")

    return FileResponse(
        path=output_path,
        filename=output_file,
        media_type="application/x-subrip",
    )
