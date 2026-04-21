"""TTS provider protocol."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class TTSProvider(Protocol):
    name: str

    def synth(
        self,
        text: str,
        *,
        voice: str | None = None,
        speed: float = 1.0,
    ) -> bytes:
        """Synthesize `text` to WAV bytes."""
        ...

    def health(self) -> bool:
        ...
