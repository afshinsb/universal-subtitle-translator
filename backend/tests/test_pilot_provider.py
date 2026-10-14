from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.services import translator
from app.services.pilot_budget import SYSTEM_PROMPT


def test_guarded_provider_disables_sdk_retries_and_sets_bounded_parameters(monkeypatch):
    client = MagicMock()
    client.base_url = "https://api.openai.com/v1/"
    client.__enter__.return_value = client
    bounded = client.with_options.return_value
    bounded.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="BEGIN[7]\nسلام\nEND[7]"))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15))
    monkeypatch.setenv("UST_PILOT_BUDGET_FILE", "/unused/private/config.json")
    monkeypatch.setattr(translator, "get_openai_client", lambda: client)
    monkeypatch.setattr(translator, "reserve_request", lambda *args: {
        "max_completion_tokens":8192,"reasoning_effort":"none","service_tier":"default"})
    assert translator.call_openai("source").translations == {7:"سلام"}
    client.with_options.assert_called_once_with(max_retries=0)
    params = bounded.chat.completions.create.call_args.kwargs
    assert params["max_completion_tokens"] == 8192 and "temperature" not in params
    assert params["messages"][0]["content"] == SYSTEM_PROMPT


def test_guard_failure_prevents_provider_request(monkeypatch):
    client = MagicMock()
    client.base_url = "https://api.openai.com/v1/"
    client.__enter__.return_value = client
    monkeypatch.setattr(translator, "get_openai_client", lambda: client)
    def exhausted(*args):
        raise RuntimeError("ceiling reached")
    monkeypatch.setattr(translator, "reserve_request", exhausted)
    with pytest.raises(RuntimeError, match="ceiling"):
        translator.call_openai("source")
    client.chat.completions.create.assert_not_called()
    client.with_options.assert_not_called()
