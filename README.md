# porcaria

Portable voice-AI pipeline. Capture audio → transcribe → (optionally) process with an LLM → route to a sink (clipboard, quick-note, task CLI, …). Pluggable providers: local (Parakeet, Whisper.cpp, Kokoro, llama.cpp) or cloud (OpenAI Whisper, OpenAI TTS, ElevenLabs, OpenRouter). Exposed via a CLI and a long-lived daemon with Unix-socket + optional HTTP IPC.

## Install

```sh
# GPU workstation (local models)
uv tool install --from /home/travis/dev/porcaria 'porcaria[parakeet,kokoro,cloud]'

# Travel laptop (cloud only)
uv tool install --from /home/travis/dev/porcaria 'porcaria[cloud]'
```

## Quick start

```sh
# One-time: write a config (copies defaults.toml to $XDG_CONFIG_HOME/porcaria/config.toml)
porcaria config edit

# Start the daemon (supervises local model servers, exposes IPC)
porcaria daemon start

# Status check
porcaria status

# Record → transcribe → clipboard
porcaria dictate

# Record → transcribe → clean via LLM → clipboard
porcaria dictate --clean

# Record → transcribe → save to quick notes
porcaria dictate --note

# Record → voice-command a task CLI (e.g. fazerei)
porcaria dictate --route task
```

## Hyprland keybind migration

Today's binds call `toggle_dictation.sh` directly. During Phase 1 migration, the bash script becomes a thin wrapper; once Phase 3 ships you can rewrite the binds to call `porcaria` directly, e.g.:

```
bind = SUPER_ALT, D, exec, porcaria dictate
bind = SUPER_ALT_SHIFT, D, exec, porcaria dictate --clean
bind = SUPER_ALT, V, exec, porcaria dictate --route task
bind = SUPER_ALT, N, exec, porcaria dictate --note
bind = SUPER_ALT_SHIFT, N, exec, porcaria dictate --clean --note
bind = SUPER_ALT, L, exec, porcaria serve all --model small
bind = SUPER_ALT_SHIFT, L, exec, porcaria serve all --model large
```

## Config

`$XDG_CONFIG_HOME/porcaria/config.toml` — see `src/porcaria/config/defaults.toml` for the full schema. Env overrides: `PORCARIA_PROFILE`, `PORCARIA_ASR`, `PORCARIA_TTS`, `PORCARIA_LLM`, `PORCARIA_LLM_URL`, etc.

## Status

Phase 1 — scaffold + daemon skeleton + strangler CLI that falls back to the existing bash scripts in `~/.config/hypr/scripts/` when the native pipeline isn't implemented yet. See `/home/travis/.claude/plans/dotfiles-hypr-config-hypr-the-folder-i-parallel-dolphin.md` for the full phased plan.
