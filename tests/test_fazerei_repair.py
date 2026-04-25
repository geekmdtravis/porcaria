"""Tests for the fazerei single-shot repair loop and failure-message enrichment.

These tests are hermetic — they never invoke the real `fazerei` binary. The
LLM is replaced with a `_FakeLLM` that returns scripted responses, and inputs
are chosen so the executor either hits the FAZEREI_SKIP fast-path or rejects
every line at the whitelist stage (no subprocess fires).
"""
from __future__ import annotations

import pytest

from porcaria.config.schema import FazereiCfg
from porcaria.sinks.fazerei import _to_result, run_with_repair
from porcaria.sinks.fazerei.executor import CmdOutcome, RunReport


class _FakeLLM:
    """Returns the next scripted response per .chat() call. Records prompts."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def chat(self, system: str, user: str, temperature: float = 0.0) -> str:
        self.calls.append((system, user))
        if not self._responses:
            raise AssertionError("FakeLLM ran out of scripted responses")
        return self._responses.pop(0)


@pytest.fixture
def cfg() -> FazereiCfg:
    return FazereiCfg()


# ---- run_with_repair ------------------------------------------------------


def test_repair_skips_when_first_call_returns_skip_signal(cfg: FazereiCfg):
    llm = _FakeLLM(["FAZEREI_SKIP"])
    result, raw = run_with_repair(cfg, llm, "system", "what's the weather like")
    assert len(llm.calls) == 1, "should not retry on FAZEREI_SKIP"
    assert not result.ok
    assert "skipped" in result.message
    assert raw == "FAZEREI_SKIP"


def test_repair_fires_when_every_line_is_rejected(cfg: FazereiCfg):
    # First reply: every line starts with the wrong binary → all rejected, no exec.
    # Second reply: also rejected (so we don't have to worry about subprocess).
    llm = _FakeLLM([
        "echo not-a-fazerei-command\nls -la\n",
        "still bogus prose with no fazerei lines",
    ])
    result, raw = run_with_repair(cfg, llm, "system", "add buy milk")
    assert len(llm.calls) == 2, "should retry once when all lines are rejected"
    # The second user message must contain a repair preamble + the prior output + errors.
    repair_user_msg = llm.calls[1][1]
    assert "could not be executed" in repair_user_msg
    assert "echo not-a-fazerei-command" in repair_user_msg
    assert "Original request: add buy milk" in repair_user_msg
    # Final result reflects the second attempt (also a failure here).
    assert not result.ok
    assert raw.startswith("still bogus")


def test_repair_fires_when_output_yields_zero_parsed_lines(cfg: FazereiCfg):
    # All output lines are filtered out by sanitize_line (fences + lang tags).
    llm = _FakeLLM([
        "```bash\n```\n",
        "FAZEREI_SKIP",
    ])
    result, _ = run_with_repair(cfg, llm, "system", "anything")
    assert len(llm.calls) == 2
    repair_user_msg = llm.calls[1][1]
    # No outcomes existed, so the helper should fall back to the generic guidance.
    assert "No lines could be parsed" in repair_user_msg
    # Second call returned SKIP, so the final result is the "skipped" message.
    assert "skipped" in result.message


def test_no_repair_when_first_attempt_fully_succeeds(cfg: FazereiCfg, monkeypatch):
    # Patch run_commands so we don't need a real fazerei binary; simulate full success.
    from porcaria.sinks.fazerei import executor as ex

    fake = RunReport(outcomes=[CmdOutcome("fazerei done 3", "done", True)])

    def _fake_run(_cfg, _llm_output):
        return fake

    monkeypatch.setattr(ex, "run_commands", _fake_run)
    llm = _FakeLLM(["fazerei done 3"])
    result, _ = run_with_repair(cfg, llm, "system", "mark task 3 done")
    assert len(llm.calls) == 1, "no repair when the first attempt has at least one ok"
    assert result.ok


def test_no_repair_when_runtime_failure_but_classify_succeeded(cfg: FazereiCfg, monkeypatch):
    # If the verb classified fine but `fazerei` itself returned non-zero, that's a
    # runtime failure — repairing won't help (the LLM emitted a syntactically valid
    # command). Verify we don't burn a second call.
    from porcaria.sinks.fazerei import executor as ex

    fake = RunReport(outcomes=[
        CmdOutcome("fazerei done 9999", "done", False, error="exited 1"),
    ])

    def _fake_run(_cfg, _llm_output):
        return fake

    monkeypatch.setattr(ex, "run_commands", _fake_run)
    llm = _FakeLLM(["fazerei done 9999"])
    result, _ = run_with_repair(cfg, llm, "system", "mark task 9999 done")
    assert len(llm.calls) == 1, "runtime failure must not trigger LLM repair"
    assert not result.ok


# ---- _to_result message enrichment ---------------------------------------


def test_to_result_message_includes_failure_diagnostics():
    report = RunReport(outcomes=[
        CmdOutcome("fazerei add 'ok'", "add", True),
        CmdOutcome("nonsense line", "", False, error="rejected: not a whitelisted fazerei command"),
    ])
    result = _to_result(report)
    assert not result.ok
    assert "1 failed" in result.message
    # The user must see WHICH line failed and WHY.
    assert "nonsense line" in result.message
    assert "rejected" in result.message


def test_to_result_truncates_long_diagnostics():
    long_line = "x" * 1000
    report = RunReport(outcomes=[
        CmdOutcome(long_line, "", False, error="rejected"),
    ])
    result = _to_result(report)
    # Hard cap on diagnostic chars (300) — message itself is a bit longer than that
    # because of the surrounding "(N failed (..."), but the embedded diag is bounded.
    assert "…" in result.message
