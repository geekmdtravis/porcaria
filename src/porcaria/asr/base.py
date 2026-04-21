"""ASR provider protocol."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ASRProvider(Protocol):
    name: str

    def transcribe(self, wav: bytes, *, sample_rate: int = 16000) -> str:
        """Transcribe a WAV-formatted audio blob; return plain text."""
        ...

    def health(self) -> bool:
        """Return True if the provider is reachable and ready."""
        ...
