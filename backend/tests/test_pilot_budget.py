import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from app.services.pilot_budget import reserve_request


def config(tmp_path, monkeypatch, **overrides):
    p = tmp_path / "approval.json"
    p.write_text(json.dumps({"approved": True, "model": "gpt-6-luna",
        "budget_usd": 0.01, "input_ceiling_per_million": 0.125,
        "output_per_million": 0.5, "max_completion_tokens": 8192,
        "reasoning_effort": "none", **overrides}))
    monkeypatch.setenv("UST_PILOT_BUDGET_FILE", str(p))
    return p


def test_disabled_guard_does_not_change_manual_behavior(monkeypatch):
    monkeypatch.delenv("UST_PILOT_BUDGET_FILE", raising=False)
    assert reserve_request("any-model", "dialogue") is None


def test_restart_and_failed_request_reservations_cannot_exceed_limit(tmp_path, monkeypatch):
    config(tmp_path, monkeypatch)
    for _ in range(2):
        params = reserve_request("gpt-6-luna", "hello")
        assert params["reasoning_effort"] == "none" and "temperature" not in params
    with pytest.raises(RuntimeError, match="ceiling"):
        reserve_request("gpt-6-luna", "hello")


def test_concurrent_reservations_are_atomic(tmp_path, monkeypatch):
    config(tmp_path, monkeypatch)
    def request(_):
        try:
            reserve_request("gpt-6-luna", "hello")
            return True
        except RuntimeError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(request, range(8))) == 2


def test_approval_and_config_are_pinned(tmp_path, monkeypatch):
    p = config(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="model"):
        reserve_request("gpt-4o-mini", "hello")
    reserve_request("gpt-6-luna", "hello")
    cfg = json.loads(p.read_text())
    cfg["budget_usd"] = 1
    p.write_text(json.dumps(cfg))
    with pytest.raises(RuntimeError, match="changed"):
        reserve_request("gpt-6-luna", "hello")


@pytest.mark.parametrize("limit", [0, -1, float("nan"), float("inf")])
def test_invalid_budget_fails_closed(tmp_path, monkeypatch, limit):
    config(tmp_path, monkeypatch, budget_usd=limit)
    with pytest.raises(RuntimeError):
        reserve_request("gpt-6-luna", "hello")


def test_usage_audit_does_not_release_reservations(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.services.pilot_budget import record_response
    p = config(tmp_path, monkeypatch)
    reserve_request("gpt-6-luna", "hello")
    class Usage:
        def model_dump(self, **kwargs):
            return {"prompt_tokens": 12, "completion_tokens": 30,
                    "completion_tokens_details": {"reasoning_tokens": 20},
                    "prompt_tokens_details": {"cached_tokens": 2, "cache_write_tokens": 5}}
    record_response(SimpleNamespace(usage=Usage(), model="gpt-6-luna", _request_id="req-fixture"), 1.25)
    reserve_request("gpt-6-luna", "hello")
    record_response(latency=2.5, error=TimeoutError())
    with pytest.raises(RuntimeError, match="ceiling"):
        reserve_request("gpt-6-luna", "hello")
    import sqlite3
    with sqlite3.connect(p.with_suffix(".json.sqlite")) as c:
        rows = c.execute("SELECT state,usage,latency,error_type FROM pilot_requests ORDER BY created").fetchall()
        assert len(rows) == 2 and rows[0][0] == "completed" and rows[1][0] == "uncertain"
        assert json.loads(rows[0][1])["completion_tokens_details"]["reasoning_tokens"] == 20
        assert rows[0][2] == 1.25 and rows[1][3] == "TimeoutError"
        assert c.execute("SELECT reserved FROM pilot_budget").fetchone()[0] > 0
