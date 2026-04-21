"""Pydantic models for the porcaria config."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- profiles ----------


class Profile(_Strict):
    asr: str
    tts: str
    llm: str
    sinks: list[str] = Field(default_factory=list)


# ---------- ASR ----------


class ParakeetCfg(_Strict):
    url: str = "http://127.0.0.1:5092"
    device: str = "cuda"
    model: str = "nvidia/parakeet-tdt-0.6b-v3"


class OpenAIWhisperCfg(_Strict):
    api_key_env: str = "OPENAI_API_KEY"
    model: str = "whisper-1"
    base_url: str = "https://api.openai.com/v1"


class ASRCfg(_Strict):
    parakeet: ParakeetCfg = ParakeetCfg()
    openai_whisper: OpenAIWhisperCfg = OpenAIWhisperCfg()


# ---------- TTS ----------


class KokoroCfg(_Strict):
    url: str = "http://127.0.0.1:5093"
    voice: str = "af_heart"
    speed: float = 1.0
    model_path: str = "~/.cache/porcaria/kokoro/kokoro-v1.0.onnx"
    voices_path: str = "~/.cache/porcaria/kokoro/voices-v1.0.bin"
    auto_download: bool = True
    model_url: str = (
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
    )
    voices_url: str = (
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
    )
    # Empty string disables hash check (e.g. when pointing at a custom quantization).
    model_sha256: str = "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5"
    voices_sha256: str = "d19762d46cf0e6648cb28a7711df1637aad15818185d13f4ff840d57f2f6dfed"


class OpenAITTSCfg(_Strict):
    api_key_env: str = "OPENAI_API_KEY"
    model: str = "tts-1"
    voice: str = "alloy"
    base_url: str = "https://api.openai.com/v1"


class ElevenLabsCfg(_Strict):
    api_key_env: str = "ELEVENLABS_API_KEY"
    voice_id: str = ""
    model: str = "eleven_turbo_v2_5"


class NoneTTSCfg(_Strict):
    pass


class TTSCfg(_Strict):
    kokoro: KokoroCfg = KokoroCfg()
    openai_tts: OpenAITTSCfg = OpenAITTSCfg()
    elevenlabs: ElevenLabsCfg = ElevenLabsCfg()
    none: NoneTTSCfg = NoneTTSCfg()


# ---------- LLM ----------


class LlamaCppCfg(_Strict):
    url: str = "http://127.0.0.1:8089"
    model_small: str = "ggml-org/Qwen3-4B-Instruct-2507-Q8_0-GGUF"
    model_large: str = "ggml-org/gpt-oss-120b-GGUF"
    ctx_small: int = 8192
    ctx_large: int = 32768


class OpenRouterCfg(_Strict):
    api_key_env: str = "OPENROUTER_API_KEY"
    model: str = "anthropic/claude-sonnet-4-6"
    base_url: str = "https://openrouter.ai/api/v1"


class LLMCfg(_Strict):
    llamacpp: LlamaCppCfg = LlamaCppCfg()
    openrouter: OpenRouterCfg = OpenRouterCfg()


# ---------- capture ----------


class CaptureCfg(_Strict):
    sample_rate: int = 16000
    mono: bool = True
    timeout_seconds: int = 600
    pulse_source: str = "default"


# ---------- sinks ----------


class ClipboardCfg(_Strict):
    tool: Literal["auto", "wl-copy", "xclip", "pbcopy"] = "auto"


class QuickNoteCfg(_Strict):
    dir: str = "$XDG_DOCUMENTS_DIR/quick-notes"


class FazereiCfg(_Strict):
    command: str = "fazerei"
    enabled: bool = True


class SinksCfg(_Strict):
    clipboard: ClipboardCfg = ClipboardCfg()
    quick_note: QuickNoteCfg = QuickNoteCfg()
    fazerei: FazereiCfg = FazereiCfg()


# ---------- daemon ----------


class DaemonCfg(_Strict):
    ipc_socket: str = ""
    http_enabled: bool = False
    http_bind: str = "127.0.0.1:8790"


# ---------- servers (supervised sub-processes) ----------


class LlamaServerCfg(_Strict):
    port: int = 8089
    flash_attn: bool = True
    kv_cache_type: str = "q8_0"
    batch_size: int = 2048
    ubatch_size: int = 2048
    fit_target: int = 4096
    binary: str = "llama-server"


class ParakeetServerCfg(_Strict):
    port: int = 5092
    device: str = "cuda"
    model: str = "nvidia/parakeet-tdt-0.6b-v3"
    python_executable: str = ""  # blank → sys.executable


class KokoroServerCfg(_Strict):
    port: int = 5093
    python_executable: str = ""  # blank → sys.executable


class ServersCfg(_Strict):
    llamacpp: LlamaServerCfg = LlamaServerCfg()
    parakeet: ParakeetServerCfg = ParakeetServerCfg()
    kokoro: KokoroServerCfg = KokoroServerCfg()


# ---------- root ----------


class Config(_Strict):
    active_profile: str = "home"
    profiles: dict[str, Profile]
    asr: ASRCfg = ASRCfg()
    tts: TTSCfg = TTSCfg()
    llm: LLMCfg = LLMCfg()
    capture: CaptureCfg = CaptureCfg()
    sinks: SinksCfg = SinksCfg()
    daemon: DaemonCfg = DaemonCfg()
    servers: ServersCfg = ServersCfg()

    def profile(self, name: str | None = None) -> Profile:
        key = name or self.active_profile
        if key not in self.profiles:
            raise KeyError(f"profile '{key}' not in config (have: {sorted(self.profiles)})")
        return self.profiles[key]
