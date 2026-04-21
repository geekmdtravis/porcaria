"""LLM provider protocol."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Send a single-turn chat; return the assistant's text."""
        ...

    def health(self) -> bool:
        ...
