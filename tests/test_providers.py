from __future__ import annotations

from pathlib import Path

import pytest

from porcaria.config import load_config
from porcaria.providers import UnknownProvider, get_asr, get_llm, get_tts, list_asr, list_llm, list_tts


def _cfg():
    return load_config(user_file=Path("/nonexistent"))


def test_registry_lists_phase2_providers():
    assert "parakeet" in list_asr()
    assert "kokoro" in list_tts()
    assert "llamacpp" in list_llm()


def test_asr_factory_returns_protocol_instance():
    cfg = _cfg()
    p = get_asr(cfg, "parakeet")
    assert p.name == "parakeet"
    assert hasattr(p, "transcribe")
    assert hasattr(p, "health")


def test_tts_factory_returns_protocol_instance():
    cfg = _cfg()
    t = get_tts(cfg, "kokoro")
    assert t.name == "kokoro"
    assert hasattr(t, "synth")


def test_llm_factory_returns_protocol_instance():
    cfg = _cfg()
    m = get_llm(cfg, "llamacpp")
    assert m.name == "llamacpp"
    assert hasattr(m, "chat")


def test_unknown_provider_names_raise():
    cfg = _cfg()
    with pytest.raises(UnknownProvider):
        get_asr(cfg, "does-not-exist")
    with pytest.raises(UnknownProvider):
        get_tts(cfg, "does-not-exist")
    with pytest.raises(UnknownProvider):
        get_llm(cfg, "does-not-exist")
