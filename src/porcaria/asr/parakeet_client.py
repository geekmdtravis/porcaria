"""ASRProvider implementation talking to the parakeet HTTP server."""
from __future__ import annotations

import httpx

from porcaria.config.schema import ParakeetCfg


class ParakeetClient:
    name = "parakeet"

    def __init__(self, cfg: ParakeetCfg, *, timeout: float = 120.0) -> None:
        self._cfg = cfg
        self._timeout = timeout
        # Persistent client: TCP-reuse, IPv4-only (skip happy-eyeballs stall),
        # HTTP/1.1 (the stdlib server speaks HTTP/1.0 but httpx downgrades cleanly).
        self._client = httpx.Client(
            base_url=cfg.url,
            timeout=timeout,
            transport=httpx.HTTPTransport(local_address="0.0.0.0"),
        )

    def transcribe(self, wav: bytes, *, sample_rate: int = 16000) -> str:
        r = self._client.post(
            "/transcribe",
            content=wav,
            headers={"Content-Type": "application/octet-stream"},
        )
        if r.status_code != 200:
            raise RuntimeError(
                f"parakeet /transcribe returned {r.status_code}: {r.text[:500]}"
            )
        return r.text.strip()

    def health(self) -> bool:
        try:
            r = self._client.get("/health", timeout=2.0)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def close(self) -> None:
        self._client.close()
