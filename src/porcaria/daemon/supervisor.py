"""Native supervisor for local model servers.

Spawns llama-server (binary) + parakeet + kokoro (both `python -m` invocations)
as long-lived subprocesses. Each has:

  - a PID file under $XDG_RUNTIME_DIR/porcaria/{name}.pid
  - a log file at  $XDG_RUNTIME_DIR/porcaria/{name}.log
  - a /health endpoint the supervisor polls to confirm startup

Children are started with `start_new_session=True` so they survive the daemon
exiting (mirrors the previous bash behavior). Stop them explicitly via
`porcaria serve all --stop` or the `servers.stop` RPC.
"""
from __future__ import annotations

import logging
import multiprocessing
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from porcaria import notify, paths
from porcaria.config.schema import Config

log = logging.getLogger(__name__)


@dataclass
class ServerSpec:
    name: str                     # "llama" | "parakeet" | "kokoro"
    argv: list[str]
    health_url: str
    health_timeout_s: float       # how long to wait for /health to come up
    extra_state: dict[str, str]   # e.g. {"model": "small"}


# --------------------------- file helpers ---------------------------


def _pid_file(name: str) -> Path:
    return paths.runtime_dir() / f"{name}.pid"


def _log_file(name: str) -> Path:
    return paths.runtime_dir() / f"{name}.log"


def _state_file(name: str, key: str) -> Path:
    return paths.runtime_dir() / f"{name}.{key}"


def _read_pid(name: str) -> int | None:
    pf = _pid_file(name)
    if not pf.exists():
        return None
    try:
        return int(pf.read_text().strip())
    except (ValueError, OSError):
        return None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _reaped(pid: int) -> bool:
    """True if the process is gone (exited and reaped OR never existed).
    os.kill(pid, 0) reports zombies as alive, so also try waitpid(WNOHANG)
    to either reap our own child or confirm it's not ours anymore."""
    try:
        reaped, _status = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        # Not our child or already reaped by someone else.
        return not _alive(pid)
    if reaped != 0:
        return True
    return not _alive(pid)


def _kill(pid: int, *, timeout_s: float = 10.0) -> bool:
    """SIGTERM, wait, then SIGKILL. Returns True if the process is gone."""
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _reaped(pid):
            return True
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    end = time.monotonic() + 0.5
    while time.monotonic() < end:
        if _reaped(pid):
            return True
        time.sleep(0.05)
    return False


# --------------------------- spec builders ---------------------------


def _llama_spec(cfg: Config, model: str) -> ServerSpec:
    s = cfg.servers.llamacpp
    l = cfg.llm.llamacpp
    ctx = l.ctx_small if model == "small" else l.ctx_large
    hf = l.model_small if model == "small" else l.model_large
    argv: list[str] = [
        s.binary,
        "-hf", hf,
        "--port", str(s.port),
        "--ctx-size", str(ctx),
        "--jinja",
        "--fit-target", str(s.fit_target),
        "--cache-type-k", s.kv_cache_type,
        "--cache-type-v", s.kv_cache_type,
        "-tb", str(multiprocessing.cpu_count()),
        "-ub", str(s.ubatch_size),
        "-b", str(s.batch_size),
    ]
    if s.flash_attn:
        argv.extend(["-fa", "on"])
    return ServerSpec(
        name="llama",
        argv=argv,
        health_url=f"{l.url}/health",
        health_timeout_s=240.0,
        extra_state={"model": model, "hf": hf},
    )


def _resolve_python(configured: str, uv_tool_names: tuple[str, ...]) -> str:
    """Pick the python that has the heavy ML deps installed.

    Order: explicit config > first matching uv-tool venv > daemon's own sys.executable.
    The uv-tool venv path convention is $HOME/.local/share/uv/tools/<name>/bin/python.
    """
    if configured:
        return configured
    home = Path(os.path.expanduser("~"))
    for name in uv_tool_names:
        candidate = home / ".local/share/uv/tools" / name / "bin" / "python"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return sys.executable


def _server_script(module: str) -> str:
    """Absolute path to a porcaria server module, so it can run under any
    interpreter that has the heavy ML deps but doesn't need porcaria installed."""
    import importlib.util
    spec = importlib.util.find_spec(module)
    if spec is None or spec.origin is None:
        raise RuntimeError(f"cannot locate server module: {module}")
    return spec.origin


def _parakeet_spec(cfg: Config) -> ServerSpec:
    s = cfg.servers.parakeet
    python = _resolve_python(s.python_executable, ("nano-parakeet",))
    argv = [
        python, "-u", _server_script("porcaria.asr.parakeet_server"),
        "--port", str(s.port),
        "--device", s.device,
        "--model", s.model,
    ]
    return ServerSpec(
        name="parakeet",
        argv=argv,
        health_url=f"{cfg.asr.parakeet.url}/health",
        health_timeout_s=120.0,
        extra_state={"model": s.model, "device": s.device, "python": python},
    )


def _kokoro_spec(cfg: Config) -> ServerSpec:
    s = cfg.servers.kokoro
    k = cfg.tts.kokoro
    python = _resolve_python(s.python_executable, ("kokoro-tts",))
    argv = [
        python, "-u", _server_script("porcaria.tts.kokoro_server"),
        "--port", str(s.port),
        "--model", str(paths.expand(k.model_path)),
        "--voices", str(paths.expand(k.voices_path)),
    ]
    return ServerSpec(
        name="kokoro",
        argv=argv,
        health_url=f"{k.url}/health",
        health_timeout_s=30.0,
        extra_state={"python": python},
    )


# --------------------------- spawn / stop ---------------------------


def _spawn(spec: ServerSpec) -> dict:
    paths.ensure_dirs()
    existing = _read_pid(spec.name)
    if existing and _alive(existing):
        return {"status": "already_running", "pid": existing}

    log_path = _log_file(spec.name)
    fh = log_path.open("ab", buffering=0)
    fh.write(f"\n--- porcaria supervisor starting {spec.name} at {int(time.time())} ---\n".encode())
    t_start = time.monotonic()
    log.info("supervisor: spawning %s (health timeout %.0fs)", spec.name, spec.health_timeout_s)
    notify.info("porcaria", f"starting {spec.name}…")
    try:
        proc = subprocess.Popen(  # noqa: S603
            spec.argv,
            stdout=fh,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError as e:
        fh.close()
        log.warning("supervisor: %s executable not found: %s", spec.name, e)
        notify.warn("porcaria", f"{spec.name} failed: executable not found")
        return {"status": "error", "error": f"executable not found: {e}"}

    _pid_file(spec.name).write_text(str(proc.pid))
    for key, val in spec.extra_state.items():
        _state_file(spec.name, key).write_text(val)

    ok, reason = _wait_for_health(spec.health_url, spec.health_timeout_s, proc=proc)
    elapsed = time.monotonic() - t_start
    if not ok:
        # Startup failed. Kill the child (no-op if already dead) and clean up.
        _kill(proc.pid)
        _pid_file(spec.name).unlink(missing_ok=True)
        tail = _tail(log_path, 40)
        log.warning("supervisor: %s %s after %.1fs", spec.name, reason, elapsed)
        notify.warn("porcaria", f"{spec.name} failed to start ({reason})")
        return {"status": "error", "error": reason, "elapsed_s": round(elapsed, 1), "log_tail": tail}
    log.info("supervisor: %s ready in %.1fs", spec.name, elapsed)
    notify.info("porcaria", f"{spec.name} ready ({elapsed:.0f}s)")
    return {"status": "started", "pid": proc.pid, "elapsed_s": round(elapsed, 1), **spec.extra_state}


def _wait_for_health(
    url: str,
    timeout_s: float,
    *,
    proc: subprocess.Popen[bytes] | None = None,
    interval_s: float = 0.5,
) -> tuple[bool, str]:
    """Poll `url` until 200 OK or the deadline lapses. If `proc` is given and
    it exits before /health comes up, fail fast with a meaningful reason."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            return False, f"process exited early (rc={proc.returncode})"
        try:
            r = httpx.get(url, timeout=2.0)
            if r.status_code == 200:
                return True, ""
        except httpx.HTTPError:
            pass
        time.sleep(interval_s)
    return False, f"health check timed out after {timeout_s:.0f}s"


def _tail(path: Path, lines: int) -> str:
    if not path.exists():
        return ""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def _stop_one(name: str) -> dict:
    pid = _read_pid(name)
    if pid is None:
        return {"status": "not_running"}
    if not _alive(pid):
        _pid_file(name).unlink(missing_ok=True)
        return {"status": "not_running"}
    log.info("supervisor: stopping %s (pid %d)", name, pid)
    ok = _kill(pid)
    _pid_file(name).unlink(missing_ok=True)
    if ok:
        notify.info("porcaria", f"{name} stopped")
    else:
        notify.warn("porcaria", f"{name} kill failed (pid {pid})")
    return {"status": "stopped" if ok else "kill_failed", "pid": pid}


# --------------------------- public API ---------------------------


def start_all(cfg: Config, model: str = "small") -> dict:
    """Start llama, parakeet, kokoro. If llama is already running with a
    different model, it is replaced; the others are left alone if healthy."""
    results: dict[str, dict] = {}
    results["kokoro"] = _start_if_needed(_kokoro_spec(cfg))
    results["parakeet"] = _start_if_needed(_parakeet_spec(cfg))
    results["llama"] = _start_llama(cfg, model)
    return {"model": model, "servers": results}


def _start_if_needed(spec: ServerSpec) -> dict:
    pid = _read_pid(spec.name)
    if pid and _alive(pid):
        try:
            r = httpx.get(spec.health_url, timeout=1.0)
            if r.status_code == 200:
                return {"status": "already_running", "pid": pid}
        except httpx.HTTPError:
            pass
    # No tracked PID but port may already be owned by a legacy-started server.
    try:
        r = httpx.get(spec.health_url, timeout=1.0)
        if r.status_code == 200:
            return {"status": "running_externally", "note": "found existing service on port; not spawning"}
    except httpx.HTTPError:
        pass
    return _spawn(spec)


def _start_llama(cfg: Config, model: str) -> dict:
    spec = _llama_spec(cfg, model)
    pid = _read_pid("llama")
    if pid and _alive(pid):
        current = _state_file("llama", "model")
        current_model = current.read_text().strip() if current.exists() else ""
        if current_model == model:
            return {"status": "already_running", "pid": pid, "model": model}
        # Different model — replace it.
        _kill(pid)
        _pid_file("llama").unlink(missing_ok=True)
    return _spawn(spec)


def start_one(cfg: Config, which: str, *, model: str = "small") -> dict:
    match which:
        case "asr":
            return _start_if_needed(_parakeet_spec(cfg))
        case "tts":
            return _start_if_needed(_kokoro_spec(cfg))
        case "llm":
            return _start_llama(cfg, model)
        case _:
            raise ValueError(f"which must be asr|tts|llm, got {which!r}")


def stop_all() -> dict:
    return {
        "llama": _stop_one("llama"),
        "parakeet": _stop_one("parakeet"),
        "kokoro": _stop_one("kokoro"),
    }


def stop_one(which: str) -> dict:
    match which:
        case "asr":
            return {"parakeet": _stop_one("parakeet")}
        case "tts":
            return {"kokoro": _stop_one("kokoro")}
        case "llm":
            return {"llama": _stop_one("llama")}
        case _:
            raise ValueError(f"which must be asr|tts|llm, got {which!r}")


def health_snapshot(cfg: Config) -> dict:
    targets = {
        "llamacpp": f"{cfg.llm.llamacpp.url}/health",
        "parakeet": f"{cfg.asr.parakeet.url}/health",
        "kokoro": f"{cfg.tts.kokoro.url}/health",
    }
    out: dict[str, dict] = {}
    for name, url in targets.items():
        try:
            r = httpx.get(url, timeout=2.0)
            out[name] = {"ok": r.status_code == 200, "status": r.status_code}
        except httpx.HTTPError as e:
            out[name] = {"ok": False, "error": type(e).__name__}
    return out
