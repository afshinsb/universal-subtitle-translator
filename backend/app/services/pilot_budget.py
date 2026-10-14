"""Opt-in persistent request reservations for an explicitly approved pilot.

Unset UST_PILOT_BUDGET_FILE leaves normal/manual translation behavior unchanged.
Reservations are never refunded: failed/ambiguous requests may be billable.
The config and ledger belong in private development data, never the library.
"""
import json
import os
import sqlite3
from decimal import Decimal, ROUND_CEILING
from pathlib import Path


SYSTEM_PROMPT = "You translate subtitles. You must obey the requested target language and block format exactly."


def reserve_request(model, prompt):
    filename = os.getenv("UST_PILOT_BUDGET_FILE")
    if not filename:
        return None
    config_path = Path(filename)
    cfg = json.loads(config_path.read_text())
    if cfg.get("approved") is not True or cfg.get("model") != model:
        raise RuntimeError("Pilot approval/model does not match this request.")
    # A sealed, operator-approved rate/config file is fixed for this ledger.
    budget = Decimal(str(cfg["budget_usd"]))
    input_rate = Decimal(str(cfg["input_ceiling_per_million"]))
    output_rate = Decimal(str(cfg["output_per_million"]))
    output_cap = cfg["max_completion_tokens"]
    if not all(v.is_finite() and v > 0 for v in (budget, input_rate, output_rate)):
        raise RuntimeError("Pilot budget and rates must be positive and finite.")
    if type(output_cap) is not int or not 1 <= output_cap <= 16384:
        raise RuntimeError("Invalid pilot completion cap.")
    input_bound = len((SYSTEM_PROMPT + prompt).encode("utf-8")) + 1024
    if input_bound > 272000:
        raise RuntimeError("Pilot request exceeds the priced short-context bound.")
    def units(value):
        return int((value * 1_000_000_000).to_integral_value(rounding=ROUND_CEILING))
    reserve = units((input_bound * input_rate + output_cap * output_rate) / 1_000_000)
    limit = int(budget * 1_000_000_000)
    # Do not accept a different budget/rate/model after requests have been reserved.
    fingerprint = json.dumps(cfg, sort_keys=True)
    ledger = config_path.with_suffix(config_path.suffix + ".sqlite")
    with sqlite3.connect(ledger, timeout=30) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS pilot_budget (id INTEGER PRIMARY KEY CHECK(id=1), config TEXT NOT NULL, reserved INTEGER NOT NULL)")
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT config,reserved FROM pilot_budget WHERE id=1").fetchone()
        if row and row[0] != fingerprint:
            raise RuntimeError("Pilot configuration changed; use a separately approved new ledger.")
        spent = row[1] if row else 0
        if spent + reserve > limit:
            raise RuntimeError("Pilot spending ceiling reached; no provider request made.")
        conn.execute("INSERT OR REPLACE INTO pilot_budget VALUES (1,?,?)", (fingerprint, spent + reserve))
    kwargs = {"max_completion_tokens": output_cap, "service_tier": "default"}
    if cfg.get("reasoning_effort") is not None:
        if cfg["reasoning_effort"] != "none":
            raise RuntimeError("Pilot uses reasoning_effort=none only.")
        kwargs["reasoning_effort"] = "none"
    else:
        kwargs["temperature"] = 0.1
    return kwargs
