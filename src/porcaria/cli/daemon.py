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

app = typer.Typer(
    help=(
        "Lifecycle commands for the long-lived porcaria daemon. "
        "The daemon holds the UDS+HTTP IPC socket, keeps provider clients warm, "
        "and supervises local model servers. Most other subcommands (`dictate`, "
        "`transcribe`, `speak`, `clean`, `task`) require it to be running."
    ),
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)

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


_VALID_NOTIFY_LEVELS = ("debug", "info", "warning", "error", "critical", "none")


@app.command("start")
def start(
    foreground: bool = typer.Option(
        False,
        "--foreground",
        "-f",
        help=(
            "Run the daemon attached to the current terminal (logs go to stdout) "
            "instead of double-forking into the background. Useful for debugging."
        ),
    ),
    notify_level: str = typer.Option(
        "warning",
        "--notify-level",
        help=(
            "Minimum level to surface via desktop notifications "
            "(debug|info|warning|error|critical|none). Default: warning, so "
            "task completions and errors pop up while in-progress chatter stays "
            "silent. Use 'error' for failures-only, 'info' for full chatter, "
            "or 'none' to silence everything. Pair with a waybar module "
            "reading $XDG_RUNTIME_DIR/porcaria/status.json for "
            "status-at-a-glance."
        ),
    ),
) -> None:
    """Start the porcaria daemon, double-forked into the background by default.

    Writes its PID to $XDG_RUNTIME_DIR/porcaria/porcaria.pid and exposes a Unix
    socket at $XDG_RUNTIME_DIR/porcaria/porcaria.sock. Logs go to daemon.log
    next to the pid file."""
    level = notify_level.strip().lower()
    if level not in _VALID_NOTIFY_LEVELS:
        typer.secho(
            f"invalid --notify-level {notify_level!r}; valid: {list(_VALID_NOTIFY_LEVELS)}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(2)

    paths.ensure_dirs()
    existing = _read_pid()
    if existing and _alive(existing):
        typer.secho(f"already running (pid {existing})", fg=typer.colors.YELLOW)
        raise typer.Exit(0)

    cmd = [sys.executable, "-m", "porcaria.daemon.server"]
    env = os.environ.copy()
    env["PORCARIA_NOTIFY_LEVEL"] = level
    # Previous release shipped a boolean PORCARIA_NOTIFY; strip any inherited
    # value so it can't confuse older notify.py builds.
    env.pop("PORCARIA_NOTIFY", None)

    if foreground:
        os.execvpe(cmd[0], cmd, env)

    log_path = paths.runtime_dir() / "daemon.log"
    proc = subprocess.Popen(
        cmd,
        env=env,
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
    """Stop the porcaria daemon, shutting down supervised model servers too.

    Prefers a graceful shutdown RPC; falls back to SIGTERM on the pid file if
    the socket is unresponsive."""
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
    """Report daemon liveness as JSON.

    Shows the pid file path, whether the pid is alive, the socket path, and whether
    a ping RPC succeeds. Useful for health-check scripts and troubleshooting."""
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
    """Reload the config file and flush cached provider clients without restarting.

    Call this after editing ~/.config/porcaria/config.toml (or `porcaria config edit`)
    so the daemon picks up the new profile/provider settings."""
    resp = try_rpc("reload")
    if resp is None:
        typer.secho("daemon not running", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)
    from porcaria.cli._common import print_rpc

    print_rpc(resp)
