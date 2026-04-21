"""`porcaria download {tts}` — fetch model weights and other downloadable assets.

Single entry point for all porcaria asset downloads. Currently supports the
Kokoro TTS ONNX model + voices file; other inference backends (llama.cpp,
nano-parakeet) fetch their own weights via their host libraries on first use.
"""
from __future__ import annotations

import sys
from typing import Annotated

import typer

from porcaria.config import load_config
from porcaria.tts.kokoro_download import (
    KokoroAssetError,
    ensure_kokoro_assets,
    ensure_kokoro_model,
    ensure_kokoro_voices,
)

app = typer.Typer(
    help=(
        "Pre-fetch or re-download porcaria's model assets. The supervisor "
        "auto-downloads on first run, so you only need these commands to "
        "pre-fetch before going offline, recover from a corrupted file, or "
        "re-pull after rotating the hash pin."
    ),
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@app.command("tts")
def tts(
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Re-download even if the files already exist and match the configured hash.",
        ),
    ] = False,
    model_only: Annotated[
        bool,
        typer.Option(
            "--model-only",
            help="Only fetch the ONNX model; skip the voices file.",
        ),
    ] = False,
    voices_only: Annotated[
        bool,
        typer.Option(
            "--voices-only",
            help="Only fetch the voices file; skip the ONNX model.",
        ),
    ] = False,
) -> None:
    """Download the Kokoro TTS ONNX model and voices file."""
    if model_only and voices_only:
        typer.secho(
            "--model-only and --voices-only are mutually exclusive.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)

    cfg = load_config().tts.kokoro
    try:
        if model_only:
            path = ensure_kokoro_model(cfg, force=force)
            typer.secho(f"model:  {path}", fg=typer.colors.GREEN)
        elif voices_only:
            path = ensure_kokoro_voices(cfg, force=force)
            typer.secho(f"voices: {path}", fg=typer.colors.GREEN)
        else:
            model_path, voices_path = ensure_kokoro_assets(cfg, force=force)
            typer.secho(f"model:  {model_path}", fg=typer.colors.GREEN)
            typer.secho(f"voices: {voices_path}", fg=typer.colors.GREEN)
    except KokoroAssetError as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e
    sys.stdout.flush()
