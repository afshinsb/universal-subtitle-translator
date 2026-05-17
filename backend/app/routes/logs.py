import csv
import io
from collections import Counter
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.database import list_jobs_by_batch, list_logs, list_logs_for_job
from app.template_context import configure_templates

router = APIRouter()
templates = configure_templates(Jinja2Templates(directory="app/templates"))

SEVERITY_MAP = {
    "SUCCESS": "success",
    "INFO": "info",
    "WARNING": "warning",
    "ERROR": "error",
    "DEBUG": "debug",
}

EVENT_TITLES = {
    "batch_job_started": "Batch started",
    "batch_job_completed": "Batch completed",
    "batch_job_cancelled": "Batch cancelled",
    "batch_job_failed": "Batch failed",
    "batch_job_interrupted": "Batch interrupted",
    "batch_cancel_requested": "Batch cancellation requested",
    "batch_cancel_timeout": "Batch cancel timeout",
    "batch_concurrency_started": "Workers started",
    "scan_started": "Scan started",
    "scan_completed": "Scan completed",
    "scan_cancel_requested": "Scan cancellation requested",
    "scan_cancelled": "Scan cancelled",
    "scan_failed": "Scan failed",
    "folder_scan_completed": "Scan completed",
    "media_file_skipped": "File skipped",
    "media_file_failed": "File failed",
    "media_file_cancelled": "File cancelled",
    "source_subtitle_selected": "Source subtitle selected",
    "subtitle_already_target_language": "Subtitle already target language",
    "job_started": "Translation started",
    "job_completed": "Translation completed",
    "job_cancelled": "Translation cancelled",
    "job_cancel_requested": "Job cancellation requested",
    "job_cancel_timeout": "Cancel timeout",
    "job_failed": "Translation failed",
    "single_file_job_failed": "Single-file job failed",
    "single_file_job_cancelled": "Single-file job cancelled",
    "source_language_detected": "Source language detected",
    "job_batches_created": "Translation batches prepared",
    "batch_started": "Provider batch started",
    "batch_completed": "Provider batch completed",
    "batch_tokens": "Token usage recorded",
    "provider_request_completed": "Provider request completed",
    "provider_retry_attempted": "Provider retry attempted",
    "batch_missing_indexes": "Translation repair started",
    "repair_tokens": "Repair token usage",
    "repair_request_completed": "Repair request completed",
    "repair_success": "Repair succeeded",
    "repair_failed": "Repair failed",
    "validation_completed": "Validation completed",
    "embedded_subtitle_extract_started": "Subtitle extraction started",
    "embedded_subtitle_extract_skipped": "Using cached extraction",
    "ffmpeg_extract_completed": "FFmpeg extraction completed",
    "ffmpeg_extract_failed": "FFmpeg extraction failed",
    "media_job_failed": "Media job failed",
    "media_job_cancelled": "Media job cancelled",
    "cleanup_history_cleared": "History cleared",
    "cleanup_completed": "Cleanup completed",
    "cleanup_blocked": "Cleanup blocked",
    "cleanup_unblocked": "Cleanup unblocked",
    "cleanup_error": "Cleanup error",
    "cleanup_skipped_path": "Cleanup skipped path",
    "cleanup_skipped_root": "Cleanup skipped folder",
    "cleanup_deleted_file": "App file deleted",
    "cleanup_deleted_folder": "App folder deleted",
    "cleanup_cleaned_folder": "App folder cleaned",
    "stale_job_repaired": "Stale job repaired",
    "stale_batch_repaired": "Stale batch repaired",
    "stale_work_repaired": "Stale work repaired",
    "stale_clear_blocked": "Stale clear blocked",
}

QUIET_EVENTS = {
    "batch_started",
    "batch_completed",
    "batch_tokens",
    "provider_request_completed",
    "embedded_subtitle_extract_started",
    "repair_tokens",
    "cleanup_deleted_file",
    "cleanup_deleted_folder",
    "cleanup_cleaned_folder",
}

CATEGORY_LABELS = [
    "System",
    "Scan",
    "Translation",
    "Extraction",
    "API/Provider",
    "Errors",
    "Warnings",
    "Batch jobs",
    "User actions",
]


def normalize_severity(level: str | None) -> str:
    if not level:
        return "info"

    return SEVERITY_MAP.get(level.upper(), level.lower())


def log_category(log: dict) -> str:
    severity = normalize_severity(log.get("level"))
    event = log.get("event") or ""
    message = (log.get("message") or "").lower()

    if severity == "error" or event.endswith("_failed") or "failed" in event:
        return "Errors"

    if severity == "warning" or "warning" in event or "skipped" in event:
        return "Warnings" if "skipped" not in event else "Scan"

    if "cleanup" in event or "cancel" in event:
        return "User actions"

    if "extract" in event or "embedded_subtitle" in event or "source_subtitle" in event or "ffmpeg" in event:
        return "Extraction"

    if "token" in event or "repair" in event or "provider" in event or "provider" in message or "openai" in message:
        return "API/Provider"

    if "scan" in event or "folder_scan" in event or "media_file_skipped" in event:
        return "Scan"

    if "batch_job" in event or log.get("batch_id"):
        return "Batch jobs"

    if "job" in event or "translation" in event or "validation" in event or "source_language" in event:
        return "Translation"

    return "System"


def human_title(log: dict) -> str:
    event = log.get("event") or ""

    if event in EVENT_TITLES:
        return EVENT_TITLES[event]

    return event.replace("_", " ").strip().title() or "Log event"


def compact_time(value: str | None) -> str:
    if not value:
        return "-"

    try:
        parsed = datetime.fromisoformat(value)
        return parsed.strftime("%b %d, %H:%M:%S")
    except ValueError:
        return value


def cost_summary(logs: list[dict]) -> dict:
    input_tokens = sum(log.get("input_tokens") or 0 for log in logs)
    output_tokens = sum(log.get("output_tokens") or 0 for log in logs)
    total_tokens = sum(log.get("total_tokens") or 0 for log in logs)
    input_cost = (input_tokens / 1_000_000) * settings.openai_input_cost_per_1m
    output_cost = (output_tokens / 1_000_000) * settings.openai_output_cost_per_1m
    total_cost = input_cost + output_cost

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "estimated_cost": total_cost,
        "estimated_cost_display": f"${total_cost:.4f}" if total_cost else "Not configured",
        "cost_configured": bool(settings.openai_input_cost_per_1m or settings.openai_output_cost_per_1m),
    }


def log_context(log: dict) -> list[dict[str, str]]:
    context = []

    if log.get("model"):
        context.append({"label": "Model", "value": str(log["model"])})

    if log.get("total_tokens"):
        context.append({"label": "Tokens", "value": f"{log.get('total_tokens')} total"})

    if log.get("batch_number"):
        context.append({"label": "Batch", "value": f"{log.get('batch_number')} / {log.get('batch_count')}"})

    if log.get("subtitle_start") is not None:
        context.append({"label": "Indexes", "value": f"{log.get('subtitle_start')} - {log.get('subtitle_end')}"})

    if log.get("job_id"):
        context.append({"label": "Job", "value": str(log["job_id"])[:8]})

    if log.get("batch_id"):
        context.append({"label": "Batch ID", "value": str(log["batch_id"])[:8]})

    return context


def present_log(log: dict) -> dict:
    severity = normalize_severity(log.get("level"))
    category = log_category(log)
    event = log.get("event") or ""

    return {
        **log,
        "severity": severity,
        "category": category,
        "title": human_title(log),
        "time_label": compact_time(log.get("created_at")),
        "context": log_context(log),
        "quiet": event in QUIET_EVENTS or severity == "debug",
        "search_text": " ".join(
            str(part or "")
            for part in [
                log.get("message"),
                event,
                category,
                severity,
                log.get("model"),
                log.get("job_id"),
                log.get("batch_id"),
            ]
        ).lower(),
    }


def log_summary(logs: list[dict]) -> dict:
    severity_counts = Counter(normalize_severity(log.get("level")) for log in logs)
    event_counts = Counter(log.get("event") or "" for log in logs)
    categories = Counter(log_category(log) for log in logs)
    costs = cost_summary(logs)

    return {
        "total": len(logs),
        "visible_default": len([log for log in logs if (log.get("event") or "") not in QUIET_EVENTS]),
        "translated": event_counts["job_completed"],
        "skipped": event_counts["media_file_skipped"],
        "errors": severity_counts["error"],
        "warnings": severity_counts["warning"],
        "success": severity_counts["success"],
        "tokens": costs["total_tokens"],
        "input_tokens": costs["input_tokens"],
        "output_tokens": costs["output_tokens"],
        "estimated_cost_display": costs["estimated_cost_display"],
        "cost_configured": costs["cost_configured"],
        "categories": dict(categories),
    }


def logs_view_context(
    logs: list[dict],
    title: str = "Application Logs",
    csv_url: str = "/logs.csv",
    json_url: str = "/logs.json",
) -> dict:
    presented = [present_log(log) for log in logs]

    return {
        "logs": presented,
        "summary": log_summary(logs),
        "categories": CATEGORY_LABELS,
        "severities": ["info", "success", "warning", "error", "debug"],
        "page_title": title,
        "csv_url": csv_url,
        "json_url": json_url,
    }


def logs_csv_response(logs: list[dict], filename: str) -> Response:
    output = io.StringIO()
    fieldnames = [
        "id",
        "created_at",
        "level",
        "event",
        "message",
        "model",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "batch_number",
        "batch_count",
        "subtitle_start",
        "subtitle_end",
        "job_id",
        "batch_id",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows([{field: log.get(field) for field in fieldnames} for log in logs])

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def batch_logs(batch_id: str) -> list[dict]:
    job_ids = {job["id"] for job in list_jobs_by_batch(batch_id)}
    return [
        log for log in list_logs(limit=1000)
        if log.get("batch_id") == batch_id or log.get("job_id") in job_ids
    ]


@router.get("/logs")
def logs_page(request: Request):
    logs = list_logs(limit=300)

    return templates.TemplateResponse(
        request=request,
        name="logs.html",
        context=logs_view_context(logs),
    )


@router.get("/logs.json")
def logs_json():
    return {
        "logs": list_logs(limit=300),
    }


@router.get("/logs.csv")
def logs_csv():
    return logs_csv_response(list_logs(limit=300), "application-logs.csv")


@router.get("/jobs/{job_id}/logs")
def job_logs_page(request: Request, job_id: str):
    logs = list_logs_for_job(job_id=job_id, limit=300)

    return templates.TemplateResponse(
        request=request,
        name="logs.html",
        context=logs_view_context(
            logs,
            title=f"Job Logs {job_id[:8]}",
            csv_url=f"/jobs/{job_id}/logs.csv",
            json_url=f"/jobs/{job_id}/logs.json",
        ),
    )


@router.get("/jobs/{job_id}/logs.json")
def job_logs_json(job_id: str):
    return {
        "logs": list_logs_for_job(job_id=job_id, limit=300),
    }


@router.get("/jobs/{job_id}/logs.csv")
def job_logs_csv(job_id: str):
    return logs_csv_response(list_logs_for_job(job_id=job_id, limit=300), f"job-{job_id[:8]}-logs.csv")


@router.get("/batches/{batch_id}/logs.json")
def batch_logs_json(batch_id: str):
    return {"logs": batch_logs(batch_id)}


@router.get("/batches/{batch_id}/logs.csv")
def batch_logs_csv(batch_id: str):
    return logs_csv_response(batch_logs(batch_id), f"batch-{batch_id[:8]}-logs.csv")
