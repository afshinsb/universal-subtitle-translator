from pathlib import Path
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time

from app.config import settings
from app.database import (
    create_job,
    get_job,
    update_job,
    get_batch,
    update_batch,
    list_jobs_by_batch,
    add_log,
    mark_stale_work_interrupted,
    stale_work_counts,
)
from app.models import language_code
from app.services.subtitle_io import (
    read_srt,
    write_srt,
    make_output_filename,
    batch_subtitles,
    wrap_subtitle_text,
)
from app.services.ffmpeg_service import extract_subtitle
from app.services.language_detector import detect_subtitle_language
from app.services.media_scanner import (
    DEFAULT_SOURCE_PREFERENCE,
    TARGET_SUBTITLE_EXISTS_REASON,
    VIDEO_EXTENSIONS,
    inspect_media_file,
    scan_media_folder,
)
from app.services.translator import translate_batch
from app.services.validator import validate_subtitles

CANCELLED_BATCHES: set[str] = set()
CANCELLED_JOBS: set[str] = set()
ACTIVE_BATCHES: set[str] = set()
ACTIVE_JOBS: set[str] = set()
ACTIVE_LOCK = threading.RLock()
TERMINAL_STATUSES = {"done", "failed", "cancelled", "skipped", "interrupted"}


class CancelledError(RuntimeError):
    pass


def register_active_job(job_id: str) -> None:
    with ACTIVE_LOCK:
        ACTIVE_JOBS.add(job_id)


def unregister_active_job(job_id: str) -> None:
    with ACTIVE_LOCK:
        ACTIVE_JOBS.discard(job_id)


def register_active_batch(batch_id: str) -> None:
    with ACTIVE_LOCK:
        ACTIVE_BATCHES.add(batch_id)


def unregister_active_batch(batch_id: str) -> None:
    with ACTIVE_LOCK:
        ACTIVE_BATCHES.discard(batch_id)


def active_runtime_ids() -> tuple[set[str], set[str]]:
    with ACTIVE_LOCK:
        return set(ACTIVE_JOBS), set(ACTIVE_BATCHES)


def active_runtime_counts() -> dict[str, int]:
    jobs, batches = active_runtime_ids()

    return {
        "jobs": len(jobs),
        "batches": len(batches),
        "total": len(jobs) + len(batches),
    }


def stale_runtime_counts() -> dict[str, int]:
    jobs, batches = active_runtime_ids()
    return stale_work_counts(exclude_job_ids=jobs, exclude_batch_ids=batches)


def repair_stale_work(reason: str = "startup") -> dict[str, int]:
    jobs, batches = active_runtime_ids()
    return mark_stale_work_interrupted(
        exclude_job_ids=jobs,
        exclude_batch_ids=batches,
        reason=reason,
    )


def is_batch_cancelled(batch_id: str) -> bool:
    return batch_id in CANCELLED_BATCHES


def is_job_cancelled(job_id: str) -> bool:
    return job_id in CANCELLED_JOBS


def is_cancelled(job_id: str | None = None, batch_id: str | None = None) -> bool:
    return bool((job_id and is_job_cancelled(job_id)) or (batch_id and is_batch_cancelled(batch_id)))


def check_cancelled(job_id: str | None = None, batch_id: str | None = None) -> None:
    if is_cancelled(job_id=job_id, batch_id=batch_id):
        raise CancelledError("Cancellation requested.")


def friendly_error_message(error: Exception | str) -> str:
    text = str(error)
    lowered = text.lower()

    if "openai_api_key" in lowered or "api key" in lowered:
        return "OpenAI API key is missing or invalid. Check OPENAI_API_KEY in your .env file."

    if "insufficient_quota" in lowered or "quota" in lowered or "billing" in lowered:
        return "The translation provider reported a quota or billing problem. Check your OpenAI account."

    if "unauthorized" in lowered or "401" in lowered or "authentication" in lowered:
        return "The translation provider rejected the request. Check your API key and model access."

    if "rate limit" in lowered or "429" in lowered:
        return "The translation provider rate-limited the request. Wait a moment and try again."

    if "timed out" in lowered and ("openai" in lowered or "provider" in lowered or "api" in lowered):
        return "The translation provider timed out. Try again or increase OPENAI_TIMEOUT_SECONDS."

    if "connection" in lowered and ("openai" in lowered or "provider" in lowered or "api" in lowered):
        return "Could not reach the translation provider. Check the network connection and provider status."

    if "ffmpeg" in lowered and "timed out" in lowered:
        return "FFmpeg timed out while processing this media file."

    if "ffprobe" in lowered and "timed out" in lowered:
        return "FFprobe timed out while inspecting this media file."

    if "no extractable text subtitle" in lowered:
        return "No extractable text subtitle track was found in this video."

    if "output already exists" in lowered:
        return "The target subtitle already exists. Enable overwrite if you want to replace it."

    if "invalid" in lowered and ("srt" in lowered or "subrip" in lowered):
        return "The subtitle file appears to be malformed or unreadable."

    if "no readable subtitle text" in lowered:
        return "The subtitle file does not contain readable subtitle text."

    if "unicode" in lowered or "codec can't decode" in lowered:
        return "The subtitle file could not be read with the supported text encodings."

    if "permission denied" in lowered or "access is denied" in lowered:
        return "The app does not have permission to read or write one of the required files."

    return text


def elapsed_seconds(started_at: float) -> float:
    return round(time.monotonic() - started_at, 2)


def estimated_provider_cost(input_tokens: int | None, output_tokens: int | None) -> float:
    return (
        ((input_tokens or 0) / 1_000_000) * settings.openai_input_cost_per_1m
        + ((output_tokens or 0) / 1_000_000) * settings.openai_output_cost_per_1m
    )


def provider_cost_text(input_tokens: int | None, output_tokens: int | None) -> str:
    if not settings.openai_input_cost_per_1m and not settings.openai_output_cost_per_1m:
        return "estimated cost not configured"

    return f"estimated cost ${estimated_provider_cost(input_tokens, output_tokens):.4f}"


def count_subtitle_items(path: Path) -> int:
    subs = read_srt(path)
    return len([sub for sub in subs if sub.text.strip()])


def batch_file_concurrency_limit() -> int:
    return max(1, min(settings.batch_file_concurrency, 10))


def normalize_concurrency(value: int | None) -> int:
    if value is None:
        return batch_file_concurrency_limit()

    return max(1, min(int(value), 10))


def cancel_batch(batch_id: str) -> None:
    with ACTIVE_LOCK:
        is_active = batch_id in ACTIVE_BATCHES

    if not is_active:
        repair_stale_work(reason="batch cancel")
        add_log(
            batch_id=batch_id,
            level="WARNING",
            event="stale_batch_repaired",
            message="Cancel requested for a batch with no active worker. Marked stale work interrupted immediately.",
            model=settings.openai_model,
        )
        return

    CANCELLED_BATCHES.add(batch_id)
    impacted_jobs = [
        job for job in list_jobs_by_batch(batch_id)
        if job["status"] in {"queued", "running"}
    ]

    update_batch(
        batch_id,
        status="cancel_requested",
        message="Canceling... Active provider requests may finish before stopping.",
    )

    add_log(
        batch_id=batch_id,
        level="WARNING",
        event="batch_cancel_requested",
        message=(
            f"Cancellation requested for batch. "
            f"{len(impacted_jobs)} queued/running jobs will stop at safe checkpoints."
        ),
        model=settings.openai_model,
    )

    for job in impacted_jobs:
        CANCELLED_JOBS.add(job["id"])

        update_job(
            job["id"],
            status="cancel_requested",
            message="Canceling...",
        )

    def enforce_batch_cancel_timeout() -> None:
        time.sleep(max(1, settings.cancel_timeout_seconds))

        if batch_id not in CANCELLED_BATCHES:
            return

        with ACTIVE_LOCK:
            still_active = batch_id in ACTIVE_BATCHES

        if not still_active:
            return

        update_batch(
            batch_id,
            status="interrupted",
            message="Cancel timed out. Marked interrupted; no further work will be scheduled.",
            progress_percent=100,
        )

        for job in list_jobs_by_batch(batch_id):
            if job["status"] in {"queued", "running", "cancel_requested", "canceling"}:
                update_job(
                    job["id"],
                    status="interrupted",
                    message="Cancel timed out. Marked interrupted; no further work will be scheduled.",
                    progress_percent=100,
                )

        add_log(
            batch_id=batch_id,
            level="WARNING",
            event="batch_cancel_timeout",
            message=(
                f"Cancel timeout after {settings.cancel_timeout_seconds}s. "
                "Marked batch interrupted while waiting for workers to reach safe checkpoints."
            ),
            model=settings.openai_model,
        )

    threading.Thread(target=enforce_batch_cancel_timeout, daemon=True).start()


def cancel_job(job_id: str) -> None:
    job = get_job(job_id)

    if job and job["status"] in TERMINAL_STATUSES:
        return

    CANCELLED_JOBS.add(job_id)

    with ACTIVE_LOCK:
        is_active = job_id in ACTIVE_JOBS

    if not is_active:
        update_job(
            job_id,
            status="interrupted",
            message="App was closed or backend restarted before this job finished.",
            progress_percent=100,
        )
        CANCELLED_JOBS.discard(job_id)
        add_log(
            job_id=job_id,
            level="WARNING",
            event="stale_job_repaired",
            message="Cancel requested for a job with no active worker. Marked interrupted immediately.",
            model=settings.openai_model,
        )
        return

    update_job(
        job_id,
        status="cancel_requested",
        message="Canceling... Active provider requests may finish before stopping.",
    )

    add_log(
        job_id=job_id,
        level="WARNING",
        event="job_cancel_requested",
        message="Cancellation requested. The job will stop after the current safe checkpoint or provider response.",
        model=settings.openai_model,
    )

    def enforce_cancel_timeout() -> None:
        time.sleep(max(1, settings.cancel_timeout_seconds))

        if job_id not in CANCELLED_JOBS:
            return

        current = get_job(job_id)

        if not current or current["status"] in TERMINAL_STATUSES:
            return

        with ACTIVE_LOCK:
            still_active = job_id in ACTIVE_JOBS

        if not still_active:
            return

        update_job(
            job_id,
            status="interrupted",
            message="Cancel timed out. Marked interrupted; no further work will be scheduled.",
            progress_percent=100,
        )

        add_log(
            job_id=job_id,
            level="WARNING",
            event="job_cancel_timeout",
            message=(
                f"Cancel timeout after {settings.cancel_timeout_seconds}s. "
                "Marked job interrupted while waiting for the worker to reach a safe checkpoint."
            ),
            model=settings.openai_model,
        )

    threading.Thread(target=enforce_cancel_timeout, daemon=True).start()


def mark_job_cancelled(job_id: str, message: str = "Canceled.") -> None:
    current = get_job(job_id)

    if current and current["status"] == "interrupted":
        return

    update_job(
        job_id,
        status="cancelled",
        message=message,
        progress_percent=100,
    )


def get_batch_range(batch: list[dict]) -> tuple[int | None, int | None]:
    if not batch:
        return None, None

    indexes = [item["index"] for item in batch]
    return min(indexes), max(indexes)


def translate_batch_with_repair(
    job_id: str,
    batch: list[dict],
    source_language: str,
    target_language: str,
    style: str,
    batch_number: int,
    batch_count: int,
    cancel_check=None,
) -> dict[int, str]:
    if cancel_check:
        cancel_check()

    start_index, end_index = get_batch_range(batch)

    request_started_at = time.monotonic()
    result = translate_batch(
        batch=batch,
        target_language=target_language,
        style=style,
        source_language=source_language,
    )
    request_duration = elapsed_seconds(request_started_at)

    if cancel_check:
        cancel_check()

    if result.retry_attempted:
        add_log(
            job_id=job_id,
            level="WARNING",
            event="provider_retry_attempted",
            message=(
                f"Provider retry used for batch {batch_number}/{batch_count}. "
                f"Reason: {result.retry_reason}"
            ),
            model=settings.openai_model,
            batch_number=batch_number,
            batch_count=batch_count,
            subtitle_start=start_index,
            subtitle_end=end_index,
        )

    add_log(
        job_id=job_id,
        level="INFO",
        event="provider_request_completed",
        message=(
            f"Provider request completed for batch {batch_number}/{batch_count} "
            f"in {request_duration}s. Items: {len(batch)}. "
            f"Tokens: {result.total_tokens} total "
            f"({result.input_tokens} in, {result.output_tokens} out). "
            f"Attempts: {result.attempts}. {provider_cost_text(result.input_tokens, result.output_tokens)}."
        ),
        model=settings.openai_model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        total_tokens=result.total_tokens,
        batch_number=batch_number,
        batch_count=batch_count,
        subtitle_start=start_index,
        subtitle_end=end_index,
    )

    translated = result.translations

    missing_items = [item for item in batch if item["index"] not in translated]

    if not missing_items:
        return translated

    missing_indexes = [item["index"] for item in missing_items]

    add_log(
        job_id=job_id,
        level="WARNING",
        event="batch_missing_indexes",
        message=f"Batch {batch_number}/{batch_count} missing indexes: {missing_indexes}. Starting repair.",
        model=settings.openai_model,
        batch_number=batch_number,
        batch_count=batch_count,
        subtitle_start=start_index,
        subtitle_end=end_index,
    )

    for item in missing_items:
        if cancel_check:
            cancel_check()

        repair_started_at = time.monotonic()
        repair_result = translate_batch(
            batch=[item],
            target_language=target_language,
            style=style,
            source_language=source_language,
        )
        repair_duration = elapsed_seconds(repair_started_at)

        add_log(
            job_id=job_id,
            level="INFO",
            event="repair_request_completed",
            message=(
                f"Repair request for subtitle index {item['index']} completed in {repair_duration}s. "
                f"Tokens: {repair_result.total_tokens} total. "
                f"{provider_cost_text(repair_result.input_tokens, repair_result.output_tokens)}."
            ),
            model=settings.openai_model,
            input_tokens=repair_result.input_tokens,
            output_tokens=repair_result.output_tokens,
            total_tokens=repair_result.total_tokens,
            batch_number=batch_number,
            batch_count=batch_count,
            subtitle_start=item["index"],
            subtitle_end=item["index"],
        )

        if item["index"] in repair_result.translations:
            translated[item["index"]] = repair_result.translations[item["index"]]
            add_log(
                job_id=job_id,
                level="SUCCESS",
                event="repair_success",
                message=f"Successfully repaired subtitle index {item['index']}.",
                model=settings.openai_model,
                batch_number=batch_number,
                batch_count=batch_count,
                subtitle_start=item["index"],
                subtitle_end=item["index"],
            )
        else:
            add_log(
                job_id=job_id,
                level="ERROR",
                event="repair_failed",
                message=f"Repair failed for subtitle index {item['index']}.",
                model=settings.openai_model,
                batch_number=batch_number,
                batch_count=batch_count,
                subtitle_start=item["index"],
                subtitle_end=item["index"],
            )

    still_missing = [item["index"] for item in batch if item["index"] not in translated]

    if still_missing:
        raise RuntimeError(f"Translation output missing indexes after repair: {still_missing}")

    return translated


def run_translation_job(
    job_id: str,
    input_path: str,
    input_filename: str,
    target_language: str,
    style: str,
    output_next_to_input: bool = False,
    output_path_override: str | None = None,
    overwrite_existing: bool = True,
    batch_id: str | None = None,
) -> None:
    job_started_at = time.monotonic()

    try:
        check_cancelled(job_id=job_id, batch_id=batch_id)

        add_log(
            job_id=job_id,
            level="INFO",
            event="job_started",
            message=(
                f"Translation started for {input_filename}. "
                f"Source will be detected automatically. Target: {target_language}. "
                f"Style: {style}. Provider model: {settings.openai_model}."
            ),
            model=settings.openai_model,
        )

        update_job(
            job_id,
            status="running",
            message="Reading subtitle file...",
            progress_percent=0,
        )

        path = Path(input_path)
        check_cancelled(job_id=job_id, batch_id=batch_id)
        subs = read_srt(path)
        detected_source_language = detect_subtitle_language(subs, input_filename)

        total = len([sub for sub in subs if sub.text.strip()])

        if total == 0:
            raise RuntimeError("No readable subtitle text found.")

        update_job(
            job_id,
            source_language=detected_source_language,
            total_subtitles=total,
            translated_count=0,
            message="Preparing translation batches...",
        )

        add_log(
            job_id=job_id,
            level="INFO",
            event="source_language_detected",
            message=f"Detected source language: {detected_source_language}. Non-empty subtitles: {total}.",
            model=settings.openai_model,
        )

        batches = list(
            batch_subtitles(
                subs=subs,
                batch_size=settings.srt_batch_size,
                max_chars=settings.srt_max_chars,
                language=detected_source_language,
            )
        )

        add_log(
            job_id=job_id,
            level="INFO",
            event="job_batches_created",
            message=(
                f"Prepared {len(batches)} translation batches for {total} subtitles. "
                f"Limits: {settings.srt_batch_size} subtitles/batch, {settings.srt_max_chars} chars/batch."
            ),
            model=settings.openai_model,
        )

        translated_count = 0

        for batch_number, batch in enumerate(batches, start=1):
            check_cancelled(job_id=job_id, batch_id=batch_id)

            update_job(
                job_id,
                message=f"Translating batch {batch_number} of {len(batches)}...",
            )

            translated = translate_batch_with_repair(
                job_id=job_id,
                batch=batch,
                source_language=detected_source_language,
                target_language=target_language,
                style=style,
                batch_number=batch_number,
                batch_count=len(batches),
                cancel_check=lambda: check_cancelled(job_id=job_id, batch_id=batch_id),
            )

            check_cancelled(job_id=job_id, batch_id=batch_id)

            for item in batch:
                subtitle_index = item["index"]

                if subtitle_index in translated:
                    subs[subtitle_index].text = wrap_subtitle_text(
                        translated[subtitle_index],
                        target_language,
                    )

            translated_count += len(batch)
            progress_percent = int((translated_count / total) * 100) if total else 100

            update_job(
                job_id,
                translated_count=translated_count,
                progress_percent=progress_percent,
                message=f"Translated {translated_count} of {total} subtitles.",
            )

        update_job(job_id, message="Validating translated subtitle...")
        check_cancelled(job_id=job_id, batch_id=batch_id)

        validation = validate_subtitles(subs, target_language)

        add_log(
            job_id=job_id,
            level="INFO",
            event="validation_completed",
            message=(
                f"Validation {'passed' if validation['passed'] else 'failed'}. "
                f"Non-empty: {validation['non_empty']}. Empty: {validation['empty']}. "
                f"Likely untranslated: {validation['likely_untranslated']}. "
                f"Warnings: {validation['warnings']}."
            ),
            model=settings.openai_model,
        )

        if not validation["passed"]:
            raise RuntimeError(
                f"Validation failed. Too many subtitles are not in {target_language}. "
                f"Likely untranslated: {validation['likely_untranslated']} / {validation['non_empty']}."
            )

        output_filename = make_output_filename(input_filename, target_language)

        if output_path_override:
            output_path = Path(output_path_override)
            output_filename = output_path.name
        elif output_next_to_input:
            output_path = path.with_name(output_filename)
        else:
            output_path = settings.output_dir / output_filename

        if output_path.exists() and not overwrite_existing:
            raise RuntimeError(f"Output already exists: {output_path}")

        check_cancelled(job_id=job_id, batch_id=batch_id)
        update_job(job_id, message="Saving translated subtitle...")

        write_srt(subs, output_path)

        final_message = "Translation completed."

        if validation["warnings"]:
            final_message += " Warnings: " + " ".join(validation["warnings"])

        update_job(
            job_id,
            status="done",
            message=final_message,
            output_file=output_filename,
            output_path=str(output_path),
            progress_percent=100,
        )

        add_log(
            job_id=job_id,
            level="SUCCESS",
            event="job_completed",
            message=(
                f"Translation completed in {elapsed_seconds(job_started_at)}s. "
                f"Output: {output_path}"
            ),
            model=settings.openai_model,
        )

    except CancelledError:
        mark_job_cancelled(job_id)

        add_log(
            job_id=job_id,
            batch_id=batch_id,
            level="WARNING",
            event="job_cancelled",
            message=f"Job cancelled after {elapsed_seconds(job_started_at)}s. Completed output was not deleted.",
            model=settings.openai_model,
        )
    except Exception as e:
        friendly_message = friendly_error_message(e)
        update_job(
            job_id,
            status="failed",
            message=friendly_message,
            error=friendly_message,
        )

        add_log(
            job_id=job_id,
            level="ERROR",
            event="job_failed",
            message=f"{friendly_message} Failed after {elapsed_seconds(job_started_at)}s.",
            model=settings.openai_model,
        )


def run_media_translation_job(
    job_id: str,
    video_path: str,
    source_subtitle_path: str,
    source_kind: str,
    source_language: str,
    target_language: str,
    style: str,
    output_path: str,
    source_stream_index: int | None = None,
    overwrite_existing: bool = False,
    source_selection_message: str | None = None,
    batch_id: str | None = None,
) -> None:
    media_started_at = time.monotonic()
    source_path = Path(source_subtitle_path)
    video = Path(video_path)

    try:
        check_cancelled(job_id=job_id, batch_id=batch_id)

        source_bits = [
            f"{source_kind} subtitle selected",
            f"language={source_language or 'unknown'}",
            f"source={source_path.name}",
        ]

        if source_kind == "embedded":
            source_bits.append(f"stream={source_stream_index}")

        if source_selection_message:
            source_bits.append(source_selection_message)

        add_log(
            job_id=job_id,
            batch_id=batch_id,
            level="INFO",
            event="source_subtitle_selected",
            message=". ".join(source_bits) + ".",
            model=settings.openai_model,
        )

        if source_kind == "embedded":
            update_job(
                job_id,
                status="running",
                message="extracting embedded subtitle",
                progress_percent=0,
            )

            add_log(
                job_id=job_id,
                batch_id=batch_id,
                level="INFO",
                event="embedded_subtitle_extract_started",
                message=(
                    f"Starting FFmpeg extraction. Video: {video.name}. "
                    f"Stream: {source_stream_index}. Language: {source_language or 'unknown'}."
                ),
                model=settings.openai_model,
            )

            if source_path.exists():
                add_log(
                    job_id=job_id,
                    batch_id=batch_id,
                    level="INFO",
                    event="embedded_subtitle_extract_skipped",
                    message=f"Using cached extracted subtitle: {source_path.name}.",
                    model=settings.openai_model,
                )
            else:
                extract_started_at = time.monotonic()

                try:
                    extract_subtitle(
                        video_path=video,
                        output_srt_path=source_path,
                        preferred_language=source_language,
                        stream_index=source_stream_index,
                        cancel_check=lambda: check_cancelled(job_id=job_id, batch_id=batch_id),
                    )
                except Exception as exc:
                    add_log(
                        job_id=job_id,
                        batch_id=batch_id,
                        level="ERROR",
                        event="ffmpeg_extract_failed",
                        message=(
                            f"FFmpeg extraction failed after {elapsed_seconds(extract_started_at)}s. "
                            f"Video: {video.name}. Stream: {source_stream_index}. Error: {friendly_error_message(exc)}"
                        ),
                        model=settings.openai_model,
                    )
                    raise

            check_cancelled(job_id=job_id, batch_id=batch_id)
            total_subtitles = count_subtitle_items(source_path)

            add_log(
                job_id=job_id,
                batch_id=batch_id,
                level="SUCCESS",
                event="ffmpeg_extract_completed",
                message=(
                    f"Embedded subtitle extraction ready in {elapsed_seconds(media_started_at)}s. "
                    f"Stream: {source_stream_index}. Extracted cues: {total_subtitles}. Source: {source_path.name}."
                ),
                model=settings.openai_model,
            )

            update_job(
                job_id,
                input_path=str(source_path),
                total_subtitles=total_subtitles,
                message="translating",
            )
        else:
            update_job(
                job_id,
                status="running",
                message="found external subtitle",
                progress_percent=0,
            )

        run_translation_job(
            job_id=job_id,
            input_path=str(source_path),
            input_filename=source_path.name,
            target_language=target_language,
            style=style,
            output_next_to_input=True,
            output_path_override=output_path,
            overwrite_existing=overwrite_existing,
            batch_id=batch_id,
        )

        if source_selection_message:
            job = get_job(job_id)

            if job and job.get("status") == "done":
                update_job(
                    job_id,
                    message=f"{job.get('message') or 'Translation completed.'} Source: {source_selection_message}",
                )

    except CancelledError:
        mark_job_cancelled(job_id)

        add_log(
            job_id=job_id,
            batch_id=batch_id,
            level="WARNING",
            event="media_job_cancelled",
            message=f"Media job cancelled after {elapsed_seconds(media_started_at)}s.",
            model=settings.openai_model,
        )
    except Exception as e:
        friendly_message = friendly_error_message(e)
        update_job(
            job_id,
            status="failed",
            message=friendly_message,
            error=friendly_message,
        )

        add_log(
            job_id=job_id,
            level="ERROR",
            event="media_job_failed",
            message=f"{friendly_message} Media processing failed after {elapsed_seconds(media_started_at)}s.",
            model=settings.openai_model,
        )


def run_single_file_job(
    job_id: str,
    input_path: str,
    input_filename: str,
    target_language: str,
    style: str,
    overwrite_existing: bool = False,
) -> None:
    register_active_job(job_id)
    path = Path(input_path)
    suffix = path.suffix.lower()

    try:
        check_cancelled(job_id=job_id)

        if suffix == ".srt":
            update_job(
                job_id,
                status="running",
                message="Detecting subtitle language...",
                progress_percent=0,
            )

            subs = read_srt(path)
            check_cancelled(job_id=job_id)
            detected_source_language = detect_subtitle_language(subs, input_filename)
            total = len([sub for sub in subs if sub.text.strip()])

            if total == 0:
                raise RuntimeError("No readable subtitle text found.")

            update_job(
                job_id,
                source_language=detected_source_language,
                total_subtitles=total,
                translated_count=0,
            )

            if language_code(detected_source_language) == language_code(target_language):
                add_log(
                    job_id=job_id,
                    level="INFO",
                    event="subtitle_already_target_language",
                    message=(
                        f"Skipped {input_filename}: detected source language "
                        f"{detected_source_language} already matches target {target_language}."
                    ),
                    model=settings.openai_model,
                )

                update_job(
                    job_id,
                    status="skipped",
                    message="This subtitle is already in the selected target language",
                    progress_percent=100,
                )
                return

            output_filename = make_output_filename(input_filename, target_language)
            output_path = path.with_name(output_filename)

            if output_path.exists() and not overwrite_existing:
                add_log(
                    job_id=job_id,
                    level="INFO",
                    event="media_file_skipped",
                    message=f"Skipped {input_filename}: {TARGET_SUBTITLE_EXISTS_REASON}. Output: {output_path.name}.",
                    model=settings.openai_model,
                )

                update_job(
                    job_id,
                    status="skipped",
                    message=TARGET_SUBTITLE_EXISTS_REASON,
                    output_file=output_filename,
                    output_path=str(output_path),
                    progress_percent=100,
                )
                return

            run_translation_job(
                job_id=job_id,
                input_path=str(path),
                input_filename=input_filename,
                target_language=target_language,
                style=style,
                output_next_to_input=True,
                output_path_override=str(output_path),
                overwrite_existing=overwrite_existing,
            )
            return

        if suffix in VIDEO_EXTENSIONS:
            update_job(
                job_id,
                status="running",
                message="Inspecting video subtitles...",
                progress_percent=0,
            )

            scan_result = inspect_media_file(
                video_path=path,
                target_language=target_language,
                source_preference=DEFAULT_SOURCE_PREFERENCE,
                overwrite=overwrite_existing,
                root=path.parent,
                cancel_check=lambda: check_cancelled(job_id=job_id),
            )

            skipped = scan_result["skipped"]

            if skipped:
                output_path = skipped.get("output_path")
                add_log(
                    job_id=job_id,
                    level="INFO",
                    event="media_file_skipped",
                    message=f"Skipped {path.name}: {skipped['reason']}.",
                    model=settings.openai_model,
                )

                update_job(
                    job_id,
                    status="skipped",
                    message=skipped["reason"],
                    output_file=Path(output_path).name if output_path else None,
                    output_path=output_path,
                    progress_percent=100,
                )
                return

            file_info = scan_result["item"]
            source_detail = (
                f"{file_info['source_kind']} subtitle selected: "
                f"{file_info['source_subtitle_name']} "
                f"({file_info.get('source_language') or 'unknown'}). "
                f"{file_info.get('source_selection_reason') or ''}"
            ).strip()

            update_job(
                job_id,
                source_language=file_info["source_language"],
                total_subtitles=file_info["total_subtitles"],
                message=source_detail,
            )

            run_media_translation_job(
                job_id=job_id,
                video_path=file_info["video_path"],
                source_subtitle_path=file_info["source_subtitle_path"],
                source_kind=file_info["source_kind"],
                source_language=file_info["source_language"],
                target_language=target_language,
                style=style,
                output_path=file_info["output_path"],
                source_stream_index=file_info.get("source_stream_index"),
                overwrite_existing=overwrite_existing,
                source_selection_message=source_detail,
            )
            return

        raise RuntimeError("Only .srt subtitle files and supported video files are supported.")

    except CancelledError:
        mark_job_cancelled(job_id)

        add_log(
            job_id=job_id,
            level="WARNING",
            event="single_file_job_cancelled",
            message="Single-file job cancelled. Completed output files were not deleted.",
            model=settings.openai_model,
        )
    except Exception as e:
        friendly_message = friendly_error_message(e)
        update_job(
            job_id,
            status="failed",
            message=friendly_message,
            error=friendly_message,
            progress_percent=100,
        )

        add_log(
            job_id=job_id,
            level="ERROR",
            event="single_file_job_failed",
            message=friendly_message,
            model=settings.openai_model,
        )
    finally:
        CANCELLED_JOBS.discard(job_id)
        unregister_active_job(job_id)


def run_folder_batch_job(
    batch_id: str,
    folder_path: str,
    target_language: str,
    style: str,
    source_preference: str = DEFAULT_SOURCE_PREFERENCE,
    overwrite_existing: bool = False,
    max_concurrency: int | None = None,
) -> None:
    register_active_batch(batch_id)
    batch_started_at = time.monotonic()

    try:
        folder = Path(folder_path).resolve()
        concurrency = normalize_concurrency(max_concurrency)

        add_log(
            batch_id=batch_id,
            level="INFO",
            event="batch_job_started",
            message=(
                f"Batch started. Folder: {folder}. Target: {target_language}. "
                f"Style: {style}. Requested concurrency: {max_concurrency}. "
                f"Effective concurrency: {concurrency}. Overwrite: {overwrite_existing}."
            ),
            model=settings.openai_model,
        )

        update_batch(
            batch_id,
            status="running",
            message="scanning",
            progress_percent=0,
        )

        scan_started_at = time.monotonic()
        scan_result = scan_media_folder(
            folder_path=str(folder),
            target_language=target_language,
            source_preference=source_preference,
            overwrite=overwrite_existing,
            cancel_check=lambda: check_cancelled(batch_id=batch_id),
        )
        check_cancelled(batch_id=batch_id)
        scanned_files = scan_result["items"]
        skipped_files = scan_result["skipped"]
        total_files = len(scanned_files) + len(skipped_files)

        add_log(
            batch_id=batch_id,
            level="INFO",
            event="folder_scan_completed",
            message=(
                f"Scan completed in {elapsed_seconds(scan_started_at)}s. "
                f"Ready: {len(scanned_files)} files. Skipped: {len(skipped_files)}. "
                f"Source preference: {source_preference}."
            ),
            model=settings.openai_model,
        )

        update_batch(
            batch_id,
            total_files=total_files,
            completed_files=0,
            failed_files=0,
            message=f"Found {len(scanned_files)} files to translate. Skipped {len(skipped_files)}.",
        )

        if total_files == 0:
            update_batch(
                batch_id,
                status="done",
                message="No translatable media files found.",
                progress_percent=100,
            )
            return

        for skipped in skipped_files:
            job_id = str(uuid4())

            create_job(
                job_id=job_id,
                batch_id=batch_id,
                input_file=skipped["relative_path"],
                input_path=skipped["video_path"],
                target_language=target_language,
                source_language="Unknown",
                style=style,
                model=settings.openai_model,
                total_subtitles=0,
                status="skipped",
                message=skipped["reason"],
                output_file=Path(skipped["output_path"]).name if skipped.get("output_path") else None,
                output_path=skipped.get("output_path"),
            )

            add_log(
                job_id=job_id,
                batch_id=batch_id,
                level="INFO",
                event="media_file_skipped",
                message=(
                    f"Skipped {skipped['relative_path']}: {skipped['reason']}. "
                    f"Output candidate: {Path(skipped['output_path']).name if skipped.get('output_path') else 'none'}."
                ),
                model=settings.openai_model,
            )

        for file_info in scanned_files:
            job_id = str(uuid4())
            source_path = Path(file_info["source_subtitle_path"])

            create_job(
                job_id=job_id,
                batch_id=batch_id,
                input_file=file_info["relative_path"],
                input_path=file_info["video_path"] if file_info["source_kind"] == "embedded" else str(source_path),
                target_language=target_language,
                source_language=file_info["source_language"],
                style=style,
                model=settings.openai_model,
                total_subtitles=file_info["total_subtitles"],
                message=file_info["step"],
                output_file=file_info["output_name"],
                output_path=file_info["output_path"],
            )

            add_log(
                job_id=job_id,
                batch_id=batch_id,
                level="INFO",
                event="source_subtitle_selected",
                message=(
                    f"{file_info['source_kind'].title()} subtitle selected for {file_info['relative_path']}. "
                    f"Source: {file_info['source_subtitle_name']}. "
                    f"Language: {file_info['source_language']}. "
                    f"Reason: {file_info.get('source_selection_reason') or 'automatic priority'}."
                ),
                model=settings.openai_model,
            )

        jobs = list_jobs_by_batch(batch_id)
        runnable_jobs = [job for job in jobs if job["status"] != "skipped"]
        scanned_files_by_relative_path = {
            file_info["relative_path"]: file_info
            for file_info in scanned_files
        }

        if not runnable_jobs:
            update_batch(
                batch_id,
                status="done",
                message=f"Batch completed. Skipped {len(skipped_files)} files.",
                completed_files=0,
                failed_files=0,
                progress_percent=100,
            )
            return

        def run_one_file(job: dict) -> str:
            register_active_job(job["id"])
            try:
                if batch_id in CANCELLED_BATCHES:
                    mark_job_cancelled(job["id"])
                    return job["id"]

                update_batch(
                    batch_id,
                    message=f"Processing files with up to {concurrency} concurrent workers...",
                )

                matching_file = scanned_files_by_relative_path.get(job["input_file"])

                if not matching_file:
                    raise RuntimeError(f"Scanned file data not found for {job['input_file']}.")

                run_media_translation_job(
                    job_id=job["id"],
                    video_path=matching_file["video_path"],
                    source_subtitle_path=matching_file["source_subtitle_path"],
                    source_kind=matching_file["source_kind"],
                    source_language=matching_file["source_language"],
                    target_language=target_language,
                    style=style,
                    output_path=matching_file["output_path"],
                    source_stream_index=matching_file.get("source_stream_index"),
                    overwrite_existing=overwrite_existing,
                    batch_id=batch_id,
                )
            except CancelledError:
                mark_job_cancelled(job["id"])

                add_log(
                    job_id=job["id"],
                    batch_id=batch_id,
                    level="WARNING",
                    event="media_file_cancelled",
                    message="Media file cancelled before completion.",
                    model=settings.openai_model,
                )
            except Exception as exc:
                friendly_message = friendly_error_message(exc)
                update_job(
                    job["id"],
                    status="failed",
                    message=friendly_message,
                    error=friendly_message,
                    progress_percent=100,
                )

                add_log(
                    job_id=job["id"],
                    batch_id=batch_id,
                    level="ERROR",
                    event="media_file_failed",
                    message=friendly_message,
                    model=settings.openai_model,
                )
            finally:
                unregister_active_job(job["id"])

            return job["id"]

        max_workers = min(concurrency, len(runnable_jobs)) or 1

        add_log(
            batch_id=batch_id,
            level="INFO",
            event="batch_concurrency_started",
            message=(
                f"Starting translation workers. Runnable files: {len(runnable_jobs)}. "
                f"Skipped files: {len(skipped_files)}. Max workers: {max_workers}."
            ),
            model=settings.openai_model,
        )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            pending_jobs = iter(runnable_jobs)
            futures = set()

            for _ in range(max_workers):
                try:
                    futures.add(executor.submit(run_one_file, next(pending_jobs)))
                except StopIteration:
                    break

            while futures:
                for future in as_completed(futures):
                    futures.remove(future)
                    break

                future.result()

                if batch_id in CANCELLED_BATCHES:
                    for job in list_jobs_by_batch(batch_id):
                        if job["status"] in {"queued", "cancel_requested"}:
                            mark_job_cancelled(job["id"], message="Canceled before starting.")

                refreshed_jobs = list_jobs_by_batch(batch_id)
                completed = len([j for j in refreshed_jobs if j["status"] == "done"])
                failed = len([j for j in refreshed_jobs if j["status"] == "failed"])
                skipped = len([j for j in refreshed_jobs if j["status"] in {"skipped", "cancelled"}])
                finished = completed + failed + skipped
                progress_percent = int((finished / total_files) * 100) if total_files else 100

                update_batch(
                    batch_id,
                    completed_files=completed,
                    failed_files=failed,
                    progress_percent=progress_percent,
                    message=f"Finished {finished} of {total_files} files.",
                )

                if batch_id in CANCELLED_BATCHES:
                    break

                try:
                    futures.add(executor.submit(run_one_file, next(pending_jobs)))
                except StopIteration:
                    pass

        refreshed_jobs = list_jobs_by_batch(batch_id)
        current_batch = get_batch(batch_id)

        if current_batch and current_batch["status"] == "interrupted":
            add_log(
                batch_id=batch_id,
                level="WARNING",
                event="batch_job_interrupted",
                message="Batch worker reached completion after cancel timeout; preserving interrupted status.",
                model=settings.openai_model,
            )
            return

        completed = len([j for j in refreshed_jobs if j["status"] == "done"])
        failed = len([j for j in refreshed_jobs if j["status"] == "failed"])
        cancelled = len([j for j in refreshed_jobs if j["status"] in {"cancelled", "cancel_requested"}])

        if batch_id in CANCELLED_BATCHES or cancelled:
            final_status = "cancelled"
        else:
            final_status = "done" if failed == 0 else "failed"

        update_batch(
            batch_id,
            status=final_status,
            message=f"Batch completed. Done: {completed}, Failed: {failed}, Cancelled: {cancelled}.",
            completed_files=completed,
            failed_files=failed,
            progress_percent=100,
        )

        add_log(
            batch_id=batch_id,
            level="SUCCESS" if final_status == "done" else "WARNING",
            event="batch_job_completed",
            message=f"Batch completed in {elapsed_seconds(batch_started_at)}s. Done: {completed}, Failed: {failed}, Cancelled: {cancelled}.",
            model=settings.openai_model,
        )

    except CancelledError:
        refreshed_jobs = list_jobs_by_batch(batch_id)

        for job in refreshed_jobs:
            if job["status"] in {"queued", "running", "cancel_requested"}:
                mark_job_cancelled(job["id"])

        refreshed_jobs = list_jobs_by_batch(batch_id)
        completed = len([j for j in refreshed_jobs if j["status"] == "done"])
        failed = len([j for j in refreshed_jobs if j["status"] == "failed"])
        cancelled = len([j for j in refreshed_jobs if j["status"] == "cancelled"])

        current_batch = get_batch(batch_id)

        if current_batch and current_batch["status"] == "interrupted":
            add_log(
                batch_id=batch_id,
                level="WARNING",
                event="batch_job_interrupted",
                message="Batch cancellation finished after timeout; preserving interrupted status.",
                model=settings.openai_model,
            )
            return

        update_batch(
            batch_id,
            status="cancelled",
            completed_files=completed,
            failed_files=failed,
            progress_percent=100,
            message=f"Canceled. Completed {completed}, failed {failed}, not started/canceled {cancelled}.",
        )

        add_log(
            batch_id=batch_id,
            level="WARNING",
            event="batch_job_cancelled",
            message=(
                f"Batch cancelled after {elapsed_seconds(batch_started_at)}s. "
                f"Completed {completed}, Failed {failed}, Cancelled {cancelled}."
            ),
            model=settings.openai_model,
        )
    except Exception as e:
        friendly_message = friendly_error_message(e)
        update_batch(
            batch_id,
            status="failed",
            message=friendly_message,
            progress_percent=100,
        )

        add_log(
            batch_id=batch_id,
            level="ERROR",
            event="batch_job_failed",
            message=f"{friendly_message} Batch failed after {elapsed_seconds(batch_started_at)}s.",
            model=settings.openai_model,
        )
    finally:
        CANCELLED_BATCHES.discard(batch_id)
        unregister_active_batch(batch_id)

        for job in list_jobs_by_batch(batch_id):
            CANCELLED_JOBS.discard(job["id"])
