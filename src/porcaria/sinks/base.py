"""Sink protocol: how a transcript (+ optional LLM output) is delivered."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass
class DictationContext:
    """Non-secret context passed to sinks to help them build prompts."""

    now: datetime
    profile: str
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class SinkResult:
    ok: bool
    message: str = ""
    artifact: str | None = None  # e.g. a file path, clipboard hash, fazerei output


@runtime_checkable
class Sink(Protocol):
    name: str

    def system_prompt(self, ctx: DictationContext) -> str | None:
        """Return an LLM system prompt, or None if this sink doesn't need LLM processing."""
        ...

    def handle(self, transcript: str, llm_output: str | None) -> SinkResult:
        """Deliver the transcript (and/or LLM output) to the sink's destination."""
        ...
