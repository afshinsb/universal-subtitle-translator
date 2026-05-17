from app.routes.logs import log_summary, logs_view_context, present_log


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
