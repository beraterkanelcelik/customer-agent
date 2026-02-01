from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache


class VoiceSettings(BaseSettings):
    """Voice worker configuration."""

    # App API
    app_api_url: str = Field(default="http://app:8000")

    # LiveKit
    livekit_url: str = Field(default="ws://livekit:7880")
    livekit_api_key: str = Field(default="devkey")
    livekit_api_secret: str = Field(default="secret")

    # Redis
    redis_url: str = Field(default="redis://redis:6379/0")

    # Whisper STT
    whisper_model: str = Field(default="medium")  # medium with INT8 for best accuracy
    whisper_device: str = Field(default="cuda")  # Use GPU for faster transcription

    # TTS Backend: "kokoro" (local, GPU), "piper" (local, CPU), or "edge" (cloud)
    tts_backend: str = Field(default="kokoro")

    # Kokoro TTS (local, GPU-accelerated, high quality, low VRAM)
    kokoro_voice: str = Field(default="af_heart")  # Warm, friendly female voice
    kokoro_lang_code: str = Field(default="a")  # 'a' = American English, 'b' = British

    # Piper TTS (local, CPU-based)
    piper_voice: str = Field(default="en_US-lessac-high")  # High quality voice

    # Edge TTS (cloud - Microsoft's free neural TTS)
    edge_tts_voice: str = Field(default="en-US-JennyNeural")  # Natural, friendly voice

    # Paths
    models_path: str = Field(default="/app/models")

    # Audio settings
    input_sample_rate: int = Field(default=16000)
    output_sample_rate: int = Field(default=22050)

    # Timeouts
    vad_silence_duration_ms: int = Field(default=500)
    max_speech_duration_s: int = Field(default=30)

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_voice_settings() -> VoiceSettings:
    return VoiceSettings()
