import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from app.config import settings
from app.services import daily_budget, pilot_budget


@pytest.fixture
def daily(monkeypatch):
    monkeypatch.setattr(settings, "openai_daily_budget_usd", 0.05)
    monkeypatch.setattr(settings, "openai_budget_input_ceiling_per_1m", 0.125)
    monkeypatch.setattr(settings, "openai_budget_output_per_1m", 0.5)
    return {"reasoning_effort": "medium", "max_completion_tokens": 32768, "service_tier": "default"}


def test_medium_reservations_atomic_restart_safe_and_reasoning_usage(daily):
    def reserve(_):
        try:
            return daily_budget.reserve_daily("gpt-6-luna", "hello", daily)
        except daily_budget.DailyBudgetExceeded:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        reservations = [r for r in pool.map(reserve, range(8)) if r]
    assert len(reservations) == 3
    daily_budget.record_usage(reservations[0], SimpleNamespace(prompt_tokens=10,
        completion_tokens=100, completion_tokens_details=SimpleNamespace(reasoning_tokens=80)))
    # Unanswered calls retain their full reservations; reopening the ledger does not reset.
    with pytest.raises(daily_budget.DailyBudgetExceeded):
        daily_budget.reserve_daily("gpt-6-luna", "hello", daily)
    status = daily_budget.status()
    assert 0.049 < status["reserved_usd"] < 0.05
    assert status["reasoning_tokens"] == 80 and status["requests"] == 3
    with sqlite3.connect(daily_budget.ledger_path()) as conn:
        assert conn.execute("SELECT output_tokens FROM provider_reservations WHERE id=?", (reservations[0],)).fetchone()[0] == 100


def test_daily_rollover_preserves_old_reservations(daily, monkeypatch):
    monkeypatch.setattr(daily_budget, "utc_day", lambda: "2026-10-14")
    daily_budget.reserve_daily("gpt-6-luna", "hello", daily)
    monkeypatch.setattr(daily_budget, "utc_day", lambda: "2026-10-15")
    assert daily_budget.status()["reserved_usd"] == 0
    daily_budget.reserve_daily("gpt-6-luna", "hello", daily)
    with sqlite3.connect(daily_budget.ledger_path()) as conn:
        assert conn.execute("SELECT COUNT(DISTINCT day) FROM provider_reservations").fetchone()[0] == 2


def test_daily_price_config_cannot_reset_ledger(daily, monkeypatch):
    daily_budget.reserve_daily("gpt-6-luna", "hello", daily)
    monkeypatch.setattr(settings, "openai_daily_budget_usd", 0.10)
    with pytest.raises(RuntimeError, match="configuration changed"):
        daily_budget.reserve_daily("gpt-6-luna", "hello", daily)


@pytest.mark.parametrize("cap", [0, -1, 128001])
def test_daily_requires_output_cap(daily, cap):
    with pytest.raises(RuntimeError, match="bounded"):
        daily_budget.reserve_daily("gpt-6-luna", "hello", {**daily, "max_completion_tokens": cap})


def test_medium_pilot_is_scoped_and_sealed(tmp_path, monkeypatch):
    source = tmp_path / "english.srt"
    source.write_text("English dialogue")
    video = tmp_path / "approved.mkv"
    approval = tmp_path / "approval.json"
    cfg = {"approved": True, "model": "gpt-6-luna", "budget_usd": 0.05,
        "input_ceiling_per_million": 0.125, "output_per_million": 0.5,
        "max_completion_tokens": 32768, "reasoning_effort": "medium",
        "video_path": str(video), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    approval.write_text(json.dumps(cfg))
    monkeypatch.setenv("UST_PILOT_BUDGET_FILE", str(approval))
    with pytest.raises(RuntimeError, match="outside"):
        pilot_budget.reserve_request("gpt-6-luna", "dialogue")
    with pytest.raises(RuntimeError, match="does not match"):
        with pilot_budget.pilot_scope(tmp_path / "other.mkv", source):
            pass
    with pilot_budget.pilot_scope(video, source):
        for _ in range(3):
            options = pilot_budget.reserve_request("gpt-6-luna", "dialogue")
            assert options["reasoning_effort"] == "medium"
            assert options["max_completion_tokens"] == 32768
            assert "temperature" not in options
        with pytest.raises(RuntimeError, match="ceiling"):
            pilot_budget.reserve_request("gpt-6-luna", "dialogue")
    with pytest.raises(RuntimeError, match="outside"):
        pilot_budget.reserve_request("gpt-6-luna", "dialogue")
    source.write_text("changed")
    with pytest.raises(RuntimeError, match="does not match"):
        with pilot_budget.pilot_scope(video, source):
            pass


def test_invalid_pilot_effort_does_not_burn_reservation(tmp_path, monkeypatch):
    path = tmp_path / "approval.json"
    path.write_text(json.dumps({"approved": True, "model": "gpt-6-luna", "budget_usd": 1,
        "input_ceiling_per_million": 0.125, "output_per_million": 0.5,
        "max_completion_tokens": 32768, "reasoning_effort": "unsupported"}))
    monkeypatch.setenv("UST_PILOT_BUDGET_FILE", str(path))
    with pytest.raises(RuntimeError, match="reasoning effort"):
        pilot_budget.reserve_request("gpt-6-luna", "dialogue")
    assert not path.with_suffix(".json.sqlite").exists()


def test_failed_provider_calls_remain_reserved_and_sdk_retries_disabled(daily, monkeypatch):
    from unittest.mock import MagicMock
    from app.services import translator
    monkeypatch.delenv("UST_PILOT_BUDGET_FILE", raising=False)
    monkeypatch.setattr(settings, "openai_model", "gpt-6-luna")
    monkeypatch.setattr(settings, "openai_reasoning_effort", "medium")
    monkeypatch.setattr(settings, "openai_max_completion_tokens", 32768)
    client = MagicMock()
    client.base_url = "https://api.openai.com/v1"
    client.__enter__.return_value = client
    client.with_options.return_value = client
    client.chat.completions.create.side_effect = RuntimeError("transient failure")
    monkeypatch.setattr(translator, "get_openai_client", lambda: client)
    for _ in range(3):
        with pytest.raises(RuntimeError, match="transient"):
            translator.call_openai("dialogue")
    with pytest.raises(daily_budget.DailyBudgetExceeded):
        translator.call_openai("dialogue")
    assert client.chat.completions.create.call_count == 3
    client.with_options.assert_called_with(max_retries=0)
    assert daily_budget.status()["requests"] == 3
