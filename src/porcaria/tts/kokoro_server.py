"""Persistent HTTP server wrapping Kokoro ONNX TTS.

Loaded once at startup. One of possibly many TTS backends — the /speak JSON
contract is deliberately minimal so swapping in a different free model
(Piper, Coqui, etc.) only means adding a new server module that honors the
same request/response shape, or a new TTSProvider client talking to whatever
that model ships with.

Endpoints:
    GET  /health  -> {"status": "ok"}
    POST /speak
        Request (JSON): {"text": str, "voice": str?, "speed": float?, "lang": str?}
        Response:       audio/wav bytes

Run as:
    python -m porcaria.tts.kokoro_server --port 5093 \\
           --model ~/Applications/kokoro-tts/kokoro-v1.0.onnx \\
           --voices ~/Applications/kokoro-tts/voices-v1.0.bin
"""
from __future__ import annotations

import argparse
import io
import json
import os
import signal
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

_MODEL: Any = None
_SAMPLE_RATE: int = 24000  # Kokoro default; overwritten at startup if the lib exposes it.

DEFAULT_VOICE = "af_heart"
DEFAULT_SPEED = 1.0
DEFAULT_LANG = "en-us"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: ARG002
        sys.stderr.write(f"[kokoro] {args[0] if args else ''}\n")

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(200, {"status": "ok"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/speak":
            self._json(404, {"error": "not found"})
            return
        try:
            cl = int(self.headers.get("Content-Length") or 0)
            if cl <= 0:
                self._json(400, {"error": "empty request body"})
                return
            params = json.loads(self.rfile.read(cl))
            text = (params.get("text") or "").strip()
            if not text:
                self._json(400, {"error": "missing or empty 'text'"})
                return
            voice = params.get("voice") or DEFAULT_VOICE
            speed = float(params.get("speed") or DEFAULT_SPEED)
            lang = params.get("lang") or DEFAULT_LANG

            wav_bytes = _synthesize(text, voice=voice, speed=speed, lang=lang)

            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(wav_bytes)))
            self.end_headers()
            self.wfile.write(wav_bytes)
        except Exception as e:  # noqa: BLE001
            self._json(500, {"error": str(e)})

    def _json(self, code: int, obj: dict[str, Any]) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _synthesize(text: str, *, voice: str, speed: float, lang: str) -> bytes:
    import soundfile as sf

    result = _MODEL.create(text, voice=voice, speed=speed, lang=lang)
    # Older kokoro-onnx returns (audio, sr); newer releases return just audio.
    if isinstance(result, tuple) and len(result) == 2:
        audio, sr = result
    else:
        audio, sr = result, _SAMPLE_RATE
    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser(description="Kokoro TTS HTTP server")
    ap.add_argument("--port", type=int, default=5093)
    ap.add_argument(
        "--model",
        default=None,
        help="Path to kokoro-v1.0.onnx (default: ~/Applications/kokoro-tts/kokoro-v1.0.onnx).",
    )
    ap.add_argument(
        "--voices",
        default=None,
        help="Path to voices-v1.0.bin (default: ~/Applications/kokoro-tts/voices-v1.0.bin).",
    )
    args = ap.parse_args()

    default_dir = os.path.expanduser("~/Applications/kokoro-tts")
    model_path = os.path.expanduser(args.model) if args.model else os.path.join(default_dir, "kokoro-v1.0.onnx")
    voices_path = os.path.expanduser(args.voices) if args.voices else os.path.join(default_dir, "voices-v1.0.bin")
    for p, label in ((model_path, "model"), (voices_path, "voices")):
        if not os.path.isfile(p):
            print(f"[kokoro] ERROR: {label} file not found: {p}", file=sys.stderr)
            return 1

    global _MODEL, _SAMPLE_RATE
    from kokoro_onnx import Kokoro  # heavy; only at startup

    try:
        from kokoro_onnx import SAMPLE_RATE as _SR

        _SAMPLE_RATE = int(_SR)
    except ImportError:
        pass  # keep 24000 default

    print(f"[kokoro] Loading model from {model_path}…", file=sys.stderr)
    _MODEL = Kokoro(model_path, voices_path)
    print(f"[kokoro] Model loaded. Sample rate: {_SAMPLE_RATE}", file=sys.stderr)

    server = HTTPServer(("127.0.0.1", args.port), Handler)
    print(f"[kokoro] Listening on http://127.0.0.1:{args.port}", file=sys.stderr)

    def _shutdown(signum: int, _frame: Any) -> None:
        print(f"\n[kokoro] Signal {signum}; shutting down.", file=sys.stderr)
        server.shutdown()

    signal.signal(signal.SIGTERM, _shutdown)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[kokoro] Interrupted; shutting down.", file=sys.stderr)
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
