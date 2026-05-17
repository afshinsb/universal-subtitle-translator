from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.database import add_log
from app.routes.batches import active_scan_count
from app.services.cleanup import cleanup_history_and_app_files
from app.services.job_runner import active_runtime_counts, repair_stale_work

router = APIRouter()


@router.post("/cleanup")
def cleanup_app_files():
    active_counts = active_runtime_counts()
    scans = active_scan_count()

    if active_counts["total"] or scans:
        add_log(
            level="WARNING",
            event="cleanup_blocked",
            message=(
                "Cleanup blocked by real active work. "
                f"Jobs: {active_counts['jobs']}. Batches: {active_counts['batches']}. Scans: {scans}."
            ),
        )
        return JSONResponse(
            status_code=409,
            content={
                "error": "Stop active jobs before cleanup.",
                "detail": "Cleanup is disabled while real in-memory jobs, batches, or scans are active.",
                "active": {
                    **active_counts,
                    "scans": scans,
                },
            },
        )

    repaired = repair_stale_work(reason="cleanup")
    summary = cleanup_history_and_app_files()
    add_log(
        level="INFO",
        event="cleanup_unblocked",
        message=(
            "Cleanup was allowed because no active in-memory work was running. "
            f"Stale repaired before cleanup: {repaired['total']}."
        ),
    )

    return {
        "message": "Recent jobs cleared.",
        "summary": summary,
    }


@router.post("/cleanup/stale-jobs")
def force_clear_stale_jobs():
    active_counts = active_runtime_counts()
    scans = active_scan_count()

    if active_counts["total"] or scans:
        add_log(
            level="WARNING",
            event="stale_clear_blocked",
            message=(
                "Force stale-job repair blocked by real active work. "
                f"Jobs: {active_counts['jobs']}. Batches: {active_counts['batches']}. Scans: {scans}."
            ),
        )
        return JSONResponse(
            status_code=409,
            content={
                "error": "Active work is still running.",
                "detail": "Force clear only repairs stale persisted history when no real workers are active.",
                "active": {
                    **active_counts,
                    "scans": scans,
                },
            },
        )

    repaired = repair_stale_work(reason="force clear stale jobs")

    return {
        "message": "Stale jobs repaired.",
        "repaired": repaired,
    }
