"""
Kokoro TTS - Lightweight, high-quality neural text-to-speech.

Kokoro-82M is a fast, efficient TTS model that runs locally with
minimal VRAM requirements (<2GB). Perfect for real-time voice agents.

Model: https://huggingface.co/hexgrad/Kokoro-82M
"""

import asyncio
import io
import wave
import logging
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from .config import get_voice_settings

settings = get_voice_settings()
logger = logging.getLogger("voice_worker.tts_kokoro")

# Thread pool for CPU/GPU-bound TTS
_executor = ThreadPoolExecutor(max_workers=2)

# Available Kokoro voices (subset - see full list at huggingface)
VOICE_OPTIONS = {
    # American English
    "af_heart": "af_heart",       # Female, warm and friendly (recommended)
    "af_bella": "af_bella",       # Female, professional
    "af_sarah": "af_sarah",       # Female, clear
    "am_adam": "am_adam",         # Male, professional
    "am_michael": "am_michael",   # Male, warm
    # British English
    "bf_emma": "bf_emma",         # Female, British
    "bm_george": "bm_george",     # Male, British
}

DEFAULT_VOICE = "af_heart"  # Warm, friendly female voice - good for customer service


class KokoroTextToSpeech:
    """
    Text-to-Speech using Kokoro-82M.

    Benefits:
    - Very lightweight (82M parameters, <2GB VRAM)
    - High quality (StyleTTS 2 architecture)
    - Fast inference (no diffusion)
    - Runs locally (GPU or CPU)
    - Apache 2.0 license
    """

    def __init__(self, voice: str = None, lang_code: str = None):
        """
        Initialize Kokoro TTS.

        Args:
            voice: Voice ID (e.g., 'af_heart', 'am_adam')
            lang_code: Language code ('a' for American English, 'b' for British)
        """
        self.voice = voice or settings.kokoro_voice or DEFAULT_VOICE
        self.lang_code = lang_code or settings.kokoro_lang_code or "a"
        self._pipeline = None
        self._loaded = False
        self._sample_rate = 24000  # Kokoro outputs 24kHz

    def load_model(self):
        """Load the Kokoro pipeline."""
        if self._loaded:
            return

        logger.info(f"Loading Kokoro TTS (voice: {self.voice}, lang: {self.lang_code})")

        try:
            from kokoro import KPipeline
        except ImportError:
            raise ImportError(
                "Kokoro not installed. Install with: pip install kokoro>=0.9.2\n"
                "Also install espeak-ng: https://github.com/espeak-ng/espeak-ng/releases"
            )

        # Initialize the pipeline
        # lang_code: 'a' = American English, 'b' = British English, etc.
        self._pipeline = KPipeline(lang_code=self.lang_code)
        self._loaded = True

        logger.info(f"Kokoro TTS loaded successfully (sample rate: {self._sample_rate})")

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

        try:
            # Generate audio using Kokoro pipeline
            audio_chunks = []

            for _, _, audio in self._pipeline(text, voice=self.voice):
                if audio is not None:
                    audio_chunks.append(audio)

            if not audio_chunks:
                logger.warning("Kokoro returned no audio")
                return b""

            # Concatenate all audio chunks
            full_audio = np.concatenate(audio_chunks)

            # Convert float32 audio to int16 WAV
            audio_int16 = (full_audio * 32767).astype(np.int16)

            # Create WAV buffer
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)  # 16-bit
                wav.setframerate(self._sample_rate)
                wav.writeframes(audio_int16.tobytes())

            return wav_buffer.getvalue()

        except Exception as e:
            logger.error(f"Kokoro synthesis error: {e}")
            return b""

    async def synthesize_async(self, text: str) -> bytes:
        """Async version of synthesize."""
        if not self._loaded:
            # Load model in thread pool to not block event loop
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(_executor, self.load_model)

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, self.synthesize, text)

    def synthesize_to_numpy(self, text: str) -> np.ndarray:
        """
        Synthesize to numpy array.

        Returns:
            Float32 numpy array of audio samples
        """
        if not self._loaded:
            self.load_model()

        if not text.strip():
            return np.array([], dtype=np.float32)

        try:
            audio_chunks = []
            for _, _, audio in self._pipeline(text, voice=self.voice):
                if audio is not None:
                    audio_chunks.append(audio)

            if not audio_chunks:
                return np.array([], dtype=np.float32)

            return np.concatenate(audio_chunks)

        except Exception as e:
            logger.error(f"Kokoro synthesis error: {e}")
            return np.array([], dtype=np.float32)


# Global instance
kokoro_tts_instance = KokoroTextToSpeech()
