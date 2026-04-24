from __future__ import annotations

import json

import pytest

from porcaria import live_state, notify
from porcaria.config.schema import Config
from porcaria.pipeline import dictate as dictate_pipeline
from porcaria.sinks.base import SinkResult


def _cfg() -> Config:
    return Config.model_validate(
        {
            "active_profile": "test",
            "profiles": {"test": {"asr": "parakeet", "tts": "kokoro", "llm": "llamacpp", "sinks": []}},
        }
    )


@pytest.fixture(autouse=True)
def _isolated_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    live_state._reset_for_tests()
    live_state.init(build_status=lambda: {"servers": {}, "pid": 1})
    yield
    live_state._reset_for_tests()


def test_successful_destinations_filters_failures():
    rs = [
        {"sink": "clipboard", "ok": True, "message": "…"},
        {"sink": "speaker", "ok": False, "message": "oops"},
        {"route": "task", "ok": True, "message": "done"},
    ]
    assert dictate_pipeline._successful_destinations(rs) == ["clipboard", "task"]


def test_successful_destinations_empty_when_all_failed():
    rs = [
        {"sink": "clipboard", "ok": False, "message": "oops"},
        {"route": "task", "ok": False, "message": "oops"},
    ]
    assert dictate_pipeline._successful_destinations(rs) == []


def _install_spy(monkeypatch):
    """Re-install the real notify.success but capture the title/body."""
    calls: list[tuple[str, str]] = []

    def spy(title, body=""):
        calls.append((title, body))
        return True

    monkeypatch.setattr(notify, "success", spy)
    return calls


def _run_stop(monkeypatch, *, clean: bool, route: str, sinks):
    monkeypatch.setattr(dictate_pipeline.recorder, "is_recording", lambda: True)
    monkeypatch.setattr(dictate_pipeline.recorder, "stop", lambda: b"fakewav")

    class FakeASR:
        def transcribe(self, wav):
            return "hello world"

    class FakeLLM:
        def chat(self, system, user, temperature=0.0):
            return "Hello, world."

    class FakeClipboard:
        def __init__(self, *a, **kw): pass
        def handle(self, transcript, llm_output):
            return SinkResult(ok=True, message="copied")

    class FakeNote:
        def __init__(self, *a, **kw): pass
        def handle(self, transcript, llm_output):
            return SinkResult(ok=True, message="appended")

    class FakeSpeaker:
        def __init__(self, *a, **kw): pass
        def handle(self, transcript, llm_output):
            return SinkResult(ok=True, message="spoke")

    monkeypatch.setattr(dictate_pipeline, "get_asr", lambda cfg, name: FakeASR())
    monkeypatch.setattr(dictate_pipeline, "get_llm", lambda cfg, name: FakeLLM())
    monkeypatch.setattr(dictate_pipeline, "ClipboardSink", FakeClipboard)
    monkeypatch.setattr(dictate_pipeline, "QuickNoteSink", FakeNote)
    monkeypatch.setattr(dictate_pipeline, "SpeakerSink", FakeSpeaker)

    return dictate_pipeline.stop_and_process(_cfg(), clean=clean, route=route, sinks=sinks)


def test_summary_single_sink(monkeypatch):
    calls = _install_spy(monkeypatch)
    _run_stop(monkeypatch, clean=False, route="default", sinks="clipboard")
    assert calls, "expected a notify.success call"
    title, _body = calls[-1]
    assert title == "Dictation → clipboard"


def test_summary_multiple_sinks(monkeypatch):
    calls = _install_spy(monkeypatch)
    _run_stop(monkeypatch, clean=False, route="default", sinks="clipboard,note")
    title, _body = calls[-1]
    assert title == "Dictation → clipboard + note"


def test_summary_cleaned_prefix(monkeypatch):
    calls = _install_spy(monkeypatch)
    _run_stop(monkeypatch, clean=True, route="default", sinks="clipboard")
    title, _body = calls[-1]
    assert title == "Cleaned dictation → clipboard"


def test_summary_task_route_with_sink(monkeypatch):
    calls = _install_spy(monkeypatch)

    # Stub out fazerei's handler so the task leg reports success without running a real command.
    class FakeFazereiSink:
        def __init__(self, *a, **kw): pass
        def system_prompt(self, ctx): return ""
        def handle(self, transcript, llm_output):
            return SinkResult(ok=True, message="fazerei ran")

    monkeypatch.setattr(dictate_pipeline, "FazereiSink", FakeFazereiSink)

    _run_stop(monkeypatch, clean=False, route="task", sinks="clipboard")
    title, body = calls[-1]
    assert title == "Dictation → task + clipboard"
    assert "chars" in body  # body still carries metrics


def test_summary_skipped_when_no_destinations(monkeypatch):
    """If nothing was delivered, no 'complete' notification — the 'has no sinks' warn already fired."""
    calls = _install_spy(monkeypatch)
    _run_stop(monkeypatch, clean=False, route="default", sinks=[])
    # No success call — the empty-sinks warning path handled messaging.
    assert calls == []
