"""`porcaria status` — snapshot of providers and local server health."""
from __future__ import annotations

import json

import typer

from porcaria.cli._common import try_rpc
from porcaria.config import load_config
from porcaria.daemon import supervisor


def main() -> None:
    """Print a JSON snapshot of the current pipeline state.

    Includes the active profile, each configured provider (ASR/LLM/TTS), and the
    health of the local model servers (PID, listening port, reachability).
    If the daemon isn't running, the health check runs locally instead."""
    resp = try_rpc("status")
    if resp is not None and resp.ok:
        typer.echo(json.dumps(resp.result, indent=2))
        return

    # Daemon not running — run the checks locally.
    cfg = load_config()
    prof = cfg.profile()
    health = supervisor.health_snapshot(cfg)
    payload = {
        "daemon": "not running",
        "active_profile": cfg.active_profile,
        "profile": prof.model_dump(),
        "servers": health,
    }
    typer.echo(json.dumps(payload, indent=2))
