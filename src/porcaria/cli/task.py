"""`porcaria task "..."` — free-form voice-style command routed to the task sink."""
from __future__ import annotations

import sys
from typing import Annotated

import typer

from porcaria.cli._common import print_rpc, try_rpc


def main(
    text: Annotated[str, typer.Argument(help="Command text. Use '-' to read stdin.")],
) -> None:
    if text == "-":
        text = sys.stdin.read()
    resp = try_rpc("task", {"text": text})
    if resp is None:
        typer.secho(
            "daemon not running; task subcommand requires the daemon", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(2)
    print_rpc(resp)
