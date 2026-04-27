"""Wire types for the porcaria daemon IPC (JSON, one message per line).

Wire format: UTF-8 JSON per line. Request:
  {"id": "abc", "method": "status", "params": {...}}
Response:
  {"id": "abc", "ok": true,  "result": {...}}
  {"id": "abc", "ok": false, "error": {"code": "...", "message": "..."}}

Supported methods (Phase 1):
  ping                   -> {"pong": true}
  status                 -> providers + server health snapshot
  providers.list         -> profile-active providers
  providers.switch       -> swap a provider at runtime (e.g. {"kind":"llm","name":"openrouter"})
  dictate.toggle         -> start/stop recording; returns outcome
  transcribe             -> {"wav_b64": "..."}  ->  {"text": "..."}
  speak                  -> {"text": "...", "voice": "...", "speed": 1.0}  ->  {"wav_b64": "..."}
  clean                  -> {"text": "...", "style": "dictation"}  ->  {"text": "..."}
  task                   -> {"text": "..."} -> {"executed": [...]}
  secret                 -> {"text": "..."} -> {"ok": true, "message": "..."}
  servers.start          -> {"which": "all|asr|tts|llm", "model": "small|large"}
  servers.stop           -> {"which": "all|asr|tts|llm"}
  shutdown               -> shuts down the daemon
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Request:
    method: str
    params: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, s: str) -> Request:
        d = json.loads(s)
        return cls(method=d["method"], params=d.get("params") or {}, id=d.get("id") or uuid.uuid4().hex)


@dataclass
class Response:
    id: str
    ok: bool
    result: dict[str, Any] | None = None
    error: dict[str, str] | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, s: str) -> Response:
        d = json.loads(s)
        return cls(id=d["id"], ok=d["ok"], result=d.get("result"), error=d.get("error"))

    @classmethod
    def success(cls, req_id: str, result: dict[str, Any] | None = None) -> Response:
        return cls(id=req_id, ok=True, result=result or {})

    @classmethod
    def failure(cls, req_id: str, code: str, message: str) -> Response:
        return cls(id=req_id, ok=False, error={"code": code, "message": message})
