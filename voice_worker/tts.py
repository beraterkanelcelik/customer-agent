import numpy as np
from typing import Optional, Generator, AsyncGenerator
from pathlib import Path
import io
import wave
import asyncio
from concurrent.futures import ThreadPoolExecutor

from .config import get_voice_settings

settings = get_voice_settings()

# Thread pool for CPU-bound TTS
_executor = ThreadPoolExecutor(max_workers=2)


class TextToSpeech:
    """
    Text-to-Speech using Piper.

    Piper is a fast, local neural TTS system that produces
    natural-sounding speech with low latency.
    """

    def __init__(self):
        self.voice = None
        self._loaded = False
        self._sample_rate = 22050  # Piper default

    def load_model(self):
        """Load the Piper voice model."""
        if self._loaded:
            return

        print(f"Loading Piper voice: {settings.piper_voice}")

        # Import piper
        try:
            from piper import PiperVoice
        except ImportError:
            # Alternative import for some installations
            from piper.voice import PiperVoice

        model_path = Path(settings.models_path) / "piper" / f"{settings.piper_voice}.onnx"
        config_path = Path(settings.models_path) / "piper" / f"{settings.piper_voice}.onnx.json"

        if not model_path.exists():
            raise FileNotFoundError(
                f"Piper model not found at {model_path}. "
                f"Download from: https://huggingface.co/rhasspy/piper-voices"
            )

        self.voice = PiperVoice.load(str(model_path), str(config_path))
        self._loaded = True

        print(f"Piper voice loaded successfully (sample rate: {self._sample_rate})")

    @property
    def sample_rate(self) -> int:
        """Get the output sample rate."""
        return self._sample_rate

    def synthesize(self, text: str) -> bytes:
        """
        Synthesize text to audio.

        Args:
            text: Text to speak

        Returns:
            WAV audio bytes
        """
        if not self._loaded:
            self.load_model()

        if not text.strip():
            return b""

        # Generate audio
        audio_buffer = io.BytesIO()

        with wave.open(audio_buffer, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)  # 16-bit
            wav.setframerate(self._sample_rate)

            # Synthesize
            for audio_chunk in self.voice.synthesize_stream_raw(text):
                wav.writeframes(audio_chunk)

        return audio_buffer.getvalue()

    async def synthesize_async(self, text: str) -> bytes:
        """Async version of synthesize."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, self.synthesize, text)

    def synthesize_stream(self, text: str) -> Generator[bytes, None, None]:
        """
        Stream audio chunks as they're generated.

        Yields:
            Raw PCM audio chunks (16-bit, mono)
        """
        if not self._loaded:
            self.load_model()

        if not text.strip():
            return

        for audio_chunk in self.voice.synthesize_stream_raw(text):
            yield audio_chunk

    async def synthesize_stream_async(self, text: str) -> AsyncGenerator[bytes, None]:
        """
        Async streaming synthesis.

        Yields:
            Raw PCM audio chunks
        """
        if not self._loaded:
            self.load_model()

        if not text.strip():
            return

        # Run in thread pool to not block event loop
        loop = asyncio.get_event_loop()

        def generate():
            return list(self.voice.synthesize_stream_raw(text))

        chunks = await loop.run_in_executor(_executor, generate)

        for chunk in chunks:
            yield chunk
            await asyncio.sleep(0)  # Yield control

    def synthesize_to_numpy(self, text: str) -> np.ndarray:
        """
        Synthesize to numpy array.

        Returns:
            Float32 numpy array of audio samples
        """
        wav_bytes = self.synthesize(text)

        with io.BytesIO(wav_bytes) as f:
            with wave.open(f, 'rb') as wav:
                frames = wav.readframes(wav.getnframes())
                audio = np.frombuffer(frames, dtype=np.int16)
                return audio.astype(np.float32) / 32768.0


# Global instance
tts = TextToSpeech()
