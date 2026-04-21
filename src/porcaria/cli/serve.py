"""`porcaria serve {all,asr,tts,llm}` — start/stop local model servers."""
from __future__ import annotations

from typing import Annotated

import typer

from porcaria.cli._common import legacy_servers, try_rpc

app = typer.Typer(
    help=(
        "Start or stop the local model servers (Parakeet ASR, Kokoro TTS, llama.cpp LLM). "
        "Only meaningful when a profile uses local providers — cloud backends don't need "
        "any servers started."
    ),
    no_args_is_help=True,
)


@app.command("all")
def all_(
    model: Annotated[
        str,
        typer.Option(
            "--model",
            help=(
                "Which LLM model size to load. 'small' uses the fast/lightweight "
                "model from config (good for dictation cleanup); 'large' uses the "
                "bigger model (better voice-command interpretation, slower startup)."
            ),
        ),
    ] = "small",
    stop: Annotated[
        bool,
        typer.Option(
            "--stop",
            help="Stop every running local server instead of starting them.",
        ),
    ] = False,
) -> None:
    """Start (or stop with --stop) every local model server in one shot."""
    if stop:
        resp = try_rpc("servers.stop", {"which": "all"})
        if resp is None:
            rc = legacy_servers([])  # legacy script auto-toggles: if running, stops
            raise typer.Exit(rc)
        from porcaria.cli._common import print_rpc

        print_rpc(resp)
        return

    resp = try_rpc("servers.start", {"which": "all", "model": model})
    if resp is None:
        rc = legacy_servers([f"--{model}"])
        raise typer.Exit(rc)
    from porcaria.cli._common import print_rpc

    print_rpc(resp)


@app.command("asr")
def asr(
    stop: Annotated[
        bool,
        typer.Option("--stop", help="Stop the ASR server instead of starting it."),
    ] = False,
) -> None:
    """Start (or stop with --stop) the local ASR server (Parakeet by default)."""
    method = "servers.stop" if stop else "servers.start"
    resp = try_rpc(method, {"which": "asr"})
    if resp is None:
        typer.secho(
            "daemon not running; per-service start/stop needs the daemon (use `porcaria serve all` for legacy behavior)",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(2)
    from porcaria.cli._common import print_rpc

    print_rpc(resp)


@app.command("tts")
def tts(
    stop: Annotated[
        bool,
        typer.Option("--stop", help="Stop the TTS server instead of starting it."),
    ] = False,
) -> None:
    """Start (or stop with --stop) the local TTS server (Kokoro by default)."""
    method = "servers.stop" if stop else "servers.start"
    resp = try_rpc(method, {"which": "tts"})
    if resp is None:
        typer.secho("daemon not running", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(2)
    from porcaria.cli._common import print_rpc

    print_rpc(resp)


@app.command("llm")
def llm(
    model: Annotated[
        str,
        typer.Option(
            "--model",
            help=(
                "Which LLM model size to load. 'small' is the lightweight dictation "
                "model; 'large' is the heavier command-interpretation model."
            ),
        ),
    ] = "small",
    stop: Annotated[
        bool,
        typer.Option("--stop", help="Stop the LLM server instead of starting it."),
    ] = False,
) -> None:
    """Start (or stop with --stop) the local LLM server (llama.cpp by default)."""
    method = "servers.stop" if stop else "servers.start"
    resp = try_rpc(method, {"which": "llm", "model": model})
    if resp is None:
        typer.secho("daemon not running", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(2)
    from porcaria.cli._common import print_rpc

    print_rpc(resp)
