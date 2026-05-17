from app.config import ensure_directories, settings
from app.database import create_batch, create_job, get_batch, get_job, init_db, list_jobs, list_logs
from app.services.cleanup import cleanup_history_and_app_files
from app.services.job_runner import (
    ACTIVE_BATCHES,
    ACTIVE_JOBS,
    CANCELLED_BATCHES,
    CANCELLED_JOBS,
    active_runtime_counts,
    cancel_job,
    repair_stale_work,
)


def test_cleanup_clears_history_and_only_app_managed_files(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    upload_dir = data_dir / "uploads"
    output_dir = data_dir / "outputs"
    temp_dir = data_dir / "temp"
    external_dir = tmp_path / "movies"

    monkeypatch.setattr(settings, "data_dir", data_dir)
    monkeypatch.setattr(settings, "upload_dir", upload_dir)
    monkeypatch.setattr(settings, "output_dir", output_dir)
    monkeypatch.setattr(settings, "temp_dir", temp_dir)
    monkeypatch.setattr(settings, "database_path", data_dir / "app.db")

    ensure_directories()
    init_db()

    upload_file = upload_dir / "job-1" / "movie.en.srt"
    output_file = output_dir / "movie.fa.srt"
    temp_file = temp_dir / "extract" / "embedded.srt"
    external_file = external_dir / "movie.fa.srt"

    upload_file.parent.mkdir(parents=True)
    temp_file.parent.mkdir(parents=True)
    external_dir.mkdir(parents=True)
    upload_file.write_text("upload", encoding="utf-8")
    output_file.write_text("output", encoding="utf-8")
    temp_file.write_text("temp", encoding="utf-8")
    external_file.write_text("external", encoding="utf-8")

    create_job(
        job_id="job-1",
        input_file="movie.en.srt",
        input_path=str(upload_file),
        target_language="Persian",
        source_language="English",
        style="natural_conversational",
        model="test-model",
        status="done",
        output_file=external_file.name,
        output_path=str(external_file),
    )

    summary = cleanup_history_and_app_files()

    assert summary["files_deleted"] == 3
    assert summary["folders_cleaned"] == 3
    assert not upload_file.exists()
    assert not output_file.exists()
    assert not temp_file.exists()
    assert external_file.exists()
    assert list_jobs() == []
    assert any(log["event"] == "cleanup_completed" for log in list_logs())


def test_startup_repair_marks_persisted_active_work_interrupted(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"

    monkeypatch.setattr(settings, "data_dir", data_dir)
    monkeypatch.setattr(settings, "upload_dir", data_dir / "uploads")
    monkeypatch.setattr(settings, "output_dir", data_dir / "outputs")
    monkeypatch.setattr(settings, "temp_dir", data_dir / "temp")
    monkeypatch.setattr(settings, "database_path", data_dir / "app.db")

    ACTIVE_JOBS.clear()
    ACTIVE_BATCHES.clear()
    CANCELLED_JOBS.clear()
    CANCELLED_BATCHES.clear()

    ensure_directories()
    init_db()

    create_batch(
        batch_id="batch-stale",
        folder_path=str(tmp_path / "movies"),
        target_language="Persian",
        style="natural_conversational",
    )
    create_job(
        job_id="job-stale",
        batch_id="batch-stale",
        input_file="movie.en.srt",
        input_path=str(tmp_path / "movie.en.srt"),
        target_language="Persian",
        source_language="English",
        style="natural_conversational",
        model="test-model",
        status="running",
    )

    assert active_runtime_counts() == {"jobs": 0, "batches": 0, "total": 0}

    repaired = repair_stale_work(reason="test startup")

    assert repaired == {"jobs": 1, "batches": 1, "total": 2}
    assert get_job("job-stale")["status"] == "interrupted"
    assert get_batch("batch-stale")["status"] == "interrupted"
    assert "backend restarted" in get_job("job-stale")["message"]
    assert any(log["event"] == "stale_work_repaired" for log in list_logs())


def test_cancel_stale_job_marks_interrupted_immediately(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"

    monkeypatch.setattr(settings, "data_dir", data_dir)
    monkeypatch.setattr(settings, "upload_dir", data_dir / "uploads")
    monkeypatch.setattr(settings, "output_dir", data_dir / "outputs")
    monkeypatch.setattr(settings, "temp_dir", data_dir / "temp")
    monkeypatch.setattr(settings, "database_path", data_dir / "app.db")

    ACTIVE_JOBS.clear()
    ACTIVE_BATCHES.clear()
    CANCELLED_JOBS.clear()
    CANCELLED_BATCHES.clear()

    ensure_directories()
    init_db()

    create_job(
        job_id="job-cancel-stale",
        input_file="movie.en.srt",
        input_path=str(tmp_path / "movie.en.srt"),
        target_language="Persian",
        source_language="English",
        style="natural_conversational",
        model="test-model",
        status="cancel_requested",
    )

    cancel_job("job-cancel-stale")

    job = get_job("job-cancel-stale")

    assert job["status"] == "interrupted"
    assert job["progress_percent"] == 100
    assert "job-cancel-stale" not in CANCELLED_JOBS
