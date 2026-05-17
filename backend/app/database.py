import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.config import settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.database_path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def init_db() -> None:
    with get_connection() as conn:
        conn.execute("PRAGMA journal_mode=WAL")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS batches (
                id TEXT PRIMARY KEY,
                folder_path TEXT NOT NULL,
                target_language TEXT NOT NULL,
                style TEXT,
                status TEXT NOT NULL,
                message TEXT,
                total_files INTEGER DEFAULT 0,
                completed_files INTEGER DEFAULT 0,
                failed_files INTEGER DEFAULT 0,
                progress_percent INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                batch_id TEXT,
                input_file TEXT NOT NULL,
                input_path TEXT NOT NULL,
                output_file TEXT,
                output_path TEXT,
                source_language TEXT,
                target_language TEXT NOT NULL,
                style TEXT,
                status TEXT NOT NULL,
                message TEXT,
                total_subtitles INTEGER DEFAULT 0,
                translated_count INTEGER DEFAULT 0,
                progress_percent INTEGER DEFAULT 0,
                error TEXT,
                model TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT,
                batch_id TEXT,
                level TEXT NOT NULL,
                event TEXT NOT NULL,
                message TEXT NOT NULL,
                model TEXT,
                input_tokens INTEGER,
                output_tokens INTEGER,
                total_tokens INTEGER,
                batch_number INTEGER,
                batch_count INTEGER,
                subtitle_start INTEGER,
                subtitle_end INTEGER,
                created_at TEXT NOT NULL
            )
            """
        )

        if not column_exists(conn, "jobs", "batch_id"):
            conn.execute("ALTER TABLE jobs ADD COLUMN batch_id TEXT")

        conn.commit()


def add_log(
    level: str,
    event: str,
    message: str,
    job_id: str | None = None,
    batch_id: str | None = None,
    model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    batch_number: int | None = None,
    batch_count: int | None = None,
    subtitle_start: int | None = None,
    subtitle_end: int | None = None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO logs (
                job_id, batch_id, level, event, message, model,
                input_tokens, output_tokens, total_tokens,
                batch_number, batch_count, subtitle_start, subtitle_end,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                batch_id,
                level,
                event,
                message,
                model,
                input_tokens,
                output_tokens,
                total_tokens,
                batch_number,
                batch_count,
                subtitle_start,
                subtitle_end,
                utc_now(),
            ),
        )
        conn.commit()


def list_logs(limit: int = 200) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(row) for row in rows]


def list_logs_for_job(job_id: str, limit: int = 200) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM logs
            WHERE job_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (job_id, limit),
        ).fetchall()

    return [dict(row) for row in rows]


def create_batch(
    batch_id: str,
    folder_path: str,
    target_language: str,
    style: str,
) -> None:
    now = utc_now()

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO batches (
                id, folder_path, target_language, style,
                status, message,
                total_files, completed_files, failed_files, progress_percent,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, 0, ?, ?)
            """,
            (
                batch_id,
                folder_path,
                target_language,
                style,
                "queued",
                "Batch created.",
                now,
                now,
            ),
        )
        conn.commit()


def update_batch(batch_id: str, **fields: Any) -> None:
    if not fields:
        return

    fields["updated_at"] = utc_now()

    keys = list(fields.keys())
    values = [fields[key] for key in keys]
    set_clause = ", ".join(f"{key} = ?" for key in keys)

    with get_connection() as conn:
        conn.execute(
            f"UPDATE batches SET {set_clause} WHERE id = ?",
            values + [batch_id],
        )
        conn.commit()


def get_batch(batch_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM batches WHERE id = ?",
            (batch_id,),
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def list_batches(limit: int = 20) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM batches
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(row) for row in rows]


def create_job(
    job_id: str,
    input_file: str,
    input_path: str,
    target_language: str,
    source_language: str,
    style: str,
    model: str,
    batch_id: str | None = None,
    total_subtitles: int = 0,
    status: str = "queued",
    message: str = "Job created.",
    output_file: str | None = None,
    output_path: str | None = None,
) -> None:
    now = utc_now()

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO jobs (
                id, batch_id, input_file, input_path, output_file, output_path,
                source_language, target_language, style,
                status, message,
                total_subtitles, translated_count, progress_percent,
                error, model, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, NULL, ?, ?, ?)
            """,
            (
                job_id,
                batch_id,
                input_file,
                input_path,
                output_file,
                output_path,
                source_language,
                target_language,
                style,
                status,
                message,
                total_subtitles,
                100 if status in {"skipped", "done"} else 0,
                model,
                now,
                now,
            ),
        )
        conn.commit()


def update_job(job_id: str, **fields: Any) -> None:
    if not fields:
        return

    fields["updated_at"] = utc_now()

    keys = list(fields.keys())
    values = [fields[key] for key in keys]
    set_clause = ", ".join(f"{key} = ?" for key in keys)

    with get_connection() as conn:
        conn.execute(
            f"UPDATE jobs SET {set_clause} WHERE id = ?",
            values + [job_id],
        )
        conn.commit()


def get_job(job_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM jobs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(row) for row in rows]


def list_jobs_by_batch(batch_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM jobs
            WHERE batch_id = ?
            ORDER BY input_file ASC
            """,
            (batch_id,),
        ).fetchall()

    return [dict(row) for row in rows]


ACTIVE_STATUSES = ("queued", "running", "cancel_requested")
STALE_WORK_STATUSES = (
    "queued",
    "running",
    "scanning",
    "extracting",
    "translating",
    "cancel_requested",
    "canceling",
)
INTERRUPTED_MESSAGE = "App was closed or backend restarted before this job finished."


def active_work_counts() -> dict[str, int]:
    placeholders = ", ".join("?" for _ in ACTIVE_STATUSES)

    with get_connection() as conn:
        active_jobs = conn.execute(
            f"SELECT COUNT(*) FROM jobs WHERE status IN ({placeholders})",
            ACTIVE_STATUSES,
        ).fetchone()[0]
        active_batches = conn.execute(
            f"SELECT COUNT(*) FROM batches WHERE status IN ({placeholders})",
            ACTIVE_STATUSES,
        ).fetchone()[0]

    return {
        "jobs": int(active_jobs),
        "batches": int(active_batches),
        "total": int(active_jobs) + int(active_batches),
    }


def stale_work_counts(
    exclude_job_ids: set[str] | None = None,
    exclude_batch_ids: set[str] | None = None,
) -> dict[str, int]:
    exclude_job_ids = exclude_job_ids or set()
    exclude_batch_ids = exclude_batch_ids or set()
    placeholders = ", ".join("?" for _ in STALE_WORK_STATUSES)

    with get_connection() as conn:
        jobs = [
            row["id"]
            for row in conn.execute(
                f"SELECT id, batch_id FROM jobs WHERE status IN ({placeholders})",
                STALE_WORK_STATUSES,
            ).fetchall()
            if row["id"] not in exclude_job_ids and row["batch_id"] not in exclude_batch_ids
        ]
        batches = [
            row["id"]
            for row in conn.execute(
                f"SELECT id FROM batches WHERE status IN ({placeholders})",
                STALE_WORK_STATUSES,
            ).fetchall()
            if row["id"] not in exclude_batch_ids
        ]

    return {
        "jobs": len(jobs),
        "batches": len(batches),
        "total": len(jobs) + len(batches),
    }


def mark_stale_work_interrupted(
    exclude_job_ids: set[str] | None = None,
    exclude_batch_ids: set[str] | None = None,
    reason: str = "startup",
) -> dict[str, int]:
    exclude_job_ids = exclude_job_ids or set()
    exclude_batch_ids = exclude_batch_ids or set()
    placeholders = ", ".join("?" for _ in STALE_WORK_STATUSES)
    now = utc_now()

    with get_connection() as conn:
        stale_jobs = [
            dict(row)
            for row in conn.execute(
                f"SELECT id, batch_id, status FROM jobs WHERE status IN ({placeholders})",
                STALE_WORK_STATUSES,
            ).fetchall()
            if row["id"] not in exclude_job_ids and row["batch_id"] not in exclude_batch_ids
        ]
        stale_batches = [
            dict(row)
            for row in conn.execute(
                f"SELECT id, status FROM batches WHERE status IN ({placeholders})",
                STALE_WORK_STATUSES,
            ).fetchall()
            if row["id"] not in exclude_batch_ids
        ]

        for job in stale_jobs:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, message = ?, error = NULL, progress_percent = 100, updated_at = ?
                WHERE id = ?
                """,
                ("interrupted", INTERRUPTED_MESSAGE, now, job["id"]),
            )

        for batch in stale_batches:
            conn.execute(
                """
                UPDATE batches
                SET status = ?, message = ?, progress_percent = 100, updated_at = ?
                WHERE id = ?
                """,
                ("interrupted", INTERRUPTED_MESSAGE, now, batch["id"]),
            )

        conn.commit()

    for job in stale_jobs:
        add_log(
            job_id=job["id"],
            level="WARNING",
            event="stale_job_repaired",
            message=(
                f"Stale job detected with persisted status '{job['status']}' during {reason}. "
                "Marked interrupted because no active in-memory worker exists."
            ),
        )

    for batch in stale_batches:
        add_log(
            batch_id=batch["id"],
            level="WARNING",
            event="stale_batch_repaired",
            message=(
                f"Stale batch detected with persisted status '{batch['status']}' during {reason}. "
                "Marked interrupted because no active in-memory worker exists."
            ),
        )

    if stale_jobs or stale_batches:
        add_log(
            level="WARNING",
            event="stale_work_repaired",
            message=(
                f"Repaired stale work during {reason}. "
                f"Jobs: {len(stale_jobs)}. Batches: {len(stale_batches)}."
            ),
        )

    return {
        "jobs": len(stale_jobs),
        "batches": len(stale_batches),
        "total": len(stale_jobs) + len(stale_batches),
    }


def clear_history() -> dict[str, int]:
    with get_connection() as conn:
        deleted_logs = conn.execute("DELETE FROM logs").rowcount
        deleted_jobs = conn.execute("DELETE FROM jobs").rowcount
        deleted_batches = conn.execute("DELETE FROM batches").rowcount
        conn.commit()

    return {
        "logs": deleted_logs if deleted_logs is not None else 0,
        "jobs": deleted_jobs if deleted_jobs is not None else 0,
        "batches": deleted_batches if deleted_batches is not None else 0,
    }
