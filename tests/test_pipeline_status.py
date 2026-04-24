from __future__ import annotations

import json

import pytest

from porcaria import live_state
from porcaria.config.schema import Config, Profile
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
    live_state._reset_for_tests()
    # Pretend there's no XDG config so loader doesn't seed anything.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    def build() -> dict:
        return {"active_profile": "test", "servers": {}, "pid": 1}

    live_state.init(build_status=build)
    yield
    live_state._reset_for_tests()


def _read_snap() -> dict:
    return json.loads(live_state.status_path().read_text())


def test_start_recording_flips_recording_flag(monkeypatch):
    monkeypatch.setattr(dictate_pipeline.recorder, "is_recording", lambda: False)
    monkeypatch.setattr(dictate_pipeline.recorder, "start", lambda **kw: 4321)

    result = dictate_pipeline.start_recording(_cfg())
    assert result["status"] == "recording"
    snap = _read_snap()
    assert snap["recording"] is True
    assert snap["active"] == "recording"


def test_stop_and_process_phases_in_order(monkeypatch):
    # Seed as if a recording is live.
    live_state.set_recording(True)

    monkeypatch.setattr(dictate_pipeline.recorder, "is_recording", lambda: True)
    monkeypatch.setattr(dictate_pipeline.recorder, "stop", lambda: b"fakewav")

    observed: list[str] = []

    class FakeASR:
        def transcribe(self, wav):
            observed.append(_read_snap()["active"])
            return "hello world"

    class FakeLLM:
        def chat(self, system, user, temperature=0.0):
            observed.append(_read_snap()["active"])
            return "Hello, world."

    class FakeSpeaker:
        def __init__(self, *a, **kw): pass
        def handle(self, transcript, llm_output):
            observed.append(_read_snap()["active"])
            return SinkResult(ok=True, message="spoke")

    monkeypatch.setattr(dictate_pipeline, "get_asr", lambda cfg, name: FakeASR())
    monkeypatch.setattr(dictate_pipeline, "get_llm", lambda cfg, name: FakeLLM())
    monkeypatch.setattr(dictate_pipeline, "SpeakerSink", FakeSpeaker)

    result = dictate_pipeline.stop_and_process(
        _cfg(), clean=True, route="default", sinks="speaker"
    )
    assert result["status"] == "processed"
    assert observed == ["transcribing", "cleaning", "speaking"]
    # After completion, state returns to idle.
    snap = _read_snap()
    assert snap["active"] == "idle"
    assert snap["recording"] is False


def test_asr_exception_leaves_state_idle(monkeypatch):
    live_state.set_recording(True)

    monkeypatch.setattr(dictate_pipeline.recorder, "is_recording", lambda: True)
    monkeypatch.setattr(dictate_pipeline.recorder, "stop", lambda: b"fakewav")

    class BadASR:
        def transcribe(self, wav):
            raise RuntimeError("asr crashed")

    monkeypatch.setattr(dictate_pipeline, "get_asr", lambda cfg, name: BadASR())

    with pytest.raises(RuntimeError):
        dictate_pipeline.stop_and_process(_cfg(), clean=False, route="default", sinks=[])

    snap = _read_snap()
    assert snap["active"] == "idle"
    assert snap["recording"] is False
    assert snap["phase_stack"] == []


def test_recorder_stop_exception_still_clears_recording_flag(monkeypatch):
    live_state.set_recording(True)

    monkeypatch.setattr(dictate_pipeline.recorder, "is_recording", lambda: True)

    def boom():
        raise RuntimeError("stop failed")

    monkeypatch.setattr(dictate_pipeline.recorder, "stop", boom)

    with pytest.raises(RuntimeError):
        dictate_pipeline.stop_and_process(_cfg(), clean=False, route="default", sinks=[])

    snap = _read_snap()
    assert snap["recording"] is False
