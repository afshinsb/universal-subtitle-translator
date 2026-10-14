"""Durable, conservative UTC daily ceiling shared by provider calls and repairs.

Every submitted call reserves its entire capped cost; failures and restarts do
not release reservations. Completion limits include hidden reasoning tokens.
"""
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_CEILING
from uuid import uuid4
from app.services.resources import request_identity

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
        if not settings.dev_mode:
            raise RuntimeError("Production provider calls require a positive daily spending limit.")
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
        "output_rate": str(output_rate), "model": model,
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
        columns = {row[1] for row in conn.execute("PRAGMA table_info(provider_reservations)")}
        for name, kind in {"actual": "INTEGER", "identity": "TEXT", "latency": "REAL"}.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE provider_reservations ADD COLUMN {name} {kind}")
        cfg = conn.execute("SELECT value FROM budget_config WHERE id=1").fetchone()
        if cfg:
            previous = json.loads(cfg[0])
            previous.pop("cap", None)  # Upgrade legacy policy without releasing any reservation.
            new_policy = json.loads(fingerprint)
            if previous != new_policy:
                if settings.dev_mode or any(previous[k] != new_policy[k] for k in ("model", "effort", "input_rate", "output_rate")):
                    raise RuntimeError("Daily budget configuration changed; preserve ledger and review approval.")
                conn.execute("CREATE TABLE IF NOT EXISTS budget_policy_audit (changed TEXT, previous TEXT, current TEXT)")
                conn.execute("INSERT INTO budget_policy_audit VALUES (?,?,?)", (datetime.now(timezone.utc).isoformat(), cfg[0], fingerprint))
                conn.execute("UPDATE budget_config SET value=? WHERE id=1", (fingerprint,))
        day = utc_day()
        spent = conn.execute("SELECT COALESCE(SUM(COALESCE(actual,bound)),0) FROM provider_reservations WHERE day=?", (day,)).fetchone()[0]
        if spent + bound > ceiling:
            raise DailyBudgetExceeded("Daily spending ceiling reached; waiting for next UTC day.")
        conn.execute("INSERT OR IGNORE INTO budget_config VALUES (1,?)", (fingerprint,))
        conn.execute("INSERT INTO provider_reservations(id,day,bound,identity) VALUES (?,?,?,?)", (reservation, day, bound, request_identity.get()))
    return reservation


def record_usage(reservation, usage, latency=0):
    if not reservation or usage is None:
        return
    details = getattr(usage, "completion_tokens_details", None)
    incoming = getattr(usage, "prompt_tokens", None)
    outgoing = getattr(usage, "completion_tokens", None)
    if type(incoming) is not int or type(outgoing) is not int or min(incoming, outgoing) < 0:
        return  # Ambiguous requests retain their entire reservation.
    input_details = getattr(usage, "prompt_tokens_details", None)
    cached = getattr(input_details, "cached_tokens", 0) or 0
    write = getattr(input_details, "cache_write_tokens", getattr(usage, "cache_write_tokens", None))
    if write is None:
        write = max(0, incoming - cached)  # Missing cache-write details retain the conservative ceiling.
    if settings.openai_model == "gpt-6-luna" and 0 <= cached + write <= incoming:
        input_cost = (Decimal(incoming - cached - write) * Decimal("0.10")
                      + Decimal(cached) * Decimal("0.01") + Decimal(write) * Decimal("0.125"))
    else:
        input_cost = Decimal(incoming) * Decimal(str(settings.openai_budget_input_ceiling_per_1m))
    actual = int(((input_cost
                   + Decimal(outgoing) * Decimal(str(settings.openai_budget_output_per_1m)))
                  * 1000).to_integral_value(rounding=ROUND_CEILING))
    with sqlite3.connect(ledger_path(), timeout=30) as conn:
        conn.execute("""UPDATE provider_reservations SET input_tokens=?,output_tokens=?,
            reasoning_tokens=?,actual=?,latency=? WHERE id=?""", (incoming, outgoing,
            getattr(details, "reasoning_tokens", None), actual, latency, reservation))


def status():
    result = {"enabled": settings.openai_daily_budget_usd != 0,
        "limit_usd": settings.openai_daily_budget_usd, "utc_day": utc_day(),
        "reserved_usd": 0, "consumed_usd": 0, "requests": 0, "reasoning_tokens": 0}
    path = ledger_path()
    if not path.is_file():
        return result
    with sqlite3.connect("file:" + str(path) + "?mode=ro", uri=True) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(provider_reservations)")}
        if "actual" not in columns:
            row = conn.execute("SELECT COALESCE(SUM(bound),0),COUNT(*),COALESCE(SUM(reasoning_tokens),0) FROM provider_reservations WHERE day=?", (utc_day(),)).fetchone()
            result.update(reserved_usd=row[0]/1_000_000_000, requests=row[1], reasoning_tokens=row[2])
            return result
        row = conn.execute("""SELECT COALESCE(SUM(CASE WHEN actual IS NULL THEN bound ELSE 0 END),0),COUNT(*),
            COALESCE(SUM(reasoning_tokens),0),COALESCE(SUM(actual),0) FROM provider_reservations WHERE day=?""", (utc_day(),)).fetchone()
    result.update(reserved_usd=row[0]/1_000_000_000, requests=row[1], reasoning_tokens=row[2], consumed_usd=row[3]/1_000_000_000)
    return result


def file_usage(identity):
    path = ledger_path()
    if not path.is_file():
        return {"cost_usd": 0, "latency": 0}
    with sqlite3.connect(path, timeout=30) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(provider_reservations)")}
        if "identity" not in columns:
            return {"cost_usd": 0, "latency": 0}
        row = conn.execute("SELECT COALESCE(SUM(actual),0),COALESCE(SUM(latency),0) FROM provider_reservations WHERE identity=?", (identity,)).fetchone()
    return {"cost_usd": row[0] / 1_000_000_000, "latency": row[1]}
