"""LLMProvider implementation for a local llama.cpp server (OpenAI-compatible)."""
from __future__ import annotations

import httpx

from porcaria.config.schema import LlamaCppCfg


class LlamaCppClient:
    name = "llamacpp"

    def __init__(self, cfg: LlamaCppCfg, *, timeout: float = 180.0) -> None:
        self._cfg = cfg
        self._timeout = timeout
        self._client = httpx.Client(
            base_url=cfg.url,
            timeout=timeout,
            transport=httpx.HTTPTransport(local_address="0.0.0.0"),
        )

    def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        payload: dict = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        if model:
            payload["model"] = model
        if max_tokens:
            payload["max_tokens"] = max_tokens
        r = self._client.post("/v1/chat/completions", json=payload)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]

    def health(self) -> bool:
        try:
            r = self._client.get("/health", timeout=2.0)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def close(self) -> None:
        self._client.close()
