from app.config import ensure_directories, settings
from app.database import add_log, create_batch, create_job, init_db
from app.routes.logs import batch_logs, log_summary, logs_view_context, present_log


def test_present_log_categorizes_provider_token_usage_as_quiet():
    log = {
        "id": 1,
        "created_at": "2026-05-13T12:00:00+00:00",
        "level": "INFO",
        "event": "batch_tokens",
        "message": "Batch token usage.",
        "model": "gpt-test",
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150,
        "batch_number": 1,
        "batch_count": 2,
        "subtitle_start": 0,
        "subtitle_end": 10,
        "job_id": "job-123456",
        "batch_id": None,
    }

    presented = present_log(log)

    assert presented["category"] == "API/Provider"
    assert presented["severity"] == "info"
    assert presented["quiet"] is True
    assert presented["title"] == "Token usage recorded"


def test_log_summary_counts_useful_activity():
    logs = [
        {"level": "SUCCESS", "event": "job_completed", "total_tokens": 0},
        {"level": "INFO", "event": "media_file_skipped", "total_tokens": 0},
        {"level": "ERROR", "event": "job_failed", "total_tokens": 0},
        {"level": "INFO", "event": "batch_tokens", "input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
    ]

    summary = log_summary(logs)

    assert summary["translated"] == 1
    assert summary["skipped"] == 1
    assert summary["errors"] == 1
    assert summary["tokens"] == 150
    assert summary["visible_default"] == 3


def test_logs_view_context_keeps_export_urls():
    context = logs_view_context([], title="Job Logs abc", csv_url="/jobs/abc/logs.csv", json_url="/jobs/abc/logs.json")

    assert context["page_title"] == "Job Logs abc"
    assert context["csv_url"] == "/jobs/abc/logs.csv"
    assert context["json_url"] == "/jobs/abc/logs.json"


def test_present_log_categorizes_source_selection():
    log = {
        "id": 2,
        "created_at": "2026-05-13T12:00:00+00:00",
        "level": "INFO",
        "event": "source_subtitle_selected",
        "message": "External subtitle selected for Movie.mkv.",
        "model": "gpt-test",
        "job_id": "job-123456",
        "batch_id": "batch-123456",
    }

    presented = present_log(log)

    assert presented["category"] == "Extraction"
    assert presented["title"] == "Source subtitle selected"
    assert presented["quiet"] is False


def test_present_log_hides_routine_provider_usage_by_default():
    log = {
        "id": 3,
        "created_at": "2026-05-13T12:00:00+00:00",
        "level": "INFO",
        "event": "provider_request_completed",
        "message": "Provider request completed.",
        "model": "gpt-test",
        "total_tokens": 42,
    }

    presented = present_log(log)

    assert presented["category"] == "API/Provider"
    assert presented["quiet"] is True


def test_batch_logs_queries_batch_and_job_logs_without_global_limit(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"

    monkeypatch.setattr(settings, "data_dir", data_dir)
    monkeypatch.setattr(settings, "upload_dir", data_dir / "uploads")
    monkeypatch.setattr(settings, "output_dir", data_dir / "outputs")
    monkeypatch.setattr(settings, "temp_dir", data_dir / "temp")
    monkeypatch.setattr(settings, "database_path", data_dir / "app.db")

    ensure_directories()
    init_db()

    create_batch(
        batch_id="batch-1",
        folder_path=str(tmp_path / "media"),
        target_language="Persian",
        style="natural_conversational",
    )
    create_job(
        job_id="job-1",
        batch_id="batch-1",
        input_file="movie.en.srt",
        input_path=str(tmp_path / "movie.en.srt"),
        target_language="Persian",
        source_language="English",
        style="natural_conversational",
        model="test-model",
    )
    add_log(level="INFO", event="batch_old", message="old batch log", batch_id="batch-1")
    add_log(level="INFO", event="job_old", message="old job log", job_id="job-1")

    for index in range(1005):
        add_log(level="INFO", event="noise", message=f"noise {index}")

    events = {log["event"] for log in batch_logs("batch-1")}

    assert {"batch_old", "job_old"} <= events
