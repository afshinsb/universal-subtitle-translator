"""Bounded, credential-free read models for the modern UI; no workers or queues."""

import re
import sqlite3
from pathlib import Path

from app.config import settings
from app.database import get_connection, utc_now
from app.services import (
    automation,
    daily_budget,
    download_guard,
    media_intake,
    resources,
)


STATES = {
    "queued",
    "running",
    "retry",
    "waiting_source",
    "waiting_media",
    "waiting_config",
    "waiting_budget",
    "waiting_intake",
    "done",
    "skipped",
    "failed",
    "cancelled",
    "active",
    "completed",
    "validation_pending",
    "waiting_stable",
    "waiting_import",
    "invalid_media",
    "preparation_failed",
    "translation_failed",
    "processing",
    "requested",
    "requested_approved",
    "request_declined",
    "downloading",
    "download_queued",
    "download_paused",
    "download_stalled",
    "download_failed",
    "import_failed",
    "import_rejected",
    "completed_not_imported",
    "ready",
    "extracting",
    "discovering_subtitles",
    "translating",
    "validation",
}


def init_schema():
    with get_connection() as c:
        for sql in (
            "CREATE INDEX IF NOT EXISTS ui_queue_order ON automation_queue(created_at,id)",
            "CREATE INDEX IF NOT EXISTS ui_jobs_time ON jobs(created_at)",
            "CREATE INDEX IF NOT EXISTS ui_logs_job ON logs(job_id,id)",
            "CREATE INDEX IF NOT EXISTS ui_intake_time ON media_intake(imported_at,id)",
            "CREATE INDEX IF NOT EXISTS ui_upstream_download ON upstream_activity(lower(download_id))",
        ):
            c.execute(sql)


def redacted(value):
    secrets = [settings.openai_api_key, automation.config()["webhook_token"]]

    def walk(item):
        if isinstance(item, str):
            for secret in secrets:
                if secret:
                    item = item.replace(secret, "[redacted]")
            return item
        if isinstance(item, dict):
            return {k: walk(v) for k, v in item.items()}
        if isinstance(item, list):
            return [walk(v) for v in item]
        return item

    return walk(value)


def pagination(domain="queue", page=1, state="active", search="", size=25):
    page = max(1, min(page, 100000))
    size = max(1, min(size, 50))
    search = search[:200]
    if state and state not in STATES and state != "all":
        raise ValueError("Unknown status filter")
    with get_connection() as c:
        where = []
        args = []
        if domain == "queue":
            table = "automation_queue q LEFT JOIN jobs j ON j.id=q.job_id"
            select = "q.*,j.progress_percent AS progress,j.message AS detail,j.model,j.translated_count,j.total_subtitles,j.status AS job_state"
            order = "q.created_at,q.id"
            status = "q.status"
            text = "q.video_path"
            if state == "active":
                where.append("q.status NOT IN ('done','skipped','cancelled')")
        elif domain == "history":
            table = "jobs q"
            select = "q.id,q.input_file,q.output_file,q.status,q.progress_percent AS progress,q.translated_count,q.total_subtitles,q.model,q.target_language,q.style,q.message,q.error,q.created_at,q.updated_at,q.batch_id"
            order = "q.created_at DESC,q.id"
            status = "q.status"
            text = "q.input_file"
        elif domain == "downloads":
            # Arr is authoritative. Do not double-count the same hash as qBit work.
            table = """(SELECT 'upstream:'||identity AS id,title,service,state,progress,path,error,updated_at,
                first_seen AS sort_time,media_id AS media_ids,download_id,NULL AS queue_id FROM upstream_activity a
                WHERE service!='qbit' OR NOT EXISTS(SELECT 1 FROM upstream_activity b WHERE b.service IN ('sonarr','radarr') AND lower(b.download_id)=lower(a.download_id))
                UNION ALL SELECT 'intake:'||i.id,i.title,i.service,
                CASE WHEN i.owner IS NOT NULL AND i.lease_until>strftime('%s','now') AND i.phase IS NOT NULL THEN i.phase WHEN q.status='running' THEN 'translating' WHEN q.status IN ('done','skipped') THEN 'completed' WHEN q.status IN ('failed','cancelled','waiting_budget','waiting_config') THEN q.status ELSE i.state END,
                NULL,i.video_path,i.error,i.updated_at,strftime('%s',i.imported_at),i.media_ids,i.download_id,i.queue_id
                FROM media_intake i LEFT JOIN automation_queue q ON q.id=i.queue_id) q"""
            select = "q.*"
            order = "q.sort_time DESC,q.id"
            status = "q.state"
            text = "(coalesce(q.title,'')||' '||coalesce(q.path,''))"
        else:
            raise ValueError("Unknown view")
        if state not in {"all", "", "active"}:
            where.append(status + "=?")
            args.append(state)
        if domain == "downloads" and state == "active":
            where.append(
                "q.state NOT IN ('completed','cancelled','superseded','imported','request_declined')"
            )
        if search:
            where.append(text + " LIKE ? ESCAPE '!' ")
            args.append(
                "%"
                + search.replace("!", "!!").replace("%", "!%").replace("_", "!_")
                + "%"
            )
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        count = c.execute("SELECT COUNT(*) FROM " + table + clause, args).fetchone()[0]
        page = min(page, max(1, (count + size - 1) // size))
        rows = [
            dict(r)
            for r in c.execute(
                "SELECT "
                + select
                + " FROM "
                + table
                + clause
                + " ORDER BY "
                + order
                + " LIMIT ? OFFSET ?",
                [*args, size, (page - 1) * size],
            )
        ]
        for row in rows:
            if domain == "queue":
                for hidden in ("owner", "lease_until", "signature"):
                    row.pop(hidden, None)
                row["name"] = Path(row["video_path"]).name
                row["model"] = row["model"] or settings.openai_model
                message = (row["detail"] or row["message"] or "").lower()
                row["phase"] = (
                    "extracting"
                    if "extract" in message and row["status"] == "running"
                    else "validation"
                    if "validat" in message and row["status"] == "running"
                    else "translating"
                    if row["status"] == "running"
                    else row["status"]
                )
                row["progress"] = row["progress"] or 0
                row["queue_position"] = (
                    c.execute(
                        "SELECT COUNT(*)+1 FROM automation_queue WHERE status='queued' AND (created_at<? OR (created_at=? AND id<?))",
                        (row["created_at"], row["created_at"], row["id"]),
                    ).fetchone()[0]
                    if row["status"] == "queued"
                    else None
                )
                log = c.execute(
                    "SELECT batch_number,batch_count FROM logs WHERE job_id=? AND batch_number IS NOT NULL ORDER BY id DESC LIMIT 1",
                    (row["job_id"],),
                ).fetchone()
                row["batch"] = log[0] if log else None
                batch_stats = c.execute(
                    "SELECT MAX(batch_count),COUNT(DISTINCT CASE WHEN event='batch_alignment_validated' THEN batch_number END) FROM logs WHERE job_id=?",
                    (row["job_id"],),
                ).fetchone()
                row["batch_count"] = batch_stats[0] or (log[1] if log else None)
                row["batches_completed"] = batch_stats[1]
            if domain == "downloads":
                match = re.search(
                    r"(?:Season[ ._-]*(\d+)|S(\d{1,2})E)",
                    row["path"] or row["title"] or "",
                    re.I,
                )
                row["group"] = (
                    (row["title"] or "Series")
                    + " · Season "
                    + str(int(match.group(1) or match.group(2))).zfill(2)
                    if match
                    else (row["service"] or "Import").title()
                )
                row["eligible"] = bool(row["queue_id"])
    if domain == "queue":
        usage = {}
        if daily_budget.ledger_path().is_file() and rows:
            with sqlite3.connect(
                "file:" + str(daily_budget.ledger_path()) + "?mode=ro", uri=True
            ) as c:
                ids = [r["id"] for r in rows]
                sql = (
                    "SELECT identity,SUM(actual),SUM(latency),SUM(input_tokens),SUM(output_tokens),SUM(reasoning_tokens),SUM(CASE WHEN actual IS NULL THEN bound ELSE 0 END) FROM provider_reservations WHERE identity IN ("
                    + ",".join("?" for _ in ids)
                    + ") GROUP BY identity"
                )
                usage = {r[0]: r[1:] for r in c.execute(sql, ids)}
        for r in rows:
            values = usage.get(r["id"], (0, 0, 0, 0, 0, 0))
            r.update(
                cost_usd=(values[0] or 0) / 1e9,
                latency=values[1] or 0,
                input_tokens=values[2] or 0,
                output_tokens=values[3] or 0,
                reasoning_tokens=values[4] or 0,
                reserved_usd=(values[5] or 0) / 1e9,
            )
            done = r["translated_count"] or 0
            total = r["total_subtitles"] or 0
            r["eta_seconds"] = (
                round(
                    r["latency"]
                    * (total - done)
                    / done
                    / max(1, settings.automation_batch_concurrency)
                )
                if done and total > done and r["latency"] > 0
                else None
            )
    return redacted(
        {
            "items": rows,
            "page": page,
            "pages": max(1, (count + size - 1) // size),
            "total": count,
            "size": size,
            "state": state,
            "search": search,
        }
    )


def snapshot():
    cfg = automation.config()
    queue = automation.counts()
    budget = daily_budget.status()
    budget["remaining_usd"] = max(
        0, budget["limit_usd"] - budget["consumed_usd"] - budget["reserved_usd"]
    )
    with get_connection() as c:
        intake = dict(
            c.execute(
                "SELECT state,COUNT(*) FROM media_intake GROUP BY state"
            ).fetchall()
        )
        upstream = dict(
            c.execute(
                "SELECT state,COUNT(*) FROM upstream_activity WHERE service IN ('sonarr','radarr') GROUP BY state"
            ).fetchall()
        )
        today = c.execute(
            "SELECT COUNT(*) FROM automation_queue WHERE status='done' AND substr(updated_at,1,10)=substr(?,1,10)",
            (utc_now(),),
        ).fetchone()[0]
        trend = [
            dict(r)
            for r in c.execute(
                "SELECT substr(updated_at,1,10) AS day,COUNT(*) AS count FROM automation_queue WHERE status='done' AND updated_at>=datetime('now','-6 days') GROUP BY day ORDER BY day"
            )
        ]
        activity = [
            dict(r)
            for r in c.execute(
                "SELECT id,level,event,message,created_at FROM logs ORDER BY id DESC LIMIT 8"
            )
        ]
    from app.routes.logs import human_title

    for entry in activity:
        entry["title"] = human_title(entry)
    upstream_attention = sum(
        upstream.get(k, 0)
        for k in (
            "download_failed",
            "download_stalled",
            "import_failed",
            "import_rejected",
        )
    )
    services = media_intake.snapshot()["services"]
    configured = media_intake.services()
    for service in services:
        service["status"] = (
            "Disabled"
            if not settings.media_intake_enabled
            else "Not configured"
            if service["service"] not in configured
            else "Retrying"
            if service["error"]
            else "Polling healthy"
            if service["next_run"]
            else "Waiting to poll"
        )
    state = {
        "upstream_attention": upstream_attention,
        "automation": {
            k: cfg.get(k)
            for k in (
                "enabled",
                "roots",
                "path_mappings",
                "scope_mode",
                "allowed_files",
                "discovery_mode",
            )
        },
        "model": settings.openai_model,
        "reasoning": settings.openai_reasoning_effort or "default",
        "queue": queue,
        # A bounded live read model, independent of the paginated history view.
        "active_media": pagination("queue", state="running", size=6)["items"],
        "intake": intake,
        "upstream": upstream,
        "pending": sum(
            v
            for k, v in queue.items()
            if k not in {"done", "skipped", "cancelled", "running", "failed"}
        ),
        "blocked": upstream_attention
        + sum(queue.get(k, 0) for k in ("failed", "waiting_budget", "waiting_config"))
        + sum(
            intake.get(k, 0)
            for k in ("invalid_media", "preparation_failed", "translation_failed")
        ),
        "completed_today": today,
        "trend": trend,
        "resources": resources.status(),
        "budget": budget,
        "guard": download_guard.snapshot(),
        "activity": activity,
        "services": services,
        "server_time": utc_now(),
    }
    return redacted(state)
