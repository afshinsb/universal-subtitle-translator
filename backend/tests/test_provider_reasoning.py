from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.config import settings
from app.services import translator


@pytest.mark.parametrize("effort,limit,expected", [
    (None, 0, {"temperature": 0.1}),
    ("medium", 32768, {"reasoning_effort": "medium", "max_completion_tokens": 32768}),
    ("none", 8192, {"reasoning_effort": "none", "max_completion_tokens": 8192}),
])
def test_provider_request_parameters(monkeypatch, effort, limit, expected):
    monkeypatch.delenv("UST_PILOT_BUDGET_FILE", raising=False)
    monkeypatch.setattr(settings, "openai_model", "gpt-6-luna")
    monkeypatch.setattr(settings, "openai_reasoning_effort", effort)
    monkeypatch.setattr(settings, "openai_max_completion_tokens", limit)
    client = MagicMock()
    client.__enter__.return_value = client
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="BEGIN[1]سلامEND[1]"))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30),
    )
    monkeypatch.setattr(translator, "get_openai_client", lambda: client)
    result = translator.call_openai("source")
    options = client.chat.completions.create.call_args.kwargs
    assert options["model"] == "gpt-6-luna"
    assert {k: v for k, v in options.items() if k not in {"model", "messages"}} == expected
    assert result.translations == {1: "سلام"}


def test_invalid_reasoning_fails_before_provider_request(monkeypatch):
    monkeypatch.setattr(settings, "openai_reasoning_effort", "unsupported")
    with pytest.raises(RuntimeError, match="OPENAI_REASONING_EFFORT"):
        translator.provider_request_options()
