"""Bounded parallel batches with content-addressed SQLite checkpoints."""
from contextlib import nullcontext
import contextvars
import hashlib
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path

from app.config import settings
from app.services import resources


class CompletionTruncated(RuntimeError):
    pass


def connection():
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.data_dir / 'translation-checkpoints.sqlite', timeout=30)
    conn.execute('''CREATE TABLE IF NOT EXISTS batches (
        identity TEXT, number INTEGER, result TEXT NOT NULL, completed REAL,
        PRIMARY KEY(identity,number))''')
    conn.commit()
    return conn


def identity(source, model, style):
    policy = [hashlib.sha256(Path(source).read_bytes()).hexdigest(), model, style,
              settings.openai_reasoning_effort, settings.srt_batch_size, settings.srt_max_chars,
              settings.automation_context_gap_seconds, 'context-prompt-v1']
    return hashlib.sha256(json.dumps(policy).encode()).hexdigest()


def run(batches, translate, check, key, media_id, guard=None):
    with connection() as conn:
        cached = {number: {int(i): text for i, text in json.loads(result).items()}
                  for number, result in conn.execute('SELECT number,result FROM batches WHERE identity=?', (key,))}
    for number, batch in enumerate(batches, 1):
        if number in cached:
            check()
            yield number, batch, cached[number]

    def work(number, batch):
        check()
        token = resources.request_identity.set(media_id)
        initial = min(settings.openai_max_completion_tokens or 32768,
                      max(4096, settings.automation_initial_completion_tokens))
        cap_token = resources.completion_cap.set(initial)
        try:
            for attempt in range(3):
                try:
                    result = translate(number, batch)
                    check()  # Fence checkpoint writes as well as final publication.
                    with guard() if guard else nullcontext():
                        with connection() as conn:
                            conn.execute('INSERT OR IGNORE INTO batches VALUES (?,?,?,?)',
                                     (key, number, json.dumps(result), time.time()))
                    return result
                except CompletionTruncated:
                    if resources.completion_cap.get() >= settings.openai_max_completion_tokens:
                        raise
                    resources.completion_cap.set(settings.openai_max_completion_tokens)
                except Exception as exc:
                    if getattr(exc, 'status_code', None) not in {429, 500, 502, 503, 504} or attempt == 2:
                        raise
                    resources.throttled()
                    for _ in range(20 * 2 ** attempt):
                        check()
                        time.sleep(.1)
            raise RuntimeError('Batch request retry limit reached.')
        finally:
            resources.completion_cap.reset(cap_token)
            resources.request_identity.reset(token)

    pending = iter((number, batch) for number, batch in enumerate(batches, 1) if number not in cached)
    futures = {}
    with ThreadPoolExecutor(max_workers=max(1, min(settings.automation_batch_concurrency, 2))) as pool:
        exhausted = False
        while futures or not exhausted:
            while len(futures) < max(1, min(settings.automation_batch_concurrency, 2)) and not exhausted:
                try:
                    number, batch = next(pending)
                except StopIteration:
                    exhausted = True
                    break
                context = contextvars.copy_context()
                futures[pool.submit(context.run, work, number, batch)] = (number, batch)
            if futures:
                completed, _ = wait(futures, return_when=FIRST_COMPLETED)
                for future in completed:
                    number, batch = futures.pop(future)
                    yield number, batch, future.result()
