"""Persistent HTTP server wrapping nano-parakeet ASR.

Loaded once at startup; serves transcription over HTTP so the dictation pipeline
pays cold-start latency once per session. Ships with porcaria but only imports
torch/nano-parakeet inside main() so the rest of the package stays usable on
machines without GPU deps.

Endpoints:
    GET  /health      -> {"status": "ok"}
    POST /transcribe  -> text/plain transcript
        Body: raw audio bytes (typical: WAV 16kHz mono PCM16)
              or multipart/form-data with a 'file' field

Run as:
    python -m porcaria.asr.parakeet_server --port 5092 --device cuda \\
           --model nvidia/parakeet-tdt-0.6b-v3
"""
from __future__ import annotations

import argparse
import email
import email.parser
import io
import json
import signal
import struct
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

# Lazy: torch, numpy, nano_parakeet imported inside main().
_MODEL: Any = None  # set by main()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: ARG002
        sys.stderr.write(f"[parakeet] {args[0] if args else ''}\n")

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(200, {"status": "ok"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/transcribe":
            self._json(404, {"error": "not found"})
            return
        try:
            audio = self._read_audio()
            if audio is None:
                return
            text = self._transcribe(audio)
            body = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:  # noqa: BLE001
            self._json(500, {"error": str(e)})

    # --- request parsing ---

    def _read_audio(self) -> bytes | None:
        cl = int(self.headers.get("Content-Length") or 0)
        if cl <= 0:
            self._json(400, {"error": "empty request body"})
            return None
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" in ctype:
            return _parse_multipart_file(self.rfile.read(cl), ctype)
        return self.rfile.read(cl)

    # --- transcription ---

    def _transcribe(self, audio: bytes) -> str:
        import time as _t

        import numpy as np
        import torch

        t0 = _t.monotonic()
        if _is_wav_16k_mono_pcm16(audio):
            offset = _find_wav_data_offset(audio)
            if offset is not None:
                pcm = audio[offset:]
                arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
                t_prep = _t.monotonic() - t0
                t1 = _t.monotonic()
                token_ids = _MODEL.transcribe_audio(torch.from_numpy(arr))
                text = _MODEL.sp.DecodeIds(token_ids).strip()
                t_infer = _t.monotonic() - t1
                sys.stderr.write(
                    f"[parakeet] fast_path bytes={len(audio)} prep={t_prep:.3f}s infer={t_infer:.3f}s\n"
                )
                return text

        from nano_parakeet.audio import convert_to_wav16k, load_audio

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
            tmp.write(audio)
            tmp.flush()
            wav_path = convert_to_wav16k(tmp.name)
            arr = load_audio(wav_path)
        t_prep = _t.monotonic() - t0
        t1 = _t.monotonic()
        token_ids = _MODEL.transcribe_audio(torch.from_numpy(arr))
        text = _MODEL.sp.DecodeIds(token_ids).strip()
        t_infer = _t.monotonic() - t1
        sys.stderr.write(
            f"[parakeet] slow_path bytes={len(audio)} prep={t_prep:.3f}s infer={t_infer:.3f}s\n"
        )
        return text

    def _json(self, code: int, obj: dict[str, Any]) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# -------------------------------- WAV helpers --------------------------------


def _find_chunk(audio: bytes, chunk_id: bytes) -> int | None:
    """Return the offset of the given chunk's payload (i.e. past the 8-byte
    header), or None if not found. Walks chunk sizes when they're sane, and
    falls back to a direct byte-scan if a chunk size claims to overrun the
    buffer (e.g. streaming WAVs that write 0xFFFFFFFF sizes)."""
    if len(audio) < 12:
        return None
    offset = 12
    while offset + 8 <= len(audio):
        try:
            cid, size = struct.unpack_from("<4sI", audio, offset)
        except struct.error:
            break
        if cid == chunk_id:
            return offset + 8
        step = 8 + size + (size % 2)
        if size > len(audio) or offset + step > len(audio) or step <= 8:
            # Unreliable size — bail out of structured walk.
            break
        offset += step
    # Fallback: linear scan for the chunk id.
    idx = audio.find(chunk_id, 12)
    if idx < 0:
        return None
    return idx + 8


def _is_wav_16k_mono_pcm16(audio: bytes) -> bool:
    if len(audio) < 44:
        return False
    try:
        riff, _, wave = struct.unpack_from("<4sI4s", audio, 0)
    except struct.error:
        return False
    if riff != b"RIFF" or wave != b"WAVE":
        return False
    fmt_off = _find_chunk(audio, b"fmt ")
    if fmt_off is None or fmt_off + 16 > len(audio):
        return False
    try:
        audio_fmt, num_channels, sample_rate = struct.unpack_from("<HHI", audio, fmt_off)
        bits = struct.unpack_from("<H", audio, fmt_off + 14)[0]
    except struct.error:
        return False
    return (
        audio_fmt == 1
        and num_channels == 1
        and sample_rate == 16000
        and bits == 16
    )


def _find_wav_data_offset(audio: bytes) -> int | None:
    return _find_chunk(audio, b"data")


# ----------------------------- multipart parsing -----------------------------


def _parse_multipart_file(body: bytes, content_type: str) -> bytes | None:
    """Extract the 'file' field from a multipart/form-data body.

    Uses email.parser, which is in stdlib and didn't go away with cgi in 3.13.
    """
    headers = f"Content-Type: {content_type}\r\n\r\n".encode() + body
    msg = email.parser.BytesParser().parsebytes(headers)
    if not msg.is_multipart():
        return None
    for part in msg.iter_parts():
        cd = part.get("Content-Disposition", "")
        if 'name="file"' in cd:
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                return payload
    return None


# ----------------------------------- main ------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="Parakeet ASR HTTP server")
    ap.add_argument("--port", type=int, default=5092)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--model", default="nvidia/parakeet-tdt-0.6b-v3")
    args = ap.parse_args()

    global _MODEL
    from nano_parakeet import from_pretrained  # heavy; only at startup

    print(f"[parakeet] Loading {args.model} on {args.device}…", file=sys.stderr)
    _MODEL = from_pretrained(args.model, device=args.device)
    print("[parakeet] Model loaded.", file=sys.stderr)

    server = HTTPServer(("127.0.0.1", args.port), Handler)
    print(f"[parakeet] Listening on http://127.0.0.1:{args.port}", file=sys.stderr)

    def _shutdown(signum: int, _frame: Any) -> None:
        print(f"\n[parakeet] Signal {signum}; shutting down.", file=sys.stderr)
        server.shutdown()

    signal.signal(signal.SIGTERM, _shutdown)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[parakeet] Interrupted; shutting down.", file=sys.stderr)
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
