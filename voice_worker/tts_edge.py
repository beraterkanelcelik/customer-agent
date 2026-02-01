"""
Edge TTS - Microsoft's free neural text-to-speech.

This provides very natural sounding voices without requiring
any API key or GPU. It's cloud-based so requires internet.

Available voices: https://speech.microsoft.com/portal/voicegallery
"""

import asyncio
import io
import wave
import logging
from typing import Optional

import edge_tts
import numpy as np

from .config import get_voice_settings

settings = get_voice_settings()
logger = logging.getLogger("voice_worker.tts_edge")

# Recommended voices for customer service
VOICE_OPTIONS = {
    "female_us": "en-US-JennyNeural",      # Natural, friendly
    "female_us_2": "en-US-AriaNeural",     # Professional
    "male_us": "en-US-GuyNeural",          # Warm, professional
    "female_uk": "en-GB-SoniaNeural",      # British accent
    "male_uk": "en-GB-RyanNeural",         # British accent
}

# Default to Jenny - very natural sounding
DEFAULT_VOICE = "en-US-JennyNeural"


class EdgeTextToSpeech:
    """
    Text-to-Speech using Microsoft Edge TTS.

    Benefits:
    - Free (no API key needed)
    - Very high quality neural voices
    - Fast (cloud-based)
    - Many voice options
    """

    def __init__(self, voice: str = None):
        self.voice = voice or settings.edge_tts_voice or DEFAULT_VOICE
        self._loaded = True  # No model loading needed
        self._sample_rate = 24000  # Edge TTS outputs 24kHz

    def load_model(self):
        """No model loading needed for Edge TTS."""
        pass

    @property
    def sample_rate(self) -> int:
        """Get the output sample rate."""
        return self._sample_rate

    async def synthesize_async(self, text: str, max_retries: int = 3) -> bytes:
        """
        Synthesize text to audio using Edge TTS.

        Args:
            text: Text to speak
            max_retries: Number of retries on failure

        Returns:
            WAV audio bytes
        """
        if not text.strip():
            return b""

        last_error = None
        for attempt in range(max_retries):
            try:
                # Create communicate object
                communicate = edge_tts.Communicate(text, self.voice)

                # Collect all audio chunks
                audio_chunks = []
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_chunks.append(chunk["data"])

                if not audio_chunks:
                    logger.warning("Edge TTS returned no audio")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    return b""

                # Combine chunks (MP3 format from Edge)
                mp3_data = b"".join(audio_chunks)

                # Convert MP3 to WAV using ffmpeg via pydub or manually
                wav_data = await self._mp3_to_wav(mp3_data)

                return wav_data

            except Exception as e:
                last_error = e
                logger.warning(f"Edge TTS attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))  # Exponential backoff

        logger.error(f"Edge TTS failed after {max_retries} attempts: {last_error}")
        return b""

    def synthesize(self, text: str) -> bytes:
        """Synchronous version of synthesize."""
        return asyncio.get_event_loop().run_until_complete(
            self.synthesize_async(text)
        )

    async def _mp3_to_wav(self, mp3_data: bytes) -> bytes:
        """Convert MP3 to WAV format."""
        try:
            # Use pydub if available
            from pydub import AudioSegment

            audio = AudioSegment.from_mp3(io.BytesIO(mp3_data))
            audio = audio.set_channels(1)  # Mono
            audio = audio.set_frame_rate(self._sample_rate)

            wav_buffer = io.BytesIO()
            audio.export(wav_buffer, format="wav")
            return wav_buffer.getvalue()

        except ImportError:
            # Fallback: use ffmpeg directly via subprocess
            import subprocess
            import tempfile
            import os

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as mp3_file:
                mp3_file.write(mp3_data)
                mp3_path = mp3_file.name

            wav_path = mp3_path.replace(".mp3", ".wav")

            try:
                # Convert using ffmpeg
                process = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-i", mp3_path,
                    "-ar", str(self._sample_rate),
                    "-ac", "1",  # mono
                    "-y",  # overwrite
                    wav_path,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL
                )
                await process.wait()

                with open(wav_path, "rb") as f:
                    wav_data = f.read()

                return wav_data

            finally:
                # Cleanup temp files
                if os.path.exists(mp3_path):
                    os.remove(mp3_path)
                if os.path.exists(wav_path):
                    os.remove(wav_path)


# Global instance
edge_tts_instance = EdgeTextToSpeech()
