"""`porcaria task "..."` — free-form voice-style command routed to the task sink."""
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
                "Natural-language command to interpret, e.g. "
                "'add buy milk to personal', 'mark task 42 done', 'show today'. "
                "Pass '-' to read the command text from stdin."
            ),
        ),
    ],
) -> None:
    """Run a text-only voice-command through the task sink (fazerei by default).

    The active LLM translates the free-form request into a concrete task-CLI
    invocation and the result is executed. Equivalent to `porcaria dictate --route task`
    but skips audio capture/ASR — useful for scripting or testing the command layer."""
    if text == "-":
        text = sys.stdin.read()
    resp = try_rpc("task", {"text": text})
    if resp is None:
        typer.secho(
            "daemon not running; task subcommand requires the daemon", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(2)
    print_rpc(resp)
