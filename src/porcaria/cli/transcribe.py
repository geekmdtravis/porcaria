"""`porcaria transcribe FILE` — transcribe a WAV via the active ASR provider."""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Annotated

import typer

from porcaria.cli._common import print_rpc, try_rpc


def main(
    file: Annotated[Path, typer.Argument(exists=True, readable=True, help="WAV file to transcribe.")],
    format: Annotated[str, typer.Option("--format", help="'text' or 'json'.")] = "text",
) -> None:
    wav = file.read_bytes()
    params = {"wav_b64": base64.b64encode(wav).decode(), "filename": file.name}
    resp = try_rpc("transcribe", params)
    if resp is None:
        typer.secho(
            "daemon not running; transcribe subcommand requires the daemon (start with `porcaria daemon start`)",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(2)
    if format == "json":
        print_rpc(resp)
        return
    if resp.ok:
        typer.echo((resp.result or {}).get("text", ""))
    else:
        err = resp.error or {}
        typer.secho(f"error: {err.get('code')}: {err.get('message')}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
