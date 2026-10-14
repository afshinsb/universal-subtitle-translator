"""Rehearse migration of an offline SQLite backup without modifying its input."""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["OPENAI_API_KEY"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.config import settings  # noqa: E402
from app.database import init_db  # noqa: E402
from app.services.automation import init_schema  # noqa: E402


def quoted(value):
    return '"' + value.replace('"', '""') + '"'


def inventory(conn):
    result = {}
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        columns = [row[1] for row in conn.execute("PRAGMA table_info(" + quoted(name) + ")")]
        rows = conn.execute("SELECT " + ",".join(map(quoted, columns)) + " FROM " + quoted(name)).fetchall()
        digest = hashlib.sha256(json.dumps(sorted(json.dumps(row, default=str) for row in rows)).encode()).hexdigest()
        result[name] = {"columns": columns, "rows": len(rows), "sha256": digest}
    return result


def verify(snapshot):
    snapshot = Path(snapshot)
    original = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="ust-migration-") as directory:
        target = Path(directory) / "app.db"
        shutil.copyfile(snapshot, target)
        with sqlite3.connect(target) as conn:
            before = inventory(conn)
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        settings.database_path = target
        settings.media_root = None
        init_db()
        init_schema()
        with sqlite3.connect(target) as conn:
            after = {}
            for table, item in before.items():
                rows = conn.execute("SELECT " + ",".join(map(quoted, item["columns"])) + " FROM " + quoted(table)).fetchall()
                digest = hashlib.sha256(json.dumps(sorted(json.dumps(row, default=str) for row in rows)).encode()).hexdigest()
                assert len(rows) == item["rows"] and digest == item["sha256"], "Original rows changed: " + table
                after[table] = {"rows": len(rows), "original_columns_preserved": True}
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert conn.execute("SELECT COUNT(*) FROM automation_queue").fetchone()[0] == 0
            assert json.loads(conn.execute("SELECT value FROM automation_config").fetchone()[0])["enabled"] is False
        assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == original
    return {"integrity": "ok", "source_unchanged": True, "original_tables": after,
            "production_queue": "new, empty, paused"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, help="Offline backup database, never a running production database")
    args = parser.parse_args()
    print(json.dumps(verify(args.snapshot)))


if __name__ == "__main__":
    main()
