"""
Audio Processor - STT and TTS using local models.

As specified in CLAUDE.md:
- STT: Faster-Whisper (local, GPU-accelerated)
- TTS: Kokoro-82M (local GPU, <2GB VRAM)

These run locally for:
- Lower latency (no network roundtrip)
- No API costs
- Better privacy
"""
import io
import os
import logging
import asyncio
from typing import Optional
from concurrent.futures import ThreadPoolExecutor
import numpy as np

logger = logging.getLogger("app.services.audio")

# Thread pool for CPU/GPU-bound operations
_executor = ThreadPoolExecutor(max_workers=2)

# Model configuration (from CLAUDE.md)
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "medium")  # medium for best accuracy
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cuda")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")  # INT8 for memory efficiency

KOKORO_VOICE = os.getenv("KOKORO_VOICE", "af_heart")  # Warm, friendly female voice
KOKORO_LANG = os.getenv("KOKORO_LANG", "a")  # 'a' = American English

# Whisper context prompt for better accuracy in car dealership domain
WHISPER_PROMPT = """Car dealership customer service conversation. The customer is speaking about:
test drive, oil change, brake service, tire rotation, appointment, schedule, booking.
Vehicle brands: Honda, Toyota, Ford, Chevrolet, BMW, Mercedes, Volkswagen.
Common phrases: I want to book, I'd like to schedule, test drive please, tomorrow, next week."""


class AudioProcessor:
    """
    Audio processing using local models (Faster-Whisper + Kokoro).

    As per CLAUDE.md:
    - STT: Faster-Whisper (4x faster than OpenAI, runs locally with GPU)
    - TTS: Kokoro-82M (lightweight neural TTS, high quality, <2GB VRAM)
    """

    def __init__(self):
        self._stt = None
        self._tts = None
        self._stt_loaded = False
        self._tts_loaded = False
        self._tts_sample_rate = 24000  # Kokoro outputs 24kHz

    def _load_stt(self):
        """Load Faster-Whisper model."""
        if self._stt_loaded:
            return

        try:
            from faster_whisper import WhisperModel

            logger.info(f"[STT] Loading Faster-Whisper: model={WHISPER_MODEL}, device={WHISPER_DEVICE}")

            self._stt = WhisperModel(
                WHISPER_MODEL,
                device=WHISPER_DEVICE,
                compute_type=WHISPER_COMPUTE_TYPE
            )
            self._stt_loaded = True
            logger.info("[STT] Faster-Whisper loaded successfully")

        except Exception as e:
            logger.error(f"[STT] Failed to load Faster-Whisper: {e}")
            self._stt_loaded = True  # Don't retry
            raise

    def _load_tts(self):
        """Load Kokoro TTS model."""
        if self._tts_loaded:
            return

        try:
            from kokoro import KPipeline

            logger.info(f"[TTS] Loading Kokoro: voice={KOKORO_VOICE}, lang={KOKORO_LANG}")

            self._tts = KPipeline(lang_code=KOKORO_LANG)
            self._tts_loaded = True
            logger.info("[TTS] Kokoro loaded successfully")

        except Exception as e:
            logger.error(f"[TTS] Failed to load Kokoro: {e}")
            self._tts_loaded = True  # Don't retry
            raise

    async def transcribe(self, audio_data: bytes, format: str = "wav") -> Optional[str]:
        """
        Transcribe audio to text using Faster-Whisper.

        Args:
            audio_data: Raw audio bytes (WAV format, 16kHz preferred)
            format: Audio format hint

        Returns:
            Transcribed text or None on error
        """
        if not audio_data or len(audio_data) < 1000:
            logger.warning("[STT] Audio data too short for transcription")
            return None

        # Lazy load model
        if not self._stt_loaded:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(_executor, self._load_stt)

        if self._stt is None:
            logger.error("[STT] Model not available")
            return None

        try:
            # Convert bytes to numpy array
            audio_array = self._bytes_to_numpy(audio_data)

            # Run transcription in thread pool
            loop = asyncio.get_event_loop()

            def _transcribe():
                segments, info = self._stt.transcribe(
                    audio_array,
                    language="en",
                    initial_prompt=WHISPER_PROMPT,
                    beam_size=5,
                    best_of=3,
                    temperature=0.0,
                    vad_filter=True,
                    vad_parameters=dict(
                        min_silence_duration_ms=300,
                        speech_pad_ms=250,
                        threshold=0.5,
                        min_speech_duration_ms=100
                    )
                )
                return " ".join(segment.text.strip() for segment in segments)

            text = await loop.run_in_executor(_executor, _transcribe)
            text = text.strip()

            if text:
                logger.info(f"[STT] Transcribed: '{text[:100]}...'")
            else:
                logger.warning("[STT] Empty transcription result")

            return text if text else None

        except Exception as e:
            logger.error(f"[STT] Transcription error: {e}")
            return None

    async def synthesize(self, text: str, voice: str = None) -> Optional[bytes]:
        """
        Synthesize text to speech using Kokoro.

        Args:
            text: Text to synthesize
            voice: Voice override (default: KOKORO_VOICE from env)

        Returns:
            Audio bytes (MP3 format for Twilio compatibility) or None on error
        """
        if not text:
            return None

        # Lazy load model
        if not self._tts_loaded:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(_executor, self._load_tts)

        if self._tts is None:
            logger.error("[TTS] Model not available")
            return None

        voice = voice or KOKORO_VOICE

        try:
            loop = asyncio.get_event_loop()

            def _synthesize():
                # Generate audio using Kokoro
                audio_chunks = []
                for _, _, audio in self._tts(text, voice=voice):
                    if audio is not None:
                        audio_chunks.append(audio)

                if not audio_chunks:
                    logger.warning("[TTS] Kokoro returned no audio")
                    return None

                # Concatenate all chunks
                full_audio = np.concatenate(audio_chunks)

                # Convert float32 to int16
                audio_int16 = (full_audio * 32767).astype(np.int16)

                # Create WAV
                import wave
                wav_buffer = io.BytesIO()
                with wave.open(wav_buffer, 'wb') as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)  # 16-bit
                    wav.setframerate(self._tts_sample_rate)
                    wav.writeframes(audio_int16.tobytes())

                wav_data = wav_buffer.getvalue()

                # Convert to MP3 for Twilio compatibility
                from pydub import AudioSegment
                audio_segment = AudioSegment.from_wav(io.BytesIO(wav_data))
                mp3_buffer = io.BytesIO()
                audio_segment.export(mp3_buffer, format="mp3", bitrate="64k")
                return mp3_buffer.getvalue()

            audio = await loop.run_in_executor(_executor, _synthesize)

            if audio:
                logger.info(f"[TTS] Synthesized: '{text[:50]}...' ({len(audio)} bytes)")

            return audio

        except Exception as e:
            logger.error(f"[TTS] Synthesis error: {e}")
            return None

    def _bytes_to_numpy(self, audio_bytes: bytes) -> np.ndarray:
        """Convert audio bytes to float32 numpy array for Whisper."""
        import wave

        try:
            # Try to parse as WAV
            with io.BytesIO(audio_bytes) as f:
                with wave.open(f, 'rb') as wav:
                    frames = wav.readframes(wav.getnframes())
                    audio = np.frombuffer(frames, dtype=np.int16)
                    return audio.astype(np.float32) / 32768.0
        except Exception:
            # Assume raw PCM 16-bit
            audio = np.frombuffer(audio_bytes, dtype=np.int16)
            return audio.astype(np.float32) / 32768.0

    async def preload(self):
        """
        Preload both STT and TTS models at startup.

        This should be called during app initialization to avoid
        latency on the first voice call.
        """
        logger.info("[Audio] Preloading models...")

        loop = asyncio.get_event_loop()

        # Load both models in parallel using thread pool
        stt_future = loop.run_in_executor(_executor, self._load_stt)
        tts_future = loop.run_in_executor(_executor, self._load_tts)

        # Wait for both to complete
        try:
            await asyncio.gather(stt_future, tts_future)
            logger.info("[Audio] All models preloaded successfully")
        except Exception as e:
            logger.error(f"[Audio] Model preload failed: {e}")
            # Don't raise - allow app to start, models will retry on first use

    async def close(self):
        """Cleanup resources."""
        pass  # Models stay loaded for reuse


# Global instance
audio_processor = AudioProcessor()
