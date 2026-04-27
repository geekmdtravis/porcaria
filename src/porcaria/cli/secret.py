"""`porcaria secret "..."` — select an allowed pass entry and copy it."""
from __future__ import annotations

import sys
from typing import Annotated

import typer

from porcaria.cli._common import print_rpc, try_rpc


def main(
    text: Annotated[
        str,
        typer.Argument(
            help=(
                "Natural-language secret request, e.g. "
                "'copy my Emory tnesbi2 password'. Pass '-' to read from stdin."
            ),
        ),
    ],
) -> None:
    """Run a text-only secret request through the pass selection route."""
    if text == "-":
        text = sys.stdin.read()
    resp = try_rpc("secret", {"text": text})
    if resp is None:
        typer.secho(
            "daemon not running; secret subcommand requires the daemon",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(2)
    print_rpc(resp)
