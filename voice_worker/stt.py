import asyncio
import numpy as np
from typing import Optional, Union
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import io
import wave

from faster_whisper import WhisperModel

from .config import get_voice_settings

settings = get_voice_settings()

# Thread pool for CPU-bound transcription
_executor = ThreadPoolExecutor(max_workers=2)

# Context prompt to help Whisper understand the domain
WHISPER_PROMPT = """Car dealership customer service conversation. The customer is speaking about:
test drive, oil change, brake service, tire rotation, appointment, schedule, booking.
Vehicle brands and models: Honda Civic, Toyota Camry, Ford F-150, Chevrolet Malibu,
BMW 3 Series, Mercedes C-Class, Volkswagen Golf 7, Golf GTI, Passat, Jetta, Tiguan.
Common phrases: I want to book, I'd like to schedule, test drive please, Golf 7, tomorrow, next week."""


class SpeechToText:
    """
    Speech-to-Text using Faster Whisper.

    Faster Whisper is a reimplementation of OpenAI's Whisper
    using CTranslate2, which is 4x faster with lower memory usage.
    """

    def __init__(self):
        self.model: Optional[WhisperModel] = None
        self._model_loaded = False

    @property
    def _loaded(self):
        return self._model_loaded

    def load_model(self):
        """Load the Whisper model."""
        if self._model_loaded:
            return

        print(f"Loading Whisper model: {settings.whisper_model}")
        print(f"Device: {settings.whisper_device}")

        # Use INT8 quantization for better memory efficiency on limited VRAM
        compute_type = "int8"

        self.model = WhisperModel(
            settings.whisper_model,
            device=settings.whisper_device,
            compute_type=compute_type,
            download_root=str(Path(settings.models_path) / "whisper")
        )

        self._model_loaded = True
        print("Whisper model loaded successfully")

    async def transcribe(
        self,
        audio_data: Union[bytes, np.ndarray],
        sample_rate: int = 16000
    ) -> str:
        """
        Transcribe audio to text.

        Args:
            audio_data: Audio as bytes or numpy array
            sample_rate: Audio sample rate (default 16000 Hz)

        Returns:
            Transcribed text
        """
        if not self._model_loaded:
            self.load_model()

        # Convert bytes to numpy if needed
        if isinstance(audio_data, bytes):
            audio_array = self._bytes_to_numpy(audio_data, sample_rate)
        else:
            audio_array = audio_data

        # Ensure float32 and correct shape
        audio_array = audio_array.astype(np.float32)

        # Normalize if needed
        if audio_array.max() > 1.0:
            audio_array = audio_array / 32768.0

        # Run transcription in thread pool to avoid blocking event loop
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(
            _executor,
            self._transcribe_sync,
            audio_array
        )

        return text.strip()

    def _transcribe_sync(self, audio_array: np.ndarray) -> str:
        """Synchronous transcription (runs in thread pool)."""
        # Transcribe with context prompt for better accuracy
        segments, info = self.model.transcribe(
            audio_array,
            language="en",
            initial_prompt=WHISPER_PROMPT,
            beam_size=5,
            best_of=3,
            patience=1.0,
            temperature=0.0,
            compression_ratio_threshold=2.4,
            condition_on_previous_text=True,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=300,  # Reduced from 500ms
                speech_pad_ms=250,  # Increased padding
                threshold=0.5,
                min_speech_duration_ms=100
            )
        )

        # Combine segments
        text = " ".join(segment.text.strip() for segment in segments)
        return text

    def _bytes_to_numpy(self, audio_bytes: bytes, sample_rate: int) -> np.ndarray:
        """Convert raw audio bytes to numpy array."""
        # Try to parse as WAV first
        try:
            with io.BytesIO(audio_bytes) as f:
                with wave.open(f, 'rb') as wav:
                    frames = wav.readframes(wav.getnframes())
                    audio = np.frombuffer(frames, dtype=np.int16)
                    return audio.astype(np.float32) / 32768.0
        except Exception:
            pass

        # Assume raw PCM 16-bit
        audio = np.frombuffer(audio_bytes, dtype=np.int16)
        return audio.astype(np.float32) / 32768.0

    def transcribe_sync(
        self,
        audio_data: Union[bytes, np.ndarray],
        sample_rate: int = 16000
    ) -> str:
        """Synchronous transcription (for non-async contexts)."""
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            self.transcribe(audio_data, sample_rate)
        )

    async def transcribe_async(
        self,
        audio_data: Union[bytes, np.ndarray],
        sample_rate: int = 16000
    ) -> str:
        """Alias for transcribe method."""
        return await self.transcribe(audio_data, sample_rate)


# Global instance
stt = SpeechToText()
