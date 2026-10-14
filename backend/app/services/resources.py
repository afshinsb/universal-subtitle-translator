"""Bounded process-wide and cross-process admission, without Docker replicas."""
import contextlib
import contextvars
import os
import sqlite3
import time
import threading
from pathlib import Path
from uuid import uuid4

from app.config import settings

request_identity = contextvars.ContextVar('request_identity', default='manual')
completion_cap = contextvars.ContextVar('completion_cap', default=0)


def connection():
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.data_dir / 'resource-leases.sqlite', timeout=30)
    conn.execute('CREATE TABLE IF NOT EXISTS leases (id TEXT PRIMARY KEY, kind TEXT, expires REAL)')
    conn.execute('CREATE TABLE IF NOT EXISTS pressure (id INTEGER PRIMARY KEY, until REAL)')
    conn.commit()
    return conn


def pressure():
    result = {'available_mb': None, 'container_mb': None, 'memory_pressure': 0., 'load': os.getloadavg()[0]}
    try:
        mem = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
        result['available_mb'] = int(mem['MemAvailable'].split()[0]) / 1024
        result['memory_pressure'] = float(Path('/proc/pressure/memory').read_text().split('avg10=')[1].split()[0])
        cgroup = Path('/sys/fs/cgroup')
        maximum = (cgroup / 'memory.max').read_text().strip()
        if maximum != 'max':
            stats = dict(line.split() for line in (cgroup / 'memory.stat').read_text().splitlines())
            working = int((cgroup / 'memory.current').read_text()) - int(stats.get('inactive_file', 0))
            result['container_mb'] = (int(maximum) - working) / 1048576
    except (OSError, ValueError, KeyError, IndexError):
        pass
    return result


def limits():
    hard = max(1, min(settings.automation_api_concurrency, 8))
    jobs = max(1, min(settings.automation_job_concurrency, 4))
    p = pressure()
    busy = (p['available_mb'] is not None and p['available_mb'] < settings.automation_min_available_mb) or (p['container_mb'] is not None and p['container_mb'] < 128) or p['memory_pressure'] > 1 or p['load'] > (os.cpu_count() or 1) * 1.5
    with connection() as conn:
        row = conn.execute('SELECT until FROM pressure WHERE id=1').fetchone()
    if busy or row and row[0] > time.time():
        hard, jobs = 1, 1
    p.update(api_limit=hard, job_limit=jobs, api_max=settings.automation_api_concurrency,
             job_max=settings.automation_job_concurrency, extraction_limit=1)
    return p


def throttled():
    with connection() as conn:
        conn.execute('INSERT OR REPLACE INTO pressure VALUES (1,?)', (time.time() + 60,))


@contextlib.contextmanager
def slot(kind, check=None):
    owner = uuid4().hex
    deadline = max(180, settings.openai_timeout_seconds + 60, settings.ffmpeg_timeout_seconds + 60)
    while True:
        if check:
            check()
        cap = limits()['api_limit'] if kind == 'api' else 1
        with connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('DELETE FROM leases WHERE expires<?', (time.time(),))
            count = conn.execute('SELECT COUNT(*) FROM leases WHERE kind=?', (kind,)).fetchone()[0]
            if count < cap:
                conn.execute('INSERT INTO leases VALUES (?,?,?)', (owner, kind, time.time() + deadline))
                break
        time.sleep(.1)
    stop = threading.Event()
    def heartbeat():
        while not stop.wait(15):
            with connection() as conn:
                conn.execute('UPDATE leases SET expires=? WHERE id=?', (time.time() + deadline, owner))
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=2)
        with connection() as conn:
            conn.execute('DELETE FROM leases WHERE id=?', (owner,))


def status():
    result = limits()
    with connection() as conn:
        rows = conn.execute('SELECT kind,COUNT(*) FROM leases WHERE expires>=? GROUP BY kind', (time.time(),)).fetchall()
    result['active'] = dict(rows)
    return result
