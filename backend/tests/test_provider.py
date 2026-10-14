from types import SimpleNamespace

import pytest

from app.services import translator, job_runner


def result(text, tokens):
    return translator.TranslationResult({1: text}, tokens, tokens, tokens * 2, "", [1], [], 0)


def test_persian_retry_accounts_for_both_requests(monkeypatch):
    replies = iter([result("Hello", 10), result("سلام", 20)])
    monkeypatch.setattr(translator, "call_openai", lambda prompt: next(replies))
    output = translator.translate_batch([{"index": 1, "text": "Hello"}], "Persian", "formal")
    assert output.translations == {1: "سلام"}
    assert (output.input_tokens, output.output_tokens, output.total_tokens) == (30, 30, 60)
    assert output.attempts == 2


def test_missing_provider_choices_close_client_and_fail_cleanly(monkeypatch):
    closed = []
    class Client:
        chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: SimpleNamespace(choices=[])))
        def __enter__(self):
            return self
        def __exit__(self, *args):
            closed.append(True)
    monkeypatch.setattr(translator, "get_openai_client", Client)
    with pytest.raises(RuntimeError, match="no choices"):
        translator.call_openai("fixture")
    assert closed == [True]


def test_provider_key_is_redacted_in_error_messages(monkeypatch):
    monkeypatch.setattr(job_runner.settings, "openai_api_key", "sk-fixture-sensitive")
    assert "sk-fixture-sensitive" not in job_runner.friendly_error_message("Unexpected header sk-fixture-sensitive")
