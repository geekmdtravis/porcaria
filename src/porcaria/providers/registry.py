"""Central registry mapping provider names → factory callables.

Adding a new ASR/TTS/LLM backend is two steps:
    1) implement the Protocol (transcribe()/synth()/chat() + health())
    2) register its factory in the corresponding dict below

Third-party providers can also register via the `porcaria.sinks` /
`porcaria.providers` entry-point group (Phase 5).

Provider instances are memoized by (kind, name, url) so the persistent
httpx.Client inside each provider survives across calls.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from porcaria.asr.base import ASRProvider
from porcaria.config.schema import Config
from porcaria.llm.base import LLMProvider
from porcaria.tts.base import TTSProvider

_INSTANCE_CACHE: dict[tuple[str, str, str], Any] = {}


def _cache_key(kind: str, name: str, cfg: Config) -> tuple[str, str, str]:
    """Memoization key includes the URL so a config reload with a new URL
    transparently rebuilds the client."""
    url = ""
    match kind:
        case "asr":
            url = getattr(getattr(cfg.asr, name, None), "url", "") or ""
        case "tts":
            url = getattr(getattr(cfg.tts, name, None), "url", "") or ""
        case "llm":
            url = getattr(getattr(cfg.llm, name, None), "url", "") or ""
    return (kind, name, url)


def reset_cache() -> None:
    """Close any pooled clients and forget cached instances. Call on daemon reload."""
    for inst in list(_INSTANCE_CACHE.values()):
        close = getattr(inst, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
    _INSTANCE_CACHE.clear()


class UnknownProvider(KeyError):
    """Raised when a profile references a provider name with no registered factory."""


# ----- ASR -----


def _make_parakeet(cfg: Config) -> ASRProvider:
    from porcaria.asr.parakeet_client import ParakeetClient

    return ParakeetClient(cfg.asr.parakeet)


ASR_FACTORIES: dict[str, Callable[[Config], ASRProvider]] = {
    "parakeet": _make_parakeet,
    # Cloud/alternative backends land in Phase 4:
    #   "whisper_cpp": _make_whisper_cpp,
    #   "openai_whisper": _make_openai_whisper,
}


def get_asr(cfg: Config, name: str) -> ASRProvider:
    factory = ASR_FACTORIES.get(name)
    if factory is None:
        raise UnknownProvider(f"unknown ASR provider '{name}'; registered: {sorted(ASR_FACTORIES)}")
    key = _cache_key("asr", name, cfg)
    if key not in _INSTANCE_CACHE:
        _INSTANCE_CACHE[key] = factory(cfg)
    return _INSTANCE_CACHE[key]


def list_asr() -> list[str]:
    return sorted(ASR_FACTORIES)


# ----- TTS -----


def _make_kokoro(cfg: Config) -> TTSProvider:
    from porcaria.tts.kokoro_client import KokoroClient

    return KokoroClient(cfg.tts.kokoro)


TTS_FACTORIES: dict[str, Callable[[Config], TTSProvider]] = {
    "kokoro": _make_kokoro,
    # "openai_tts": _make_openai_tts,       # Phase 4
    # "elevenlabs": _make_elevenlabs,       # Phase 4
    # "none":       _make_none,             # Phase 4
}


def get_tts(cfg: Config, name: str) -> TTSProvider:
    factory = TTS_FACTORIES.get(name)
    if factory is None:
        raise UnknownProvider(f"unknown TTS provider '{name}'; registered: {sorted(TTS_FACTORIES)}")
    key = _cache_key("tts", name, cfg)
    if key not in _INSTANCE_CACHE:
        _INSTANCE_CACHE[key] = factory(cfg)
    return _INSTANCE_CACHE[key]


def list_tts() -> list[str]:
    return sorted(TTS_FACTORIES)


# ----- LLM -----


def _make_llamacpp(cfg: Config) -> LLMProvider:
    from porcaria.llm.llamacpp import LlamaCppClient

    return LlamaCppClient(cfg.llm.llamacpp)


LLM_FACTORIES: dict[str, Callable[[Config], LLMProvider]] = {
    "llamacpp": _make_llamacpp,
    # "openrouter": _make_openrouter,       # Phase 4
}


def get_llm(cfg: Config, name: str) -> LLMProvider:
    factory = LLM_FACTORIES.get(name)
    if factory is None:
        raise UnknownProvider(f"unknown LLM provider '{name}'; registered: {sorted(LLM_FACTORIES)}")
    key = _cache_key("llm", name, cfg)
    if key not in _INSTANCE_CACHE:
        _INSTANCE_CACHE[key] = factory(cfg)
    return _INSTANCE_CACHE[key]


def list_llm() -> list[str]:
    return sorted(LLM_FACTORIES)
