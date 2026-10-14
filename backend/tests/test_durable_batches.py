import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.config import settings
from app.services import durable_batches, resources


def test_completed_batches_survive_failure_and_resume(monkeypatch):
    monkeypatch.setattr(settings, 'automation_batch_concurrency', 2)
    batches = [[{'index': i}] for i in range(1, 11)]
    called = []
    def translate(number, batch):
        called.append(number)
        if number == 5:
            time.sleep(.02)
            raise RuntimeError('transient failure')
        return {batch[0]['index']: 'سلام'}
    with pytest.raises(RuntimeError, match='transient'):
        list(durable_batches.run(batches, translate, lambda: None, 'source', 'file'))
    with durable_batches.connection() as conn:
        completed = {row[0] for row in conn.execute('SELECT number FROM batches')}
    assert {1, 2, 3, 4}.issubset(completed)
    called.clear()
    def successful(number, batch):
        called.append(number)
        return {batch[0]['index']: 'سلام'}
    outputs = list(durable_batches.run(batches, successful, lambda: None, 'source', 'file'))
    assert len(outputs) == 10 and not completed.intersection(called)
    assert sorted(number for number, _, _ in outputs) == list(range(1, 11))


def test_stale_worker_cannot_checkpoint():
    def expired():
        raise RuntimeError('lease lost')
    with pytest.raises(RuntimeError, match='lease lost'):
        list(durable_batches.run([[{'index': 1}]], lambda *_: {1: 'سلام'}, expired, 'source', 'file'))
    with durable_batches.connection() as conn:
        assert conn.execute('SELECT COUNT(*) FROM batches').fetchone()[0] == 0


def test_truncation_escalates_bounded_reasoning_cap(monkeypatch):
    monkeypatch.setattr(settings, 'openai_max_completion_tokens', 32768)
    caps = []
    def translate(*_):
        caps.append(resources.completion_cap.get())
        if len(caps) == 1:
            raise durable_batches.CompletionTruncated()
        return {1: 'سلام'}
    list(durable_batches.run([[{'index': 1}]], translate, lambda: None, 'source', 'file'))
    assert caps == [16384, 32768]


def test_global_api_and_extraction_slots_are_bounded(monkeypatch):
    monkeypatch.setattr(resources, 'limits', lambda: {'api_limit': 4})
    lock = threading.Lock()
    for kind, maximum in [('api', 4), ('extraction', 1)]:
        active = 0
        peak = 0
        def work(_):
            nonlocal active, peak
            with resources.slot(kind):
                with lock:
                    active += 1
                    peak = max(peak, active)
                time.sleep(.025)
                with lock:
                    active -= 1
        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(work, range(30)))
        assert 1 <= peak <= maximum
    assert resources.status()['active'] == {}


def test_burst_100_files_idempotent_and_restart_safe(client, tmp_path, monkeypatch):
    from app.services import automation
    from app.database import get_connection
    root = tmp_path / 'library'
    root.mkdir()
    automation.save_config(False, [str(root)], {}, 'events_only')
    automation.save_scope([], 'libraries')
    token = automation.config()['webhook_token']
    files = [{'path': str(root / f'Fixture.S01E{i:02}.mkv')} for i in range(100)]
    payload = {'eventType': 'Download', 'episodeFiles': files}
    started = time.monotonic()
    for _ in range(2):
        result = client.post('/automation/hooks/sonarr', json=payload, headers={'X-Automation-Key': token})
        assert result.status_code == 200 and len(result.json()['queue_ids']) == 100
    assert time.monotonic() - started < 10
    assert automation.counts() == {'queued': 100}
    automation.init_schema()  # Same persistent database reopened.
    assert automation.counts() == {'queued': 100}
    monkeypatch.setattr(resources, 'limits', lambda: {'job_limit': 2})
    first, second = automation.claim(), automation.claim()
    assert first and second and first['id'] != second['id'] and automation.claim() is None
    with get_connection() as conn:
        conn.execute('UPDATE automation_queue SET lease_until=0 WHERE id=?', (first['id'],))
    recovered = automation.claim()
    assert recovered['id'] == first['id'] and recovered['owner'] != first['owner']
    automation.finish(first, 'done', 'stale worker')
    assert automation.counts() == {'queued': 98, 'running': 2}


def test_pressure_reduces_admission_without_removing_hard_limits(monkeypatch):
    monkeypatch.setattr(settings, 'automation_job_concurrency', 2)
    monkeypatch.setattr(settings, 'automation_api_concurrency', 4)
    monkeypatch.setattr(resources, 'pressure', lambda: {'available_mb': 100, 'container_mb': 100, 'memory_pressure': 5, 'load': 0})
    values = resources.limits()
    assert values['job_limit'] == values['api_limit'] == 1
    assert values['job_max'] == 2 and values['api_max'] == 4
