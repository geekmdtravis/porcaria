"""`porcaria clean` — run text through the active LLM's cleanup pass."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from porcaria.cli._common import try_rpc


def main(
    in_: Annotated[
        Path | None,
        typer.Option(
            "--in",
            help=(
                "Path to the text file to clean. Pass '-' (or omit) to read from stdin, "
                "which makes this easy to pipe: `cat raw.txt | porcaria clean`."
            ),
        ),
    ] = None,
    style: Annotated[
        str,
        typer.Option(
            "--style",
            help=(
                "Cleanup style. 'dictation' adds punctuation/capitalization while "
                "preserving wording for paste-into-editor workflows. 'summary' "
                "condenses the text into a speech-friendly summary (used internally "
                "to summarize query results before TTS)."
            ),
        ),
    ] = "dictation",
) -> None:
    """Pass text through the active LLM to clean it up.

    Reads text from stdin (default) or a file via --in, and prints the cleaned
    output to stdout. Requires the daemon to be running."""
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
