"""Durable, conservative UTC daily ceiling shared by provider calls and repairs.

Every submitted call reserves its entire capped cost; failures and restarts do
not release reservations. Completion limits include hidden reasoning tokens.
"""
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_CEILING
from uuid import uuid4

from app.config import settings
from app.services.pilot_budget import SYSTEM_PROMPT


class DailyBudgetExceeded(RuntimeError):
    pass


def utc_day():
    return datetime.now(timezone.utc).date().isoformat()


def retry_delay():
    now = datetime.now(timezone.utc)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return (midnight - now).total_seconds() + 1


def ledger_path():
    return settings.data_dir / "provider-budget.sqlite"


def reserve_daily(model, prompt, options):
    limit = Decimal(str(settings.openai_daily_budget_usd))
    if limit == 0:
        return None
    input_rate = Decimal(str(settings.openai_budget_input_ceiling_per_1m))
    output_rate = Decimal(str(settings.openai_budget_output_per_1m))
    cap = options.get("max_completion_tokens", 0)
    if not all(x.is_finite() and x > 0 for x in (limit, input_rate, output_rate)):
        raise RuntimeError("Daily budget and provider rates must be positive and finite.")
    if type(cap) is not int or not 1 <= cap <= 128000:
        raise RuntimeError("Daily budget requires a bounded max_completion_tokens.")
    if options.get("service_tier") != "default":
        raise RuntimeError("Daily budget requires standard service tier.")
    input_bound = len((SYSTEM_PROMPT + prompt).encode("utf-8")) + 1024
    if input_bound > 272000:
        raise RuntimeError("Daily budget request exceeds short-context price bound.")
    def units(value):
        return int((value * 1_000_000_000).to_integral_value(rounding=ROUND_CEILING))
    bound = units((input_bound * input_rate + cap * output_rate) / 1_000_000)
    ceiling = int(limit * 1_000_000_000)
    fingerprint = json.dumps({"limit": str(limit), "input_rate": str(input_rate),
        "output_rate": str(output_rate), "model": model, "cap": cap,
        "effort": options.get("reasoning_effort")}, sort_keys=True)
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    reservation = uuid4().hex
    with sqlite3.connect(path, timeout=30) as conn:
        path.chmod(0o600)
        conn.execute("CREATE TABLE IF NOT EXISTS budget_config (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)")
        conn.execute("""CREATE TABLE IF NOT EXISTS provider_reservations (
            id TEXT PRIMARY KEY, day TEXT NOT NULL, bound INTEGER NOT NULL,
            input_tokens INTEGER, output_tokens INTEGER, reasoning_tokens INTEGER)""")
        conn.execute("BEGIN IMMEDIATE")
        cfg = conn.execute("SELECT value FROM budget_config WHERE id=1").fetchone()
        if cfg and cfg[0] != fingerprint:
            raise RuntimeError("Daily budget configuration changed; preserve ledger and review approval.")
        day = utc_day()
        spent = conn.execute("SELECT COALESCE(SUM(bound),0) FROM provider_reservations WHERE day=?", (day,)).fetchone()[0]
        if spent + bound > ceiling:
            raise DailyBudgetExceeded("Daily spending ceiling reached; waiting for next UTC day.")
        conn.execute("INSERT OR IGNORE INTO budget_config VALUES (1,?)", (fingerprint,))
        conn.execute("INSERT INTO provider_reservations(id,day,bound) VALUES (?,?,?)", (reservation, day, bound))
    return reservation


def record_usage(reservation, usage):
    if not reservation or usage is None:
        return
    details = getattr(usage, "completion_tokens_details", None)
    with sqlite3.connect(ledger_path(), timeout=30) as conn:
        conn.execute("""UPDATE provider_reservations SET input_tokens=?,output_tokens=?,
            reasoning_tokens=? WHERE id=?""", (getattr(usage, "prompt_tokens", None),
            getattr(usage, "completion_tokens", None), getattr(details, "reasoning_tokens", None), reservation))


def status():
    result = {"enabled": settings.openai_daily_budget_usd != 0,
        "limit_usd": settings.openai_daily_budget_usd, "utc_day": utc_day(),
        "reserved_usd": 0, "requests": 0, "reasoning_tokens": 0}
    path = ledger_path()
    if not path.is_file():
        return result
    with sqlite3.connect("file:" + str(path) + "?mode=ro", uri=True) as conn:
        row = conn.execute("""SELECT COALESCE(SUM(bound),0),COUNT(*),
            COALESCE(SUM(reasoning_tokens),0) FROM provider_reservations WHERE day=?""", (utc_day(),)).fetchone()
    result.update(reserved_usd=row[0]/1_000_000_000, requests=row[1], reasoning_tokens=row[2])
    return result
