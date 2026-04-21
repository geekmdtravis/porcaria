"""Shared CLI helpers for daemon RPC dispatch."""
from __future__ import annotations

import json
from typing import Any

import typer

from porcaria.daemon import Client, DaemonNotRunning, Response


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
