# porcaria

Portable voice-AI pipeline. Capture audio → transcribe → (optionally) process with an LLM → route to a sink (clipboard, quick-note, task CLI, …). Pluggable providers: local (Parakeet, Kokoro, llama.cpp) or cloud (OpenAI Whisper, OpenAI TTS, ElevenLabs, OpenRouter). Exposed via a CLI and a long-lived daemon with Unix-socket + optional HTTP IPC.

## Install

```sh
# GPU workstation (local models)
uv tool install --from /home/travis/dev/porcaria 'porcaria[parakeet,kokoro,cloud]'

# Travel laptop (cloud only)
uv tool install --from /home/travis/dev/porcaria 'porcaria[cloud]'
```

## First-run setup

Run these four commands once after install:

```sh
porcaria config edit                # seed + open ~/.config/porcaria/config.toml in $EDITOR
porcaria daemon start               # background daemon (UDS at $XDG_RUNTIME_DIR/porcaria/)
porcaria serve all --model small    # spin up local Parakeet + Kokoro + llama.cpp (~7 s)
porcaria status                     # confirm providers + servers are healthy
```

To tear everything down: `porcaria serve all --stop`. For a one-key toggle suitable for a Hyprland bind, use `porcaria serve all --toggle` (see the keybind section below).

After any `porcaria config edit`, run `porcaria daemon reload` so the daemon picks up the changes.

## Cheat-sheet

| Command                                        | What it does                                                       |
|------------------------------------------------|--------------------------------------------------------------------|
| `porcaria dictate`                             | Toggle recording → transcribe → clipboard                          |
| `porcaria dictate --clean`                     | Toggle recording → transcribe → LLM-polish → clipboard             |
| `porcaria dictate --sinks note`                | Toggle recording → transcribe → quick-note file (no clipboard)     |
| `porcaria dictate --sinks clipboard,note`      | Send the transcript to both clipboard and a quick-note file        |
| `porcaria dictate --sinks speaker`             | Read the transcript back aloud through the speakers                |
| `porcaria dictate --route task`                | Toggle recording → voice-command the task CLI (fazerei)            |
| `porcaria transcribe clip.wav`                 | Transcribe an existing WAV through the active ASR                  |
| `porcaria speak "hello world"`                 | Synthesize + play speech through the speakers                      |
| `porcaria speak "hello" --out /tmp/hi.wav`     | Save synthesized audio to a file                                   |
| `porcaria clean --in notes.txt`                | Run text through the LLM cleanup pass                              |
| `porcaria task "add pay rent to personal"`     | Execute a voice-style command without audio capture                |
| `porcaria status`                              | JSON snapshot: active profile + server health                      |
| `porcaria serve all --model small` / `--large` | Start local model servers (small ≈ Qwen3-4B, large ≈ gpt-oss-120b); idempotent no-op if already up |
| `porcaria serve all --stop`                    | Stop all local model servers                                       |
| `porcaria serve all --toggle`                  | Start if stopped, stop if running — the one-keybind behaviour       |
| `porcaria daemon {start,stop,status,reload}`   | Daemon lifecycle                                                   |
| `porcaria config {show,path,edit,validate,defaults}` | Config inspection + editing                                  |

## Hyprland keybind parity

The old `toggle_dictation.sh` / `toggle_ai_servers.sh` flows map one-to-one onto `porcaria` subcommands:

| Keybind           | Legacy bash                                   | Porcaria                                    |
|-------------------|-----------------------------------------------|---------------------------------------------|
| Super+Alt+D       | `toggle_dictation.sh`                         | `porcaria dictate`                          |
| Super+Alt+Shift+D | `toggle_dictation.sh --ai-clean`              | `porcaria dictate --clean`                  |
| Super+Alt+V       | `toggle_dictation.sh --fazerei`               | `porcaria dictate --route task`             |
| Super+Alt+N       | `toggle_dictation.sh --quick-note`            | `porcaria dictate --sinks note`             |
| Super+Alt+Shift+N | `toggle_dictation.sh --quick-note --ai-clean` | `porcaria dictate --clean --sinks note`     |
| Super+Alt+L       | `toggle_ai_servers.sh --small`                | `porcaria serve all --toggle --model small` |
| Super+Alt+Shift+L | `toggle_ai_servers.sh --large`                | `porcaria serve all --toggle --model large` |

Paste into `~/.config/hypr/hyprland.conf`:

```
bind = SUPER_ALT,       D, exec, porcaria dictate
bind = SUPER_ALT_SHIFT, D, exec, porcaria dictate --clean
bind = SUPER_ALT,       V, exec, porcaria dictate --route task
bind = SUPER_ALT,       N, exec, porcaria dictate --sinks note
bind = SUPER_ALT_SHIFT, N, exec, porcaria dictate --clean --sinks note
bind = SUPER_ALT,       L, exec, porcaria serve all --toggle --model small
bind = SUPER_ALT_SHIFT, L, exec, porcaria serve all --toggle --model large
```

### How the keybinds behave

**Decide what to do with the transcript at stop time, not start time.** The start press just begins recording — any flags on it are ignored. The stop press is where `--clean`, `--route`, and `--sinks` take effect. So you can start a dictation with a bare keybind, talk for as long as you want, and then pick the keybind that matches what you actually want to do with the result: raw clipboard, cleaned clipboard, saved note, read-back through the speakers, or voice-command the task CLI. The only thing the start press commits you to is *that you are recording*.

Worked example: press Super+Alt+D to start a rambling 3-minute monologue, realize halfway through it's getting messy, then press Super+Alt+Shift+D (`--clean`) to stop — the LLM cleans up the full transcript and it lands on your clipboard. Or press Super+Alt+Shift+N (`--clean --sinks note`) instead to save the cleaned version to a timestamped file.

**Servers** (`L`, `Shift+L`): `--toggle` means one key both launches and tears down the whole stack. Press once → kokoro/parakeet/llama.cpp come up (~7 s, with desktop notifications per service). Press again → they all stop. Swap between `--model small` and `--model large` by using `Shift+L` — if the other size is already running, only the llama.cpp process is swapped (kokoro + parakeet stay warm).

### Routes vs sinks

Two orthogonal dials control what `dictate` does with the transcript:

- **`--route NAME`** picks the *processing pipeline* the transcript runs through. `default` (no extra processing) just hands off to sinks. `task` has the LLM interpret the utterance as a fazerei command and execute it. Future routes could translate, summarize, etc.
- **`--sinks LIST`** picks the *passive write destinations* for the transcript. `clipboard` copies to the system clipboard, `note` appends to a quick-note file, `speaker` synthesizes + plays the text back. Combine them with commas: `--sinks clipboard,note`.

They're orthogonal — `--route task --sinks note` runs the command AND saves the raw utterance to a note for audit. Defaults: `--route default --sinks clipboard`.

## Pipe examples

Every command reads/writes plain text where possible, so you can chain them:

```sh
# Transcribe a file, then LLM-polish it
porcaria transcribe interview.wav | porcaria clean

# Speak the output of a shell command
echo "build complete" | porcaria speak -

# Pipe synthesized audio into an alternative player
porcaria speak "hello" --stdout | pw-play -

# Save a voice memo to a specific file
porcaria speak "reminder: call alex tomorrow" --out /tmp/memo.wav

# Run a voice-style command with no microphone (for scripting/testing)
porcaria task "mark 42 done"

# Transcribe a file and send the text into the task executor
porcaria transcribe voice-note.wav | xargs -0 porcaria task
```

`dictate`, `transcribe`, `clean`, and `task` all accept `-` where a path/text argument is expected, so stdin composition Just Works.

## Run the daemon under systemd

Skip the "did I forget to start the daemon?" step by letting systemd manage it. Drop this into `~/.config/systemd/user/porcaria.service`:

```ini
[Unit]
Description=porcaria voice-AI daemon
After=default.target

[Service]
Type=simple
ExecStart=%h/.local/bin/porcaria daemon start --foreground
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
```

Then:

```sh
systemctl --user daemon-reload
systemctl --user enable --now porcaria.service
journalctl --user -u porcaria.service -f    # tail the logs
```

## Config recipes

Edits go in `~/.config/porcaria/config.toml` (created by `porcaria config edit`). The full schema lives in `src/porcaria/config/defaults.toml`; every field there can be overridden.

**Switch the LLM to OpenRouter** (travel, or just to save GPU):

```toml
active_profile = "travel"

[llm.openrouter]
api_key_env = "OPENROUTER_API_KEY"
model = "anthropic/claude-sonnet-4-6"
```

**Use OpenAI Whisper when travelling** (no GPU needed):

```toml
active_profile = "travel"   # profiles.travel already sets asr = "openai_whisper"

[asr.openai_whisper]
api_key_env = "OPENAI_API_KEY"
model = "whisper-1"
```

**Record from a specific PulseAudio source**:

```toml
[capture]
pulse_source = "alsa_input.pci-0000_00_1f.3.analog-stereo"   # see `pactl list short sources`
```

After any edit: `porcaria daemon reload`.

`PORCARIA_PROFILE`, `PORCARIA_ASR`, `PORCARIA_TTS`, `PORCARIA_LLM`, `PORCARIA_LLM_URL`, etc. work as env overrides for one-off runs.

## Troubleshooting

| Symptom                                                           | Fix                                                                                      |
|-------------------------------------------------------------------|------------------------------------------------------------------------------------------|
| `porcaria speak "hi"` dumps binary to the terminal                | Upgrade — `speak` now plays by default on a TTY. Use `--stdout` to force pipe mode.      |
| `daemon not running; …subcommand requires the daemon`             | `porcaria daemon start` (or enable the systemd unit above).                              |
| `transcribe` hangs or returns empty text                          | `porcaria serve asr` to restart Parakeet; check `porcaria status` and daemon.log.        |
| `serve all` reports `ModuleNotFoundError: kokoro_onnx` / `torch`  | Porcaria auto-detects `~/.local/share/uv/tools/{kokoro-tts,nano-parakeet}/bin/python`. If yours live elsewhere, set `[servers.kokoro] python_executable = "..."` and `[servers.parakeet] python_executable = "..."` in config.toml. |
| My `config edit` didn't take effect                               | Run `porcaria daemon reload` — the daemon caches provider clients until reloaded.        |
| `no audio player found`                                           | Install one of: `pw-play` (pipewire), `ffplay` (ffmpeg), `paplay` (pulseaudio).          |
| `porcaria daemon status` says `ipc_ok: false`                     | Stale socket. `porcaria daemon stop`, delete `$XDG_RUNTIME_DIR/porcaria/ipc.sock`, start again. |

Daemon log lives at `$XDG_RUNTIME_DIR/porcaria/daemon.log` (usually `/run/user/$UID/porcaria/daemon.log`). Set `PORCARIA_TIMING=1` before starting the daemon to get per-stage timing logs in `pipeline.dictate`.

## Config reference

`~/.config/porcaria/config.toml` — see `src/porcaria/config/defaults.toml` for the full schema. Env overrides: `PORCARIA_PROFILE`, `PORCARIA_ASR`, `PORCARIA_TTS`, `PORCARIA_LLM`, `PORCARIA_LLM_URL`, etc.
