"""Persistent single-worker automation. No service hooks are configured here."""
import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path
from uuid import uuid4

from app.config import settings
from app.database import get_connection, create_job, get_job, utc_now
from app.services.ffmpeg_service import list_text_subtitle_streams, extract_subtitle
from app.services.media_scanner import VIDEO_EXTENSIONS, sidecar_subtitles, subtitle_language_from_name
from app.services.subtitle_io import read_srt
from app.services.job_runner import run_translation_job, register_active_job, unregister_active_job, cancel_job

logger = logging.getLogger(__name__)
LEASE_SECONDS = 90
RETRY_LIMIT = 5
WAIT_SECONDS = 60


def init_schema():
    with get_connection() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS automation_config (
            id INTEGER PRIMARY KEY CHECK (id=1), value TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS automation_queue (
            id TEXT PRIMARY KEY, video_path TEXT NOT NULL UNIQUE,
            origin TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
            attempts INTEGER NOT NULL DEFAULT 0, next_run REAL NOT NULL DEFAULT 0,
            lease_until REAL NOT NULL DEFAULT 0, owner TEXT,
            message TEXT NOT NULL DEFAULT '', job_id TEXT, output_path TEXT,
            signature TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        conn.execute("CREATE INDEX IF NOT EXISTS automation_due ON automation_queue(status, next_run)")
        root = settings.media_root / "fixtures" if settings.media_root else None
        config = {"enabled": False, "roots": [str(root)] if root and root.is_dir() else [],
                  "path_mappings": {}, "webhook_token": secrets.token_urlsafe(32)}
        conn.execute("INSERT OR IGNORE INTO automation_config VALUES (1, ?)", (json.dumps(config),))


def config():
    with get_connection() as conn:
        return json.loads(conn.execute("SELECT value FROM automation_config WHERE id=1").fetchone()[0])


def permitted_file(path, cfg=None):
    cfg = cfg or config()
    resolved = Path(path).resolve()
    if cfg.get("scope_mode", "libraries") == "selected_files":
        if str(resolved) not in cfg.get("allowed_files", []):
            return False
    if settings.media_root and not settings.automation_real_library_processing:
        fixtures = (settings.media_root / "fixtures").resolve()
        if resolved != fixtures and fixtures not in resolved.parents:
            return False
    return True


def save_scope(paths):
    cfg = config()
    if len(paths) > 50:
        raise ValueError("Selected-file scope is limited to 50 videos.")
    checked = [str(checked_path(value, cfg)) for value in paths]
    if any(Path(value).suffix.lower() not in VIDEO_EXTENSIONS for value in checked):
        raise ValueError("Scope must list exact supported video file paths.")
    cfg.update(scope_mode="selected_files", allowed_files=sorted(set(checked)))
    with get_connection() as conn:
        conn.execute("UPDATE automation_config SET value=? WHERE id=1", (json.dumps(cfg),))
    return cfg


def pause():
    cfg = config()
    cfg["enabled"] = False
    with get_connection() as conn:
        conn.execute("UPDATE automation_config SET value=? WHERE id=1", (json.dumps(cfg),))
        active = conn.execute("SELECT job_id FROM automation_queue WHERE status='running' AND job_id IS NOT NULL").fetchall()
    for row in active:
        cancel_job(row["job_id"])
    return len(active)


def checked_path(value, cfg=None):
    cfg = cfg or config()
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("An absolute media path is required.")
    path = path.resolve()
    roots = [Path(root).resolve() for root in cfg["roots"]]
    if not any(path == root or root in path.parents for root in roots):
        raise ValueError("Path is outside the configured automation libraries.")
    if settings.media_root:
        media = settings.media_root.resolve()
        if path != media and media not in path.parents:
            raise ValueError("Path is outside MEDIA_ROOT.")
    # Real-library automation requires a separately authorized deployment opt-in.
    if settings.dev_mode and settings.media_root and not settings.automation_allow_library_writes:
        fixtures = (settings.media_root / "fixtures").resolve()
        if path != fixtures and fixtures not in path.parents:
            raise ValueError("Development automation is restricted to writable fixtures.")
    return path


def save_config(enabled, roots, mappings):
    cfg = config()
    candidate = {**cfg, "roots": roots}
    normalized = []
    for value in roots:
        root = checked_path(value, candidate)
        if not root.is_dir():
            raise ValueError("Automation libraries must be existing directories.")
        normalized.append(str(root))
    if enabled and not normalized:
        raise ValueError("Choose a writable automation library before enabling.")
    if not isinstance(mappings, dict) or not all(
        isinstance(k, str) and isinstance(v, str) and Path(k).is_absolute() and Path(v).is_absolute()
        for k, v in mappings.items()
    ):
        raise ValueError("Path mappings must map absolute source directories to absolute destination directories.")
    for destination in mappings.values():
        checked_path(destination, {**candidate, "roots": normalized})
    cfg.update(enabled=bool(enabled), roots=normalized, path_mappings=mappings)
    with get_connection() as conn:
        conn.execute("UPDATE automation_config SET value=? WHERE id=1", (json.dumps(cfg),))
    return cfg


def map_path(value):
    cfg = config()
    source = Path(value)
    if not source.is_absolute():
        raise ValueError("Event media path must be absolute.")
    # Match complete directory components, longest mapping first.
    for prefix, destination in sorted(cfg["path_mappings"].items(), key=lambda pair: len(pair[0]), reverse=True):
        try:
            source = Path(destination) / source.relative_to(Path(prefix))
            break
        except ValueError:
            continue
    return checked_path(str(source), cfg)


def signature(path):
    try:
        stat = path.stat()
        return f"{stat.st_size}:{stat.st_mtime_ns}"
    except FileNotFoundError:
        return ""


def enqueue(value, origin="scan"):
    path = checked_path(value)
    if not permitted_file(path):
        raise ValueError("This video is outside the selected scope or real-library processing is disabled.")
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        raise ValueError("Event path must identify a supported video file.")
    now = utc_now()
    version = signature(path)
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM automation_queue WHERE video_path=?", (str(path),)).fetchone()
        if row:
            # A new media import can revive a failed job; ordinary scans cannot.
            changed = version and version != row["signature"]
            wake = row["status"] in {"waiting_media", "waiting_source", "waiting_config"}
            if row["status"] != "running" and (changed or wake):
                conn.execute("""UPDATE automation_queue SET status='queued', next_run=0,
                    attempts=CASE WHEN ? THEN 0 ELSE attempts END, signature=?, origin=?,
                    message='Media/subtitle event received', updated_at=? WHERE id=?""",
                    (changed, version, origin, now, row["id"]))
            return dict(conn.execute("SELECT * FROM automation_queue WHERE id=?", (row["id"],)).fetchone())
        item_id = uuid4().hex
        conn.execute("""INSERT INTO automation_queue
            (id,video_path,origin,signature,created_at,updated_at) VALUES (?,?,?,?,?,?)""",
            (item_id, str(path), origin, version, now, now))
        return dict(conn.execute("SELECT * FROM automation_queue WHERE id=?", (item_id,)).fetchone())


def list_queue(limit=200):
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM automation_queue ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()]


def counts():
    with get_connection() as conn:
        return dict(conn.execute("SELECT status, COUNT(*) FROM automation_queue GROUP BY status").fetchall())


def retry(item_id):
    with get_connection() as conn:
        row = conn.execute("SELECT status FROM automation_queue WHERE id=?", (item_id,)).fetchone()
        if not row:
            raise ValueError("Queue item not found.")
        if row["status"] in {"running", "done", "skipped"}:
            raise ValueError("Active/completed items cannot be retried or overwritten.")
        conn.execute("""UPDATE automation_queue SET status='queued',attempts=0,next_run=0,
            message='Retry requested', updated_at=? WHERE id=? AND status NOT IN ('running','done','skipped')""",
            (utc_now(), item_id))


def claim(item_id=None):
    now = time.time()
    cfg = config()
    allowed = cfg.get("allowed_files", []) if cfg.get("scope_mode") == "selected_files" else None
    if allowed is not None:
        allowed = [value for value in allowed if permitted_file(value, cfg)]
    if allowed is not None and not allowed:
        return None
    scope_sql = ""
    scope_args = []
    if allowed is not None:
        scope_sql = " AND video_path IN (" + ",".join("?" for _ in allowed) + ")"
        scope_args = allowed
    elif settings.media_root and not settings.automation_real_library_processing:
        scope_sql = " AND video_path LIKE ? ESCAPE '!'"
        prefix = str((settings.media_root / "fixtures").resolve()) + "/"
        scope_args = [prefix.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"]
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("""UPDATE automation_queue SET status='queued',owner=NULL,
            message='Recovered expired worker lease' WHERE status='running' AND lease_until<?""", (now,))
        row = conn.execute("""SELECT * FROM automation_queue
            WHERE status IN ('queued','retry','waiting_media','waiting_source','waiting_config')
            AND next_run<=? AND (? IS NULL OR id=?)""" + scope_sql + " ORDER BY next_run,created_at LIMIT 1",
            [now, item_id, item_id, *scope_args]).fetchone()
        if not row:
            return None
        if not permitted_file(row["video_path"]):
            # Excluded rows remain pending, without claiming or exhausting retries.
            return None
        owner = uuid4().hex
        conn.execute("""UPDATE automation_queue SET status='running',owner=?,lease_until=?,
            updated_at=? WHERE id=?""", (owner, now + LEASE_SECONDS, utc_now(), row["id"]))
        return dict(conn.execute("SELECT * FROM automation_queue WHERE id=?", (row["id"],)).fetchone())


def finish(item, status, message, delay=0, **fields):
    fields.update(status=status, message=message, next_run=time.time()+delay,
                  lease_until=0, owner=None, updated_at=utc_now())
    with get_connection() as conn:
        conn.execute("UPDATE automation_queue SET " + ", ".join(f"{name}=?" for name in fields)
                     + " WHERE id=? AND owner=?", [*fields.values(), item["id"], item["owner"]])


def select_source(video, item_id):
    """Reuse proven sidecar-first English selection; exclude forced/commentary."""
    candidates = []
    for path in sidecar_subtitles(video.parent, video.stem):
        if subtitle_language_from_name(path, video.stem) != "en":
            continue
        flags = path.stem[len(video.stem):].lower().split(".")
        if any(flag in {"forced", "comment", "commentary"} for flag in flags):
            continue
        candidates.append((any(flag in {"hi", "sdh", "cc"} for flag in flags), str(path), path))
    for _, _, path in sorted(candidates):
        try:
            if any(cue.text.strip() for cue in read_srt(path)):
                return path
        except RuntimeError:
            logger.warning("English sidecar is incomplete; waiting for another candidate.")
    streams = [stream for stream in list_text_subtitle_streams(video)
               if stream["language"] in {"eng", "en"} and not stream["forced"] and not stream["comment"]]
    if not streams:
        return None
    chosen = sorted(streams, key=lambda stream: (bool(stream.get("hearing_impaired")), not stream["default"], stream["index"]))[0]
    directory = settings.temp_dir / "automation" / item_id
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / (video.stem + ".en.srt")
    output.unlink(missing_ok=True)
    extract_subtitle(video, output, stream_index=chosen["index"])
    return output


def process(item):
    path = checked_path(item["video_path"])
    if not permitted_file(path):
        finish(item, "waiting_config", "Outside the permitted processing scope", WAIT_SECONDS)
        return
    if not path.is_file():
        finish(item, "waiting_media", "Waiting for imported media", WAIT_SECONDS)
        return
    output = path.with_suffix(".fa.srt")
    if output.exists():
        # Never replace user subtitles or partial/invalid existing files silently.
        cues = read_srt(output)
        if not cues or any(not cue.text.strip() for cue in cues):
            raise RuntimeError("Existing Persian subtitle is incomplete; review it manually.")
        finish(item, "skipped", "Existing Persian subtitle preserved", output_path=str(output))
        return
    if not os.access(path.parent, os.W_OK):
        finish(item, "waiting_config", "Media directory is read-only", WAIT_SECONDS)
        return
    source = select_source(path, item["id"])
    if source is None:
        finish(item, "waiting_source", "Waiting for English subtitles from Bazarr", WAIT_SECONDS)
        return
    if not settings.openai_api_key:
        finish(item, "waiting_config", "Provider key is not configured; no request made", WAIT_SECONDS)
        return
    attempt = item["attempts"] + 1
    job_id = uuid4().hex
    with get_connection() as conn:
        conn.execute("""UPDATE automation_queue SET attempts=?,job_id=? WHERE id=? AND owner=?""",
                     (attempt, job_id, item["id"], item["owner"]))
    create_job(job_id, source.name, str(source), "Persian", "English",
               "natural_conversational", settings.openai_model)
    def before_publish():
        if not config()["enabled"] or not permitted_file(path):
            raise RuntimeError("Automation paused or processing scope changed.")
        checked_path(str(path))
        with get_connection() as conn:
            owned = conn.execute("SELECT owner,lease_until FROM automation_queue WHERE id=?",
                                 (item["id"],)).fetchone()
        if owned["owner"] != item["owner"] or owned["lease_until"] <= time.time():
            raise RuntimeError("Worker lease was lost before subtitle publication.")

    register_active_job(job_id)
    try:
        run_translation_job(job_id, str(source), source.name, "Persian", "natural_conversational",
                            output_path_override=str(output), overwrite_existing=False, preserve_cue_ids=True, before_publish=before_publish, check_automation=before_publish)
    finally:
        unregister_active_job(job_id)
    job = get_job(job_id)
    if job["status"] != "done":
        raise RuntimeError(job.get("error") or job.get("message") or "Translation did not complete.")
    # The engine validates every cue before atomically publishing the output.
    finish(item, "done", "Persian subtitles completed", output_path=str(output))


def process_one(item_id=None):
    if not config()["enabled"]:
        return False
    item = claim(item_id)
    if not item:
        return False
    heartbeat_stop = threading.Event()

    def heartbeat():
        while not heartbeat_stop.wait(15):
            with get_connection() as conn:
                conn.execute("UPDATE automation_queue SET lease_until=? WHERE id=? AND owner=?",
                             (time.time()+LEASE_SECONDS, item["id"], item["owner"]))
    heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()
    try:
        process(item)
    except Exception as exc:
        with get_connection() as conn:
            row = conn.execute("SELECT attempts FROM automation_queue WHERE id=?", (item["id"],)).fetchone()
        attempts = max(item["attempts"] + 1, row["attempts"])
        finish(item, "failed" if attempts >= RETRY_LIMIT else "retry",
               f"{type(exc).__name__}: {exc}", min(3600, 30 * 2 ** min(attempts-1, 7)), attempts=attempts)
        logger.warning("Automation processing deferred: %s", type(exc).__name__)
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=2)
    return True


def reconcile():
    """Recover missed imports/events and delayed subtitles without modifying services."""
    found = 0
    cfg = config()
    if cfg.get("scope_mode") == "selected_files":
        for value in cfg.get("allowed_files", []):
            if permitted_file(value, cfg):
                enqueue(value, "reconciliation")
                found += 1
        return found
    for root in cfg["roots"]:
        checked_path(root)
        for directory, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not (Path(directory) / d).is_symlink())
            for name in sorted(names):
                path = Path(directory) / name
                if path.suffix.lower() in VIDEO_EXTENSIONS and not path.is_symlink() and permitted_file(path, cfg):
                    enqueue(str(path), "reconciliation")
                    found += 1
    return found


class Worker:
    def __init__(self):
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self.run, name="subtitle-automation", daemon=True)
        self.thread.start()

    def run(self):
        next_scan = 0
        while not self.stop_event.is_set():
            try:
                if config()["enabled"]:
                    if time.time() >= next_scan:
                        reconcile()
                        next_scan = time.time() + WAIT_SECONDS
                    if process_one():
                        continue
            except Exception:
                logger.exception("Automation worker error; retrying after polling delay")
            self.stop_event.wait(2)

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)


worker = Worker()
