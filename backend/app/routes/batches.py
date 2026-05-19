import csv
import io
import json
import threading
import time
from uuid import uuid4

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

from app.config import runtime_warnings, settings, translation_blockers
from app.database import (
    add_log,
    create_batch,
    get_batch,
    list_batches,
    list_jobs_by_batch,
)
from app.models import SUPPORTED_LANGUAGES, SUPPORTED_STYLES
from app.services.job_runner import (
    batch_file_concurrency_limit,
    cancel_batch,
    run_folder_batch_job,
)
from app.services.media_scanner import DEFAULT_SOURCE_PREFERENCE, scan_media_folder
from app.template_context import configure_templates
from app.routes.utils import parse_checkbox, validate_language, validate_style

router = APIRouter(prefix="/batches")
templates = configure_templates(Jinja2Templates(directory="app/templates"))

TERMINAL_STATUSES = {"done", "failed", "cancelled", "interrupted"}
SCAN_SESSIONS: dict[str, dict] = {}
SCAN_CANCELLED: set[str] = set()
SCAN_LOCK = threading.Lock()
INTERNAL_SOURCE_PREFERENCE = DEFAULT_SOURCE_PREFERENCE
SCAN_SESSION_TTL_SECONDS = 60 * 60


def prune_scan_sessions_locked() -> None:
    cutoff = time.time() - SCAN_SESSION_TTL_SECONDS
    expired_ids = [
        scan_id
        for scan_id, session in SCAN_SESSIONS.items()
        if session.get("status") in {"done", "failed", "cancelled"}
        and session.get("updated_at", session.get("created_at", 0)) < cutoff
    ]

    for scan_id in expired_ids:
        SCAN_SESSIONS.pop(scan_id, None)
        SCAN_CANCELLED.discard(scan_id)


def active_scan_count() -> int:
    with SCAN_LOCK:
        prune_scan_sessions_locked()
        return len(
            [
                session
                for session in SCAN_SESSIONS.values()
                if session.get("status") in {"queued", "running", "cancel_requested"}
            ]
        )


def public_job(job: dict) -> dict:
    hidden_fields = {"input_path", "output_path"}
    return {key: value for key, value in job.items() if key not in hidden_fields}


def public_batch(batch: dict) -> dict:
    return {key: value for key, value in batch.items() if key != "folder_path"}


def report_source_kind(job: dict) -> str:
    message = (job.get("message") or "").lower()

    if "embedded" in message:
        return "embedded"

    if "external" in message:
        return "external"

    return ""


def batch_report_rows(batch_id: str) -> list[dict]:
    rows = []

    for job in list_jobs_by_batch(batch_id):
        rows.append(
            {
                "file": job.get("input_file") or "",
                "status": job.get("status") or "",
                "source_kind": report_source_kind(job),
                "source_language": job.get("source_language") or "",
                "output_name": job.get("output_file") or "",
                "reason_or_error": job.get("error") or job.get("message") or "",
                "translated_count": job.get("translated_count") or 0,
                "total_subtitles": job.get("total_subtitles") or 0,
                "progress_percent": job.get("progress_percent") or 0,
            }
        )

    return rows


def public_scan_result(folder_path: str, target_language: str, scan_result: dict) -> dict:
    return {
        "folder_path": folder_path,
        "target_language": target_language,
        "total_files": scan_result["total_files"],
        "skipped_files": scan_result["skipped_files"],
        "total_subtitles": scan_result["total_subtitles"],
        "files": [
            {
                "relative_path": item["relative_path"],
                "subfolder": item["subfolder"],
                "source_kind": item["source_kind"],
                "source_language": item["source_language"],
                "source_subtitle_name": item["source_subtitle_name"],
                "source_selection_reason": item.get("source_selection_reason"),
                "step": item["step"],
                "total_subtitles": item["total_subtitles"],
                "output_name": item["output_name"],
                "output_location": item.get("output_location") or "source",
                "output_note": item.get("output_note") or "",
            }
            for item in scan_result["items"]
        ],
        "skipped": [
            {
                "relative_path": item["relative_path"],
                "subfolder": item["subfolder"],
                "reason": item["reason"],
            }
            for item in scan_result["skipped"]
        ],
    }


def build_batch_status(batch_id: str) -> dict:
    batch = get_batch(batch_id)

    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    jobs = list_jobs_by_batch(batch_id)
    public_jobs = [public_job(job) for job in jobs]
    total_subtitles = sum(job.get("total_subtitles") or 0 for job in jobs)
    translated_count = sum(job.get("translated_count") or 0 for job in jobs)
    completed_files = len([job for job in jobs if job.get("status") == "done"])
    failed_files = len([job for job in jobs if job.get("status") == "failed"])
    skipped_files = len([job for job in jobs if job.get("status") in {"skipped", "cancelled", "cancel_requested", "interrupted"}])
    active_jobs = [job for job in jobs if job.get("status") == "running"][:batch_file_concurrency_limit()]

    if jobs:
        progress_percent = int(
            sum(job.get("progress_percent") or 0 for job in jobs) / len(jobs)
        )
    else:
        progress_percent = batch.get("progress_percent") or 0

    if batch.get("status") in {"done", "cancelled"}:
        progress_percent = 100

    return {
        "batch": {
            **public_batch(batch),
            "completed_files": completed_files,
            "failed_files": failed_files,
            "skipped_files": skipped_files,
            "progress_percent": progress_percent,
        },
        "jobs": public_jobs,
        "active_jobs": [public_job(job) for job in active_jobs],
        "total_subtitles": total_subtitles,
        "translated_count": translated_count,
        "progress_percent": progress_percent,
    }


@router.get("")
def batches_page(request: Request):
    blockers = translation_blockers()
    return templates.TemplateResponse(
        request=request,
        name="batches.html",
        context={
            "batches": list_batches(limit=10),
            "languages": SUPPORTED_LANGUAGES,
            "styles": SUPPORTED_STYLES,
            "default_target_language": settings.default_target_language,
            "default_style": settings.default_style,
            "default_concurrency": batch_file_concurrency_limit(),
            "runtime_warnings": runtime_warnings(),
            "translation_blockers": blockers,
            "can_translate": not blockers,
            "media_root": str(settings.media_root) if settings.media_root else "",
            "folder_placeholder": (
                f"{settings.media_root}/Shows"
                if settings.media_root
                else "C:\\Media\\TV Show or /media/Shows"
            ),
            "folder_picker_enabled": settings.media_root is None,
        },
    )


@router.post("/pick-folder")
def pick_batch_folder():
    if settings.media_root is not None:
        return JSONResponse(
            {
                "error": (
                    "Folder picker is disabled because MEDIA_ROOT is configured. "
                    f"Type a mounted folder path such as {settings.media_root}/Shows."
                )
            },
            status_code=503,
        )

    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        return JSONResponse(
            {"error": f"Folder picker is not available in this environment: {exc}"},
            status_code=503,
        )

    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        folder_path = filedialog.askdirectory(title="Select media folder")
        root.destroy()
    except Exception as exc:
        return JSONResponse(
            {"error": f"Could not open the folder picker: {exc}"},
            status_code=503,
        )

    if not folder_path:
        return {"folder_path": ""}

    return {"folder_path": folder_path}


@router.post("/scan")
def scan_batch_folder(
    folder_path: str = Form(...),
    target_language: str = Form(settings.default_target_language),
    overwrite_existing: bool = Form(False),
):
    target_language = validate_language(target_language)
    overwrite_existing = parse_checkbox(overwrite_existing)
    scan_id = str(uuid4())
    now = time.time()

    with SCAN_LOCK:
        prune_scan_sessions_locked()
        SCAN_SESSIONS[scan_id] = {
            "id": scan_id,
            "status": "queued",
            "progress": {
                "folders_scanned": 0,
                "files_checked": 0,
                "candidate_files_found": 0,
                "current_path": "",
                "items_found": 0,
                "skipped_found": 0,
            },
            "result": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
        }

    add_log(
        level="INFO",
        event="scan_started",
        message=(
            f"Preview scan started. Scan: {scan_id[:8]}. Folder: {folder_path}. "
            f"Target: {target_language}. Overwrite: {overwrite_existing}. "
            f"Source preference: {INTERNAL_SOURCE_PREFERENCE}."
        ),
        model=settings.openai_model,
    )

    def update_progress(progress: dict) -> None:
        with SCAN_LOCK:
            session = SCAN_SESSIONS.get(scan_id)

            if session:
                if session["status"] != "cancel_requested":
                    session["status"] = "running"
                session["progress"] = progress
                session["updated_at"] = time.time()

    def run_scan() -> None:
        scan_started_at = time.monotonic()

        try:
            with SCAN_LOCK:
                initial_progress = SCAN_SESSIONS[scan_id]["progress"]

            update_progress(initial_progress)
            scan_result = scan_media_folder(
                folder_path=folder_path,
                target_language=target_language,
                source_preference=INTERNAL_SOURCE_PREFERENCE,
                overwrite=overwrite_existing,
                progress_callback=update_progress,
                cancel_check=lambda: scan_id in SCAN_CANCELLED,
            )

            with SCAN_LOCK:
                session = SCAN_SESSIONS.get(scan_id)

                if session:
                    if scan_id in SCAN_CANCELLED:
                        session["status"] = "cancelled"
                        session["error"] = None
                        add_log(
                            level="WARNING",
                            event="scan_cancelled",
                            message=(
                                f"Preview scan {scan_id[:8]} cancelled after "
                                f"{round(time.monotonic() - scan_started_at, 2)}s."
                            ),
                            model=settings.openai_model,
                        )
                    else:
                        session["status"] = "done"
                        session["result"] = public_scan_result(folder_path, target_language, scan_result)
                        add_log(
                            level="SUCCESS",
                            event="scan_completed",
                            message=(
                                f"Preview scan {scan_id[:8]} completed in "
                                f"{round(time.monotonic() - scan_started_at, 2)}s. "
                                f"Ready: {scan_result['total_files']}. "
                                f"Skipped: {scan_result['skipped_files']}. "
                                f"Subtitles: {scan_result['total_subtitles']}."
                            ),
                            model=settings.openai_model,
                        )
                    session["updated_at"] = time.time()
        except Exception as exc:
            with SCAN_LOCK:
                session = SCAN_SESSIONS.get(scan_id)

                if session:
                    if scan_id in SCAN_CANCELLED:
                        session["status"] = "cancelled"
                        session["error"] = None
                        add_log(
                            level="WARNING",
                            event="scan_cancelled",
                            message=(
                                f"Preview scan {scan_id[:8]} cancelled after "
                                f"{round(time.monotonic() - scan_started_at, 2)}s."
                            ),
                            model=settings.openai_model,
                        )
                    else:
                        session["status"] = "failed"
                        session["error"] = str(exc)
                        add_log(
                            level="ERROR",
                            event="scan_failed",
                            message=(
                                f"Preview scan {scan_id[:8]} failed after "
                                f"{round(time.monotonic() - scan_started_at, 2)}s. Error: {exc}"
                            ),
                            model=settings.openai_model,
                        )
                    session["updated_at"] = time.time()
        finally:
            SCAN_CANCELLED.discard(scan_id)

    thread = threading.Thread(target=run_scan, daemon=True)
    thread.start()

    return JSONResponse({"scan_id": scan_id, "status": "queued"}, status_code=202)


@router.get("/scan/{scan_id}")
def scan_batch_folder_status(scan_id: str):
    with SCAN_LOCK:
        prune_scan_sessions_locked()
        session = SCAN_SESSIONS.get(scan_id)

        if not session:
            return JSONResponse({"error": "Scan not found."}, status_code=404)

        return jsonable_encoder(session)


@router.post("/scan/{scan_id}/cancel")
def cancel_batch_folder_scan(scan_id: str):
    with SCAN_LOCK:
        session = SCAN_SESSIONS.get(scan_id)

        if not session:
            return JSONResponse({"error": "Scan not found."}, status_code=404)

        if session["status"] in {"done", "failed", "cancelled"}:
            return {"status": session["status"]}

        SCAN_CANCELLED.add(scan_id)
        session["status"] = "cancel_requested"
        session["updated_at"] = time.time()

    add_log(
        level="WARNING",
        event="scan_cancel_requested",
        message=f"Cancellation requested for preview scan {scan_id[:8]}.",
        model=settings.openai_model,
    )

    return {"status": "cancel_requested"}


@router.post("")
def create_folder_batch(
    folder_path: str = Form(...),
    target_language: str = Form(settings.default_target_language),
    style: str = Form(settings.default_style),
    overwrite_existing: bool = Form(False),
    max_concurrency: int = Form(10),
    batch_selection_enabled: bool = Form(False),
    selected_files: list[str] | None = Form(None),
):
    blockers = translation_blockers()

    if blockers:
        first_blocker = blockers[0]
        raise HTTPException(
            status_code=400,
            detail=f"{first_blocker['message']} {first_blocker['fix']}",
        )

    target_language = validate_language(target_language)
    style = validate_style(style)
    overwrite_existing = parse_checkbox(overwrite_existing)
    batch_selection_enabled = parse_checkbox(batch_selection_enabled)
    selected_files = selected_files or []

    if batch_selection_enabled and not selected_files:
        raise HTTPException(status_code=400, detail="Select at least one file to translate.")

    batch_id = str(uuid4())

    create_batch(
        batch_id=batch_id,
        folder_path=folder_path,
        target_language=target_language,
        style=style,
    )

    thread = threading.Thread(
        target=run_folder_batch_job,
        kwargs={
            "batch_id": batch_id,
            "folder_path": folder_path,
            "target_language": target_language,
            "style": style,
            "source_preference": INTERNAL_SOURCE_PREFERENCE,
            "overwrite_existing": overwrite_existing,
            "max_concurrency": max_concurrency,
            "selected_files": selected_files if batch_selection_enabled else None,
        },
        daemon=True,
    )
    thread.start()

    return RedirectResponse(url=f"/batches/{batch_id}", status_code=303)


@router.get("/{batch_id}")
def batch_page(request: Request, batch_id: str):
    batch = get_batch(batch_id)

    if not batch:
        return {"error": "Batch not found"}

    return templates.TemplateResponse(
        request=request,
        name="batch.html",
        context={"batch": batch},
    )


@router.get("/{batch_id}/status")
def batch_status(batch_id: str):
    payload = build_batch_status(batch_id)

    if payload.get("error"):
        return JSONResponse(payload, status_code=404)

    return payload


@router.get("/{batch_id}/report.json")
def batch_report_json(batch_id: str):
    batch = get_batch(batch_id)

    if not batch:
        return JSONResponse({"error": "Batch not found"}, status_code=404)

    return {
        "batch": public_batch(batch),
        "files": batch_report_rows(batch_id),
    }


@router.get("/{batch_id}/report.csv")
def batch_report_csv(batch_id: str):
    if not get_batch(batch_id):
        return JSONResponse({"error": "Batch not found"}, status_code=404)

    rows = batch_report_rows(batch_id)
    output = io.StringIO()
    fieldnames = [
        "file",
        "status",
        "source_kind",
        "source_language",
        "output_name",
        "reason_or_error",
        "translated_count",
        "total_subtitles",
        "progress_percent",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="batch-{batch_id[:8]}-report.csv"'},
    )


@router.post("/{batch_id}/cancel")
def cancel_batch_job(batch_id: str):
    if not get_batch(batch_id):
        return JSONResponse({"error": "Batch not found"}, status_code=404)

    cancel_batch(batch_id)
    refreshed = get_batch(batch_id)
    return {"status": refreshed["status"] if refreshed else "cancel_requested"}


@router.get("/{batch_id}/events")
def batch_events(batch_id: str):
    def event_stream():
        while True:
            payload = build_batch_status(batch_id)
            yield f"data: {json.dumps(jsonable_encoder(payload))}\n\n"

            batch = payload.get("batch")

            if not batch or batch.get("status") in TERMINAL_STATUSES:
                break

            time.sleep(1)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
