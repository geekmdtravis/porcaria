"""`porcaria serve {all,asr,tts,llm}` — start/stop local model servers."""
from __future__ import annotations

from typing import Annotated

import typer

from porcaria.cli._common import legacy_servers, try_rpc

app = typer.Typer(help="Start/stop local model servers.", no_args_is_help=True)


@app.command("all")
def all_(
    model: Annotated[str, typer.Option("--model", help="'small' or 'large'.")] = "small",
    stop: Annotated[bool, typer.Option("--stop", help="Stop all servers instead of starting.")] = False,
) -> None:
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
    stop: Annotated[bool, typer.Option("--stop")] = False,
) -> None:
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
def tts(stop: Annotated[bool, typer.Option("--stop")] = False) -> None:
    method = "servers.stop" if stop else "servers.start"
    resp = try_rpc(method, {"which": "tts"})
    if resp is None:
        typer.secho("daemon not running", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(2)
    from porcaria.cli._common import print_rpc

    print_rpc(resp)


@app.command("llm")
def llm(
    model: Annotated[str, typer.Option("--model")] = "small",
    stop: Annotated[bool, typer.Option("--stop")] = False,
) -> None:
    method = "servers.stop" if stop else "servers.start"
    resp = try_rpc(method, {"which": "llm", "model": model})
    if resp is None:
        typer.secho("daemon not running", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(2)
    from porcaria.cli._common import print_rpc

    print_rpc(resp)
