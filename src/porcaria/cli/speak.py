"""`porcaria speak TEXT` — synthesize speech via the active TTS provider."""
from __future__ import annotations

import base64
import sys
from pathlib import Path
from typing import Annotated

import typer

from porcaria.audio.player import play_bytes
from porcaria.cli._common import try_rpc


def main(
    text: Annotated[
        str,
        typer.Argument(
            help=(
                "Text to synthesize. Pass '-' to read the text from stdin "
                "(useful for piping: `echo hello | porcaria speak -`)."
            ),
        ),
    ],
    voice: Annotated[
        str | None,
        typer.Option(
            "--voice",
            help=(
                "Voice identifier to use, overriding the profile default. "
                "Valid names depend on the active TTS provider (Kokoro ONNX voices "
                "like 'af_bella', OpenAI voices like 'nova', ElevenLabs voice IDs)."
            ),
        ),
    ] = None,
    speed: Annotated[
        float,
        typer.Option(
            "--speed",
            help="Playback speed multiplier. 1.0 = natural pace; <1 slower, >1 faster.",
        ),
    ] = 1.0,
    out: Annotated[
        Path | None,
        typer.Option(
            "--out",
            help=(
                "Write the synthesized audio to this WAV file instead of playing it."
            ),
        ),
    ] = None,
    stdout: Annotated[
        bool,
        typer.Option(
            "--stdout",
            help=(
                "Write raw WAV bytes to stdout instead of playing. Useful for piping "
                "into an alternative player: `porcaria speak foo --stdout | pw-play -`."
            ),
        ),
    ] = False,
) -> None:
    """Synthesize speech from text via the active TTS provider.

    Default behavior: play through speakers when running in a terminal; write
    WAV bytes to stdout when stdout is a pipe or redirection (so pipelines like
    `porcaria speak foo | aplay` still work). Pass --out PATH to save to a file,
    or --stdout to force pipe mode even on a TTY.

    Requires the daemon to be running (`porcaria daemon start`)."""
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
        return

    if stdout or not sys.stdout.isatty():
        sys.stdout.buffer.write(wav)
        return

    if not play_bytes(wav):
        typer.secho(
            "no audio player found (install pw-play, ffplay, or paplay — "
            "or use --out PATH / --stdout)",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)
