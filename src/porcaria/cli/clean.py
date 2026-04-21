"""`porcaria clean` — run text through the active LLM's cleanup pass."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from porcaria.cli._common import try_rpc


def main(
    in_: Annotated[Path | None, typer.Option("--in", help="Read text from file; '-' for stdin.")] = None,
    style: Annotated[str, typer.Option("--style", help="'dictation' or 'summary'.")] = "dictation",
) -> None:
    if in_ is None or str(in_) == "-":
        text = sys.stdin.read()
    else:
        text = in_.read_text()
    resp = try_rpc("clean", {"text": text, "style": style})
    if resp is None:
        typer.secho(
            "daemon not running; clean subcommand requires the daemon", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(2)
    if not resp.ok:
        err = resp.error or {}
        typer.secho(f"error: {err.get('code')}: {err.get('message')}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    typer.echo((resp.result or {}).get("text", ""))
