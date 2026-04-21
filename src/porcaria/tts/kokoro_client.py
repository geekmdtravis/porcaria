"""TTSProvider implementation talking to the kokoro HTTP server."""
from __future__ import annotations

import httpx

from porcaria.config.schema import KokoroCfg


class KokoroClient:
    name = "kokoro"

    def __init__(self, cfg: KokoroCfg, *, timeout: float = 60.0) -> None:
        self._cfg = cfg
        self._timeout = timeout
        self._client = httpx.Client(
            base_url=cfg.url,
            timeout=timeout,
            transport=httpx.HTTPTransport(local_address="0.0.0.0"),
        )

    def synth(self, text: str, *, voice: str | None = None, speed: float = 1.0) -> bytes:
        payload = {
            "text": text,
            "voice": voice or self._cfg.voice,
            "speed": speed or self._cfg.speed,
        }
        r = self._client.post("/speak", json=payload)
        r.raise_for_status()
        return r.content

    def health(self) -> bool:
        try:
            r = self._client.get("/health", timeout=2.0)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def close(self) -> None:
        self._client.close()
