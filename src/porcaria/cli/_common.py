"""Shared CLI helpers: daemon dispatch + strangler fallback."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import typer

from porcaria.daemon import Client, DaemonNotRunning, Response
from porcaria.shellout import run

LEGACY_DICTATE = Path(os.path.expanduser("~/.config/hypr/scripts/toggle_dictation.sh"))
LEGACY_SERVERS = Path(os.path.expanduser("~/.config/hypr/scripts/toggle_ai_servers.sh"))


def try_rpc(method: str, params: dict[str, Any] | None = None) -> Response | None:
    """Send an RPC to the daemon if it's running; otherwise return None."""
    client = Client()
    if not client.is_running():
        return None
    try:
        return client.call(method, params or {})
    except DaemonNotRunning:
        return None


def print_rpc(resp: Response) -> None:
    if resp.ok:
        typer.echo(json.dumps(resp.result, indent=2))
    else:
        err = resp.error or {}
        typer.secho(f"error: {err.get('code')}: {err.get('message')}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


def legacy_dictate(args: list[str]) -> int:
    if not LEGACY_DICTATE.is_file():
        typer.secho(
            f"native pipeline not implemented and legacy script not found at {LEGACY_DICTATE}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(2)
    res = run([str(LEGACY_DICTATE), *args], timeout=None)
    if res.stdout:
        typer.echo(res.stdout, nl=False)
    if res.stderr:
        typer.echo(res.stderr, nl=False, err=True)
    return res.returncode


def legacy_servers(args: list[str]) -> int:
    if not LEGACY_SERVERS.is_file():
        typer.secho(
            f"legacy servers script not found at {LEGACY_SERVERS}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(2)
    res = run([str(LEGACY_SERVERS), *args], timeout=None)
    if res.stdout:
        typer.echo(res.stdout, nl=False)
    if res.stderr:
        typer.echo(res.stderr, nl=False, err=True)
    return res.returncode
