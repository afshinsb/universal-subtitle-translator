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
