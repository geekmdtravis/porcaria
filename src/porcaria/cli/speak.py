"""`porcaria speak TEXT` — synthesize speech via the active TTS provider."""
from __future__ import annotations

import base64
import sys
from pathlib import Path
from typing import Annotated

import typer

from porcaria.cli._common import try_rpc


def main(
    text: Annotated[str, typer.Argument(help="Text to speak. Use '-' to read stdin.")],
    voice: Annotated[str | None, typer.Option("--voice")] = None,
    speed: Annotated[float, typer.Option("--speed")] = 1.0,
    out: Annotated[Path | None, typer.Option("--out", help="Write WAV to path; omit to play.")] = None,
) -> None:
    if text == "-":
        text = sys.stdin.read()
    params = {"text": text, "voice": voice, "speed": speed}
    resp = try_rpc("speak", params)
    if resp is None:
        typer.secho(
            "daemon not running; speak subcommand requires the daemon", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(2)
    if not resp.ok:
        err = resp.error or {}
        typer.secho(f"error: {err.get('code')}: {err.get('message')}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    wav = base64.b64decode((resp.result or {}).get("wav_b64", ""))
    if out is not None:
        out.write_bytes(wav)
        typer.echo(str(out))
    else:
        sys.stdout.buffer.write(wav)
