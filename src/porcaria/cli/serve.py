"""`porcaria serve {all,asr,tts,llm}` — start/stop local model servers."""
from __future__ import annotations

import sys
from typing import Annotated

import typer

from porcaria import notify
from porcaria.cli._common import try_rpc


def _announce(msg: str) -> None:
    """Emit a CYAN status line to stderr and flush immediately so the user
    sees it before any long-blocking RPC."""
    typer.secho(msg, fg=typer.colors.CYAN, err=True)
    sys.stderr.flush()


def _fail_no_daemon() -> None:
    """Exit with a daemon-not-running error, also sent as a desktop
    notification so Hyprland keybinds don't fail silently."""
    msg = "Run `porcaria daemon start` first."
    typer.secho(f"daemon not running; {msg.lower()}", fg=typer.colors.YELLOW, err=True)
    notify.error("Porcaria daemon offline", msg)
    raise typer.Exit(2)

app = typer.Typer(
    help=(
        "Start or stop the local model servers (Parakeet ASR, Kokoro TTS, llama.cpp LLM). "
        "Only meaningful when a profile uses local providers — cloud backends don't need "
        "any servers started."
    ),
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
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
    toggle: Annotated[
        bool,
        typer.Option(
            "--toggle",
            help=(
                "Toggle: start the stack if nothing is running, stop it if anything is. "
                "Use this for a single Hyprland keybind that both starts and stops the "
                "servers."
            ),
        ),
    ] = False,
) -> None:
    """Start, stop, or toggle every local model server in one shot.

    Default is idempotent-start (no-op if already running). Pass --stop to stop
    everything, or --toggle to flip state — use --toggle in Hyprland keybinds so
    one key both launches and tears down the stack."""
    if stop and toggle:
        typer.secho("--stop and --toggle are mutually exclusive", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)

    if toggle:
        _announce(
            f"Toggling model servers (will start kokoro → parakeet → llama.cpp "
            f"({model}) if stopped, or stop them if running)."
        )
        resp = try_rpc("servers.toggle", {"model": model})
        if resp is None:
            _fail_no_daemon()
        from porcaria.cli._common import print_rpc

        print_rpc(resp)
        return

    if stop:
        _announce("Stopping all local model servers…")
        resp = try_rpc("servers.stop", {"which": "all"})
        if resp is None:
            _fail_no_daemon()
        from porcaria.cli._common import print_rpc

        print_rpc(resp)
        return

    _announce(
        f"Starting kokoro → parakeet → llama.cpp ({model}). The daemon waits for "
        "each /health endpoint before starting the next, so first launch can take "
        "a few minutes (model weights load on GPU). You'll see desktop notifications "
        "as each service comes up."
    )
    resp = try_rpc("servers.start", {"which": "all", "model": model})
    if resp is None:
        _fail_no_daemon()
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
    _announce(
        "Stopping ASR server…" if stop
        else "Starting ASR server (parakeet)… up to 2 minutes on first launch."
    )
    resp = try_rpc(method, {"which": "asr"})
    if resp is None:
        typer.secho(
            "daemon not running; run `porcaria daemon start` first",
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
    _announce(
        "Stopping TTS server…" if stop
        else "Starting TTS server (kokoro)… ready in a few seconds."
    )
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
    _announce(
        "Stopping LLM server…" if stop
        else f"Starting LLM server (llama.cpp {model})… up to 4 minutes on first launch."
    )
    resp = try_rpc(method, {"which": "llm", "model": model})
    if resp is None:
        typer.secho("daemon not running", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(2)
    from porcaria.cli._common import print_rpc

    print_rpc(resp)
