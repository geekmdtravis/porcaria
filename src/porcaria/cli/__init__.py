"""porcaria CLI entry point."""
from __future__ import annotations

import typer

from porcaria.cli import clean, config as config_cmd, daemon, dictate, serve, speak, status, task, transcribe

app = typer.Typer(
    name="porcaria",
    help=(
        "Portable voice-AI pipeline (capture → ASR → LLM → sink).\n\n"
        "Most commands talk to a long-lived background daemon over a Unix socket. "
        "Start it once with `porcaria daemon start`; it manages the local "
        "Parakeet/Kokoro/llama.cpp servers and serves RPCs for dictation, "
        "transcription, TTS, and LLM cleanup. `porcaria config edit` opens the "
        "user config to swap providers or switch profiles (home/travel/etc)."
    ),
    no_args_is_help=True,
    add_completion=False,
)

app.command("dictate")(dictate.main)
app.command("transcribe")(transcribe.main)
app.command("speak")(speak.main)
app.command("clean")(clean.main)
app.command("task")(task.main)
app.command("status")(status.main)

app.add_typer(
    serve.app,
    name="serve",
    help="Start or stop local model servers (Parakeet ASR / Kokoro TTS / llama.cpp LLM).",
)
app.add_typer(
    daemon.app,
    name="daemon",
    help="Start, stop, and reload the long-lived porcaria daemon.",
)
app.add_typer(
    config_cmd.app,
    name="config",
    help="Inspect, edit, and validate the porcaria config.",
)


if __name__ == "__main__":
    app()
