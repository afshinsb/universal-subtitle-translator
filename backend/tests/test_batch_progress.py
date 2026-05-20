from app.config import ensure_directories, settings
from app.database import create_batch, create_job, init_db, update_batch, update_job
from app.routes.batches import build_batch_status


def test_batch_progress_ignores_initially_skipped_jobs(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"

    monkeypatch.setattr(settings, "data_dir", data_dir)
    monkeypatch.setattr(settings, "upload_dir", data_dir / "uploads")
    monkeypatch.setattr(settings, "output_dir", data_dir / "outputs")
    monkeypatch.setattr(settings, "temp_dir", data_dir / "temp")
    monkeypatch.setattr(settings, "database_path", data_dir / "app.db")

    ensure_directories()
    init_db()

    create_batch(
        batch_id="batch-progress",
        folder_path=str(tmp_path / "movies"),
        target_language="Persian",
        style="natural_conversational",
    )
    update_batch("batch-progress", status="running", total_files=10)

    for index in range(8):
        create_job(
            job_id=f"job-skipped-{index}",
            batch_id="batch-progress",
            input_file=f"skipped-{index}.mkv",
            input_path=str(tmp_path / f"skipped-{index}.mkv"),
            target_language="Persian",
            source_language="Unknown",
            style="natural_conversational",
            model="test-model",
            status="skipped",
        )

    for index in range(2):
        create_job(
            job_id=f"job-ready-{index}",
            batch_id="batch-progress",
            input_file=f"ready-{index}.mkv",
            input_path=str(tmp_path / f"ready-{index}.mkv"),
            target_language="Persian",
            source_language="English",
            style="natural_conversational",
            model="test-model",
        )

    payload = build_batch_status("batch-progress")

    assert payload["batch"]["skipped_files"] == 8
    assert payload["progress_percent"] == 0

    update_job("job-ready-0", status="running", progress_percent=50)

    payload = build_batch_status("batch-progress")

    assert payload["progress_percent"] == 25
