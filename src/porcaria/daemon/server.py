"""Async UDS + (optional) HTTP listener for the porcaria daemon."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from porcaria import live_state, paths
from porcaria.config import load_config
from porcaria.config.schema import Config
from porcaria.daemon import supervisor
from porcaria.daemon.rpc import Request, Response

log = logging.getLogger("porcaria.daemon")

Handler = Callable[["State", dict[str, Any]], Awaitable[dict[str, Any]]]


class State:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.shutdown_event = asyncio.Event()

    def reload(self) -> None:
        self.cfg = load_config()


# ---------- handlers ----------


async def h_ping(st: State, _params: dict) -> dict:
    return {"pong": True, "pid": os.getpid()}


def _status_dict(st: State) -> dict:
    """Build the full status dict, including server health. Sync — callable from
    worker threads (e.g. the live_state refresher) without event-loop churn."""
    health = supervisor.health_snapshot(st.cfg)
    prof = st.cfg.profile()
    return {
        "active_profile": st.cfg.active_profile,
        "profile": prof.model_dump(),
        "servers": health,
        "pid": os.getpid(),
    }


async def h_status(st: State, _params: dict) -> dict:
    base = await asyncio.to_thread(_status_dict, st)
    base.update(live_state.snapshot_live())
    return base


@contextlib.asynccontextmanager
async def _aphase(name: str):
    """Async wrapper around the sync live_state.phase context manager."""
    cm = live_state.phase(name)
    cm.__enter__()
    try:
        yield
    finally:
        cm.__exit__(None, None, None)


async def h_providers_list(st: State, _params: dict) -> dict:
    prof = st.cfg.profile()
    return {
        "asr": prof.asr,
        "tts": prof.tts,
        "llm": prof.llm,
        "sinks": prof.sinks,
    }


async def h_providers_switch(st: State, params: dict) -> dict:
    kind = params.get("kind")
    name = params.get("name")
    if kind not in {"asr", "tts", "llm"}:
        raise ValueError(f"kind must be asr|tts|llm, got {kind!r}")
    if not name:
        raise ValueError("name required")
    prof = st.cfg.profile()
    setattr(prof, kind, name)
    return {"active_profile": st.cfg.active_profile, "kind": kind, "name": name}


async def h_reload(st: State, _params: dict) -> dict:
    from porcaria.providers import reset_cache

    st.reload()
    reset_cache()
    return {"reloaded": True, "active_profile": st.cfg.active_profile}


async def h_servers_start(st: State, params: dict) -> dict:
    which = params.get("which", "all")
    model = params.get("model", "small")
    if model not in {"small", "large"}:
        raise ValueError("model must be 'small' or 'large'")
    if which == "all":
        return await asyncio.to_thread(supervisor.start_all, st.cfg, model)
    return await asyncio.to_thread(supervisor.start_one, st.cfg, which, model=model)


async def h_servers_stop(st: State, params: dict) -> dict:
    which = params.get("which", "all")
    if which == "all":
        return await asyncio.to_thread(supervisor.stop_all)
    return await asyncio.to_thread(supervisor.stop_one, which)


async def h_servers_toggle(st: State, params: dict) -> dict:
    """If any supervised server is up, stop them all; otherwise start the full stack."""
    model = params.get("model", "small")
    if model not in {"small", "large"}:
        raise ValueError("model must be 'small' or 'large'")
    health = await asyncio.to_thread(supervisor.health_snapshot, st.cfg)
    running = any(v.get("ok") for v in health.values())
    if running:
        result = await asyncio.to_thread(supervisor.stop_all)
        return {"action": "stopped", **result}
    result = await asyncio.to_thread(supervisor.start_all, st.cfg, model)
    return {"action": "started", **result}


# ----- pipeline handlers (Phase 2): transcribe / speak / clean -----


async def h_transcribe(st: State, params: dict) -> dict:
    import base64

    from porcaria.providers import get_asr

    wav_b64 = params.get("wav_b64") or ""
    if not wav_b64:
        raise ValueError("wav_b64 required")
    wav = base64.b64decode(wav_b64)
    prof = st.cfg.profile()
    provider = get_asr(st.cfg, prof.asr)
    async with _aphase("transcribing"):
        text = await asyncio.to_thread(provider.transcribe, wav)
    return {"text": text, "provider": prof.asr}


async def h_speak(st: State, params: dict) -> dict:
    import base64

    from porcaria.providers import get_tts

    text = params.get("text") or ""
    if not text:
        raise ValueError("text required")
    voice = params.get("voice")
    speed = float(params.get("speed") or 1.0)
    prof = st.cfg.profile()
    provider = get_tts(st.cfg, prof.tts)
    async with _aphase("speaking"):
        wav = await asyncio.to_thread(provider.synth, text, voice=voice, speed=speed)
    return {"wav_b64": base64.b64encode(wav).decode(), "provider": prof.tts}


async def h_clean(st: State, params: dict) -> dict:
    from porcaria.providers import get_llm

    text = params.get("text") or ""
    style = params.get("style", "dictation")
    if not text:
        raise ValueError("text required")
    prof = st.cfg.profile()
    provider = get_llm(st.cfg, prof.llm)
    system = _CLEAN_PROMPTS.get(style, _CLEAN_PROMPTS["dictation"])
    async with _aphase("cleaning"):
        cleaned = await asyncio.to_thread(provider.chat, system, text, temperature=0.0)
    return {"text": cleaned, "provider": prof.llm, "style": style}


async def h_dictate_toggle(st: State, params: dict) -> dict:
    from porcaria.pipeline.dictate import toggle

    clean = bool(params.get("clean", False))
    route = params.get("route") or "default"
    sinks = params.get("sinks")  # None | str | list[str] — pipeline parses
    profile = params.get("profile")
    return await asyncio.to_thread(
        toggle, st.cfg, clean=clean, route=route, sinks=sinks, profile_name=profile
    )


async def h_task(st: State, params: dict) -> dict:
    """Run a free-form voice-style command through the fazerei sink without recording."""
    from datetime import datetime

    from porcaria.providers import get_llm
    from porcaria.sinks.base import DictationContext
    from porcaria.sinks.fazerei import FazereiSink

    text = (params.get("text") or "").strip()
    if not text:
        raise ValueError("text required")

    prof = st.cfg.profile()
    sink = FazereiSink(st.cfg.sinks.fazerei)
    ctx = DictationContext(now=datetime.now(), profile=prof.llm, extras={})
    system = sink.system_prompt(ctx) or ""

    def _run() -> dict:
        llm = get_llm(st.cfg, prof.llm)
        llm_output = llm.chat(system, text, temperature=0.0)
        result = sink.handle(text, llm_output)
        return {
            "ok": result.ok,
            "message": result.message,
            "llm_output": llm_output,
            "query_output": result.artifact,
        }

    async with _aphase("task"):
        return await asyncio.to_thread(_run)


_CLEAN_PROMPTS = {
    "dictation": (
        "You clean up voice-dictated text. Fix grammar, punctuation, capitalization, "
        "and obvious transcription errors while preserving the speaker's voice. "
        "If the speaker asks you to translate (e.g. 'translate this to Spanish'), "
        "honor that instruction in your output. Return only the cleaned text — "
        "no preamble, no commentary."
    ),
    "summary": (
        "Summarize the following dictated text in 1-3 concise bullets. "
        "If the speaker asks you to translate, honor that. Return only the summary."
    ),
}


async def h_shutdown(st: State, _params: dict) -> dict:
    st.shutdown_event.set()
    return {"shutting_down": True}


HANDLERS: dict[str, Handler] = {
    "ping": h_ping,
    "status": h_status,
    "providers.list": h_providers_list,
    "providers.switch": h_providers_switch,
    "reload": h_reload,
    "servers.start": h_servers_start,
    "servers.stop": h_servers_stop,
    "servers.toggle": h_servers_toggle,
    "shutdown": h_shutdown,
    "transcribe": h_transcribe,
    "speak": h_speak,
    "clean": h_clean,
    "dictate.toggle": h_dictate_toggle,
    "task": h_task,
}


# ---------- UDS listener ----------


async def _handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, st: State) -> None:
    peer = writer.get_extra_info("peername")
    try:
        line = await reader.readline()
        if not line:
            return
        try:
            req = Request.from_json(line.decode().rstrip("\n"))
        except (json.JSONDecodeError, KeyError) as e:
            resp = Response.failure("0", "bad_request", f"parse error: {e}")
            writer.write((resp.to_json() + "\n").encode())
            await writer.drain()
            return

        handler = HANDLERS.get(req.method)
        if handler is None:
            resp = Response.failure(req.id, "unknown_method", f"unknown method '{req.method}'")
        else:
            try:
                result = await handler(st, req.params)
                resp = Response.success(req.id, result)
            except NotImplementedError as e:
                resp = Response.failure(req.id, "not_implemented", str(e))
            except Exception as e:
                log.exception("handler %s failed", req.method)
                resp = Response.failure(req.id, type(e).__name__, str(e))
        writer.write((resp.to_json() + "\n").encode())
        await writer.drain()
    finally:
        with contextlib.suppress(Exception):
            writer.close()
            await writer.wait_closed()
        log.debug("client closed: %s", peer)


# Large enough to hold ~20 min of base64-encoded 16k mono PCM16 audio on one line.
_STREAM_LIMIT = 64 * 1024 * 1024


async def _run_uds(st: State, sock_path: Path) -> asyncio.base_events.Server:
    if sock_path.exists():
        sock_path.unlink()
    sock_path.parent.mkdir(parents=True, exist_ok=True)

    async def handler(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        await _handle_client(r, w, st)

    server = await asyncio.start_unix_server(handler, path=str(sock_path), limit=_STREAM_LIMIT)
    os.chmod(sock_path, 0o600)
    log.info("listening on UDS %s", sock_path)
    return server


# ---------- optional HTTP listener ----------


async def _run_http(st: State, bind: str) -> asyncio.base_events.Server:
    host, _, port_s = bind.rpartition(":")
    port = int(port_s)

    async def http_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = await reader.readline()
            if not request_line:
                return
            parts = request_line.decode(errors="replace").split()
            if len(parts) < 3:
                _http_reply(writer, 400, {"error": "bad request line"})
                await writer.drain()
                return
            method, path, _ = parts
            headers: dict[str, str] = {}
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
                k, _, v = line.decode(errors="replace").partition(":")
                headers[k.strip().lower()] = v.strip()
            body = b""
            cl = int(headers.get("content-length", "0") or "0")
            if cl:
                body = await reader.readexactly(cl)

            rpc_method = path.lstrip("/").replace("/", ".") or "status"
            try:
                params = json.loads(body.decode()) if body else {}
            except json.JSONDecodeError:
                _http_reply(writer, 400, {"error": "invalid JSON body"})
                await writer.drain()
                return

            handler = HANDLERS.get(rpc_method)
            if handler is None:
                _http_reply(writer, 404, {"error": f"unknown method '{rpc_method}'"})
            else:
                try:
                    result = await handler(st, params)
                    _http_reply(writer, 200, result)
                except NotImplementedError as e:
                    _http_reply(writer, 501, {"error": str(e)})
                except Exception as e:
                    log.exception("http handler %s failed", rpc_method)
                    _http_reply(writer, 500, {"error": type(e).__name__, "message": str(e)})
            await writer.drain()
        finally:
            with contextlib.suppress(Exception):
                writer.close()
                await writer.wait_closed()

    server = await asyncio.start_server(http_handler, host=host, port=port, limit=_STREAM_LIMIT)
    log.info("listening on HTTP %s", bind)
    return server


def _http_reply(writer: asyncio.StreamWriter, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode()
    headers = (
        f"HTTP/1.1 {status} OK\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Connection: close\r\n\r\n"
    ).encode()
    writer.write(headers + body)


# ---------- entrypoint ----------


async def _main() -> int:
    logging.basicConfig(
        level=os.environ.get("PORCARIA_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    paths.ensure_dirs()
    cfg = load_config()
    st = State(cfg)

    sock_path = Path(cfg.daemon.ipc_socket) if cfg.daemon.ipc_socket else paths.ipc_socket()
    uds = await _run_uds(st, sock_path)

    http_server: asyncio.base_events.Server | None = None
    if cfg.daemon.http_enabled:
        http_server = await _run_http(st, cfg.daemon.http_bind)

    live_state.init(build_status=lambda: _status_dict(st))

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, st.shutdown_event.set)

    log.info("porcaria daemon up (pid=%d)", os.getpid())
    try:
        await st.shutdown_event.wait()
    finally:
        live_state.teardown()
        uds.close()
        await uds.wait_closed()
        if http_server is not None:
            http_server.close()
            await http_server.wait_closed()
        with contextlib.suppress(FileNotFoundError):
            sock_path.unlink()
        log.info("porcaria daemon stopped")
    return 0


def main() -> int:
    try:
        return asyncio.run(_main())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
