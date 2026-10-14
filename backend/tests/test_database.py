import sqlite3

import pytest

from app.config import ensure_directories
from app.database import get_connection


def test_database_connection_closes_after_context():
    ensure_directories()
    with get_connection() as connection:
        connection.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


def test_database_connection_rolls_back_and_closes_on_error():
    ensure_directories()
    with get_connection() as connection:
        connection.execute("CREATE TABLE fixture (value TEXT)")
    with pytest.raises(ValueError):
        with get_connection() as failed_connection:
            failed_connection.execute("INSERT INTO fixture VALUES ('pending')")
            raise ValueError("fixture failure")
    with get_connection() as connection:
        assert connection.execute("SELECT count(*) FROM fixture").fetchone()[0] == 0
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        failed_connection.execute("SELECT 1")
