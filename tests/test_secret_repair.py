from __future__ import annotations

from porcaria.config.schema import SecretCfg
from porcaria.sinks.secret import run_with_repair


class _FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def chat(self, system: str, user: str, temperature: float = 0.0) -> str:
        self.calls.append((system, user))
        if not self._responses:
            raise AssertionError("FakeLLM ran out of scripted responses")
        return self._responses.pop(0)


def test_no_repair_when_llm_reports_not_found():
    llm = _FakeLLM(["PASS_NOT_FOUND"])
    result, raw = run_with_repair(SecretCfg(), llm, "system", "copy missing password")

    assert len(llm.calls) == 1
    assert raw == "PASS_NOT_FOUND"
    assert not result.ok
    assert result.message == "I couldn't find a matching password under porcaria-accessible."
    assert result.artifact == "not_found"


def test_no_repair_when_llm_skips():
    llm = _FakeLLM(["PASS_SKIP"])
    result, raw = run_with_repair(SecretCfg(), llm, "system", "never mind")

    assert len(llm.calls) == 1
    assert raw == "PASS_SKIP"
    assert not result.ok
    assert result.message == "I didn't hear a password request."
    assert result.artifact == "skipped"


def test_password_request_skip_is_reinterpreted_as_not_found():
    llm = _FakeLLM(["PASS_SKIP"])
    result, raw = run_with_repair(SecretCfg(), llm, "system", "copy my google password")

    assert len(llm.calls) == 1
    assert raw == "PASS_SKIP"
    assert not result.ok
    assert result.message == "I couldn't find a matching password under porcaria-accessible."
    assert result.artifact == "not_found"


def test_no_repair_when_selected_entry_is_not_in_pass_list(monkeypatch):
    from porcaria.sinks.secret import executor

    monkeypatch.setattr(executor, "list_entries", lambda cfg: [])
    llm = _FakeLLM(["PASS_COPY porcaria-accessible/missing"])
    result, raw = run_with_repair(SecretCfg(), llm, "system", "copy missing password")

    assert len(llm.calls) == 1
    assert raw == "PASS_COPY porcaria-accessible/missing"
    assert not result.ok
    assert result.message == "I couldn't find a matching password under porcaria-accessible."
    assert result.artifact == "not_found"


def test_repair_still_fires_for_invalid_format():
    llm = _FakeLLM(["echo nope", "PASS_NOT_FOUND"])
    result, raw = run_with_repair(SecretCfg(), llm, "system", "copy missing password")

    assert len(llm.calls) == 2
    assert "could not be executed" in llm.calls[1][1]
    assert raw == "PASS_NOT_FOUND"
    assert result.message == "I couldn't find a matching password under porcaria-accessible."
    assert result.artifact == "not_found"
