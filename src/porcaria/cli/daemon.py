"""`porcaria daemon {start,stop,status,reload}` — lifecycle for the long-lived daemon."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import typer

from porcaria import paths
from porcaria.cli._common import try_rpc
from porcaria.daemon import Client

app = typer.Typer(help="Manage the porcaria daemon.", no_args_is_help=True)

PID_FILE = "porcaria.pid"


def _pid_file() -> Path:
    return paths.runtime_dir() / PID_FILE


def _read_pid() -> int | None:
    pf = _pid_file()
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


@app.command("start")
def start(
    foreground: bool = typer.Option(False, "--foreground", "-f", help="Run in foreground."),
) -> None:
    """Start the porcaria daemon."""
    paths.ensure_dirs()
    existing = _read_pid()
    if existing and _alive(existing):
        typer.secho(f"already running (pid {existing})", fg=typer.colors.YELLOW)
        raise typer.Exit(0)

    cmd = [sys.executable, "-m", "porcaria.daemon.server"]
    if foreground:
        os.execvp(cmd[0], cmd)

    log_path = paths.runtime_dir() / "daemon.log"
    proc = subprocess.Popen(
        cmd,
        stdout=open(log_path, "ab"),
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    _pid_file().write_text(str(proc.pid))
    # Wait briefly for the socket to appear.
    sock = paths.ipc_socket()
    for _ in range(20):
        if sock.exists():
            break
        time.sleep(0.1)
    typer.echo(f"started (pid {proc.pid}); log: {log_path}")


@app.command("stop")
def stop() -> None:
    """Stop the porcaria daemon."""
    resp = try_rpc("shutdown")
    if resp is not None and resp.ok:
        typer.echo("shutting down")
    else:
        pid = _read_pid()
        if pid is None or not _alive(pid):
            typer.secho("not running", fg=typer.colors.YELLOW)
            raise typer.Exit(0)
        os.kill(pid, signal.SIGTERM)
        typer.echo(f"sent SIGTERM to {pid}")
    # Clean up pid file once the process exits.
    for _ in range(30):
        pid = _read_pid()
        if pid is None or not _alive(pid):
            pf = _pid_file()
            if pf.exists():
                pf.unlink()
            return
        time.sleep(0.1)


@app.command("status")
def status() -> None:
    """Report daemon liveness."""
    client = Client()
    pid = _read_pid()
    payload: dict = {
        "pid_file": str(_pid_file()),
        "pid": pid,
        "pid_alive": _alive(pid) if pid else False,
        "socket": str(client.socket_path),
        "socket_exists": client.socket_path.exists(),
        "ipc_ok": client.is_running(),
    }
    typer.echo(json.dumps(payload, indent=2))


@app.command("reload")
def reload_() -> None:
    """Reload config without restarting."""
    resp = try_rpc("reload")
    if resp is None:
        typer.secho("daemon not running", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)
    from porcaria.cli._common import print_rpc

    print_rpc(resp)
