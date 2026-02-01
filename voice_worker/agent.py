import asyncio
import httpx
import io
import json
import logging
import wave
import numpy as np
import time
from typing import Optional, Set

import websockets
from livekit import rtc

from .stt import stt
from .config import get_voice_settings

# Import TTS based on config
settings = get_voice_settings()
if settings.tts_backend == "kokoro":
    from .tts_kokoro import kokoro_tts_instance as tts
elif settings.tts_backend == "edge":
    from .tts_edge import edge_tts_instance as tts
else:
    from .tts import tts

logger = logging.getLogger("voice_worker.agent")

# Audio settings
SAMPLE_RATE = 48000  # LiveKit default
CHANNELS = 1
BYTES_PER_SAMPLE = 2  # 16-bit audio
WHISPER_SAMPLE_RATE = 16000  # Whisper expects 16kHz


class DealershipVoiceAgent:
    """
    LiveKit Voice Agent for car dealership.

    Handles audio I/O, VAD, STT, and TTS.
    """

    def __init__(self):
        self.session_id: Optional[str] = None
        self.http_client: Optional[httpx.AsyncClient] = None
        self.room: Optional[rtc.Room] = None
        self.audio_source: Optional[rtc.AudioSource] = None
        self.local_participant: Optional[rtc.LocalParticipant] = None

        # Audio processing state
        self.is_speaking = False
        self.speech_buffer: list[bytes] = []
        self.is_user_speaking = False
        self.silence_frames = 0
        self.speech_frames = 0

        # Barge-in (user interruption) support
        self._interrupt_speaking = False
        self._barge_in_frames = 0  # Count frames of speech during agent talking

        # VAD settings (tuned for natural speech with pauses)
        self.vad_threshold = 0.012  # Energy threshold for speech detection (lowered)
        self.min_speech_frames = 5  # Min frames to consider as speech
        self.min_silence_frames = 60  # Frames of silence to end speech (~1.2 seconds)
        self.barge_in_frames = 8  # Frames needed to trigger barge-in (~160ms of speech)

        # State management
        self._running = False
        self._audio_streams: Set[rtc.AudioStream] = set()
        self._audio_tasks: Set[asyncio.Task] = set()
        self._ws_task: Optional[asyncio.Task] = None

    async def initialize(self):
        """Initialize the agent."""
        # Models may already be preloaded, but ensure they're ready
        if not stt._loaded:
            stt.load_model()
        if not tts._loaded:
            tts.load_model()

        self.http_client = httpx.AsyncClient(
            base_url=settings.app_api_url,
            timeout=60.0  # Increased timeout for LLM responses
        )
        logger.info("Voice agent initialized")

    def stop(self):
        """Signal the agent to stop."""
        self._running = False

    async def cleanup(self):
        """Cleanup resources."""
        self._running = False

        # Cancel WebSocket listener
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        self._ws_task = None

        # Close all audio streams
        for stream in self._audio_streams:
            try:
                await stream.aclose()
            except Exception as e:
                logger.warning(f"Error closing audio stream: {e}")
        self._audio_streams.clear()

        # Cancel all audio processing tasks
        for task in self._audio_tasks:
            if not task.done():
                task.cancel()
        self._audio_tasks.clear()

        # Close HTTP client
        if self.http_client:
            await self.http_client.aclose()
            self.http_client = None

        logger.info("Voice agent cleaned up")

    async def run(self, ctx):
        """Run the agent in the room context."""
        self.room = ctx.room
        self.session_id = ctx.room.name
        self.local_participant = ctx.room.local_participant
        self._running = True

        logger.info(f"Agent running in room: {self.session_id}")

        # Create session in app backend
        try:
            response = await self.http_client.post(
                "/api/sessions",
                json={"session_id": self.session_id}
            )
            response.raise_for_status()
            logger.info(f"Session created: {self.session_id}")
        except Exception as e:
            logger.error(f"Failed to create session: {e}")

        # Set up audio source for TTS output
        self.audio_source = rtc.AudioSource(SAMPLE_RATE, CHANNELS)
        track = rtc.LocalAudioTrack.create_audio_track("agent-voice", self.audio_source)

        options = rtc.TrackPublishOptions()
        options.source = rtc.TrackSource.SOURCE_MICROPHONE
        await self.local_participant.publish_track(track, options)
        logger.info("Published agent audio track")

        # Wait a moment for connection to stabilize
        await asyncio.sleep(0.5)

        # Send greeting
        await self.speak("Hello! Welcome to Springfield Auto. How can I help you today?")

        # Start WebSocket listener for real-time notifications
        self._ws_task = asyncio.create_task(self._listen_for_notifications())

        # Keep running until stopped
        while self._running:
            await asyncio.sleep(0.5)

    async def _listen_for_notifications(self):
        """Listen for real-time notifications via WebSocket."""
        # Build WebSocket URL from HTTP URL
        ws_url = settings.app_api_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/ws/{self.session_id}"

        logger.info(f"Connecting to WebSocket for notifications: {ws_url}")

        while self._running:
            try:
                async with websockets.connect(ws_url) as ws:
                    logger.info("WebSocket connected for notifications")

                    while self._running:
                        try:
                            # Wait for message with timeout
                            message = await asyncio.wait_for(ws.recv(), timeout=30.0)
                            data = json.loads(message)

                            # Handle notification messages
                            if data.get("type") == "notification":
                                notification_msg = data.get("message", "")
                                if notification_msg:
                                    logger.info(f"Received notification: {notification_msg[:50]}...")
                                    # Speak the notification to the user
                                    await self.speak(notification_msg)

                            # Handle heartbeat
                            elif data.get("type") == "heartbeat":
                                await ws.send(json.dumps({"type": "ping"}))

                        except asyncio.TimeoutError:
                            # Send ping to keep connection alive
                            try:
                                await ws.send(json.dumps({"type": "ping"}))
                            except Exception:
                                break

            except asyncio.CancelledError:
                logger.info("WebSocket listener cancelled")
                break
            except Exception as e:
                if self._running:
                    logger.warning(f"WebSocket connection error: {e}, reconnecting...")
                    await asyncio.sleep(2)  # Wait before reconnecting

        logger.info("WebSocket listener stopped")

    async def process_audio_track(self, track: rtc.Track):
        """
        Process incoming audio track for speech detection.

        This is called from main.py when a user's audio track is subscribed.
        """
        logger.info(f"Starting audio processing for track: {track.sid}")

        audio_stream = rtc.AudioStream(track)
        self._audio_streams.add(audio_stream)

        try:
            async for frame_event in audio_stream:
                if not self._running:
                    break

                frame = frame_event.frame
                await self._process_audio_frame(frame)

        except asyncio.CancelledError:
            logger.info("Audio processing cancelled")
        except Exception as e:
            logger.error(f"Error processing audio track: {e}", exc_info=True)
        finally:
            # Cleanup
            self._audio_streams.discard(audio_stream)
            try:
                await audio_stream.aclose()
            except Exception:
                pass
            logger.info(f"Audio processing ended for track: {track.sid}")

    async def _process_audio_frame(self, frame: rtc.AudioFrame):
        """Process a single audio frame for VAD."""
        audio_data = np.frombuffer(frame.data, dtype=np.int16)

        # Calculate RMS energy (normalized)
        energy = np.sqrt(np.mean(audio_data.astype(np.float32) ** 2)) / 32768.0

        if energy > self.vad_threshold:
            self.speech_frames += 1
            self.silence_frames = 0

            # Barge-in detection: if agent is speaking and user talks over
            if self.is_speaking:
                self._barge_in_frames += 1
                if self._barge_in_frames >= self.barge_in_frames:
                    if not self._interrupt_speaking:  # Only log once
                        logger.info(f"🛑 BARGE-IN detected! User interrupting agent (energy: {energy:.4f})")
                    self._interrupt_speaking = True
                # Buffer the audio even during barge-in
                if not self.is_user_speaking:
                    self.is_user_speaking = True
                    self.speech_buffer = []
                self.speech_buffer.append(frame.data)
                return  # Skip normal VAD processing while agent is stopping

            if self.speech_frames >= self.min_speech_frames:
                if not self.is_user_speaking:
                    self.is_user_speaking = True
                    self.speech_buffer = []
                    logger.info(f"User started speaking (energy: {energy:.4f})")

                # Buffer the audio
                self.speech_buffer.append(frame.data)
        else:
            self.silence_frames += 1
            self._barge_in_frames = 0  # Reset barge-in counter on silence

            if self.is_user_speaking:
                # Still buffer during short silences
                self.speech_buffer.append(frame.data)

                if self.silence_frames >= self.min_silence_frames:
                    # End of speech detected
                    self.is_user_speaking = False
                    self.speech_frames = 0
                    logger.info("User stopped speaking")

                    # Process the buffered speech
                    if self.speech_buffer:
                        audio_bytes = b''.join(self.speech_buffer)
                        self.speech_buffer = []

                        # Create task and track it
                        task = asyncio.create_task(
                            self._handle_user_speech(audio_bytes, frame.sample_rate)
                        )
                        self._audio_tasks.add(task)
                        task.add_done_callback(self._audio_tasks.discard)

    async def _handle_user_speech(self, audio_data: bytes, sample_rate: int):
        """Process user speech through STT and get response with latency tracking."""
        total_start = time.time()
        latency = {}

        # Wait briefly for any barge-in to complete stopping the agent
        if self.is_speaking:
            logger.info("Waiting for agent to stop speaking after barge-in...")
            for _ in range(20):  # Wait up to 400ms
                if not self.is_speaking:
                    break
                await asyncio.sleep(0.02)

        # Convert raw bytes to numpy array
        audio_np = np.frombuffer(audio_data, dtype=np.int16)

        # Check minimum audio length (at least 0.3 seconds)
        min_samples = int(sample_rate * 0.3)
        if len(audio_np) < min_samples:
            logger.info(f"Audio too short ({len(audio_np)} samples), ignoring")
            return

        # Check audio level - reject if too quiet (likely silence/noise)
        audio_float = audio_np.astype(np.float32) / 32768.0
        rms_energy = np.sqrt(np.mean(audio_float ** 2))
        if rms_energy < 0.005:  # Very quiet threshold
            logger.info(f"Audio too quiet (RMS: {rms_energy:.4f}), ignoring")
            return

        logger.info(f"Audio RMS energy: {rms_energy:.4f}")

        # Resample if needed (48kHz -> 16kHz for Whisper)
        if sample_rate != WHISPER_SAMPLE_RATE:
            logger.info(f"Resampling audio from {sample_rate}Hz to {WHISPER_SAMPLE_RATE}Hz")

            # Use proper decimation for 48kHz -> 16kHz (factor of 3)
            # This is more accurate than linear interpolation
            downsample_factor = sample_rate // WHISPER_SAMPLE_RATE  # 48000/16000 = 3

            if sample_rate == 48000 and WHISPER_SAMPLE_RATE == 16000:
                # Exact 3x downsampling - use averaging for anti-aliasing
                audio_float = audio_np.astype(np.float32)

                # Simple low-pass filter before downsampling (moving average)
                kernel_size = 3
                if len(audio_float) >= kernel_size:
                    kernel = np.ones(kernel_size) / kernel_size
                    audio_float = np.convolve(audio_float, kernel, mode='same')

                # Decimate by taking every 3rd sample
                new_length = len(audio_float) // downsample_factor
                audio_np = audio_float[:new_length * downsample_factor:downsample_factor].astype(np.int16)
            else:
                # Fallback to interpolation for non-standard rates
                ratio = WHISPER_SAMPLE_RATE / sample_rate
                new_length = int(len(audio_np) * ratio)
                indices = np.linspace(0, len(audio_np) - 1, new_length)
                audio_np = np.interp(
                    indices,
                    np.arange(len(audio_np)),
                    audio_np.astype(np.float32)
                ).astype(np.int16)

            sample_rate = WHISPER_SAMPLE_RATE

        # Convert to WAV format for STT
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav:
            wav.setnchannels(CHANNELS)
            wav.setsampwidth(BYTES_PER_SAMPLE)
            wav.setframerate(sample_rate)
            wav.writeframes(audio_np.tobytes())

        wav_bytes = wav_buffer.getvalue()
        audio_duration = len(audio_np) / sample_rate
        latency["audio_duration"] = round(audio_duration * 1000)  # ms

        logger.info(f"Audio prepared: {len(audio_np)} samples at {sample_rate}Hz ({audio_duration:.2f}s)")

        # === STT ===
        stt_start = time.time()
        logger.info("Transcribing...")
        try:
            text = await stt.transcribe_async(wav_bytes)
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return
        latency["stt_ms"] = round((time.time() - stt_start) * 1000)

        if not text or not text.strip():
            logger.info("No speech detected in transcription")
            return

        # Filter out Whisper hallucinations (common patterns when audio is unclear)
        hallucination_patterns = [
            "you may as well",
            "thank you for watching",
            "please subscribe",
            "thanks for watching",
            "see you next time",
            "music playing",
            "[music]",
            "...",
            "___",
        ]
        text_lower = text.lower().strip()
        if any(pattern in text_lower for pattern in hallucination_patterns) or len(text_lower) < 3:
            logger.warning(f"Detected likely hallucination, ignoring: '{text}'")
            return

        # Also filter if text is mostly underscores or punctuation
        alpha_count = sum(1 for c in text if c.isalpha())
        if alpha_count < 3:
            logger.warning(f"Text has too few letters ({alpha_count}), ignoring: '{text}'")
            return

        logger.info(f"User said: {text} [STT: {latency['stt_ms']}ms]")

        # === LLM ===
        llm_start = time.time()
        try:
            response = await self.http_client.post(
                "/api/chat",
                json={
                    "session_id": self.session_id,
                    "message": text
                }
            )
            response.raise_for_status()
            data = response.json()
            latency["llm_ms"] = round((time.time() - llm_start) * 1000)

            agent_response = data.get("response", "I'm sorry, I didn't understand that.")
            logger.info(f"Agent response: {agent_response} [LLM: {latency['llm_ms']}ms]")

            # === TTS ===
            tts_start = time.time()
            await self.speak(agent_response)
            latency["tts_ms"] = round((time.time() - tts_start) * 1000)

            # Total latency
            latency["total_ms"] = round((time.time() - total_start) * 1000)

            # Log latency summary
            logger.info(f"📊 LATENCY: STT={latency['stt_ms']}ms | LLM={latency['llm_ms']}ms | TTS={latency['tts_ms']}ms | TOTAL={latency['total_ms']}ms")

            # Send latency to backend for frontend display
            try:
                await self.http_client.post(
                    "/api/latency",
                    json={
                        "session_id": self.session_id,
                        "latency": latency,
                        "user_message": text,
                        "agent_response": agent_response[:100]
                    }
                )
            except Exception:
                pass  # Non-critical

        except Exception as e:
            logger.error(f"Error getting response: {e}")
            await self.speak("I'm having trouble processing your request. Please try again.")

    async def speak(self, text: str):
        """Synthesize and play TTS audio with mutex to prevent overlap and barge-in support."""
        if not text.strip():
            return

        # Use a lock to prevent concurrent speech
        if not hasattr(self, '_speak_lock'):
            self._speak_lock = asyncio.Lock()

        async with self._speak_lock:
            # Check if audio source is valid
            if not self.audio_source or not self._running:
                logger.warning("Audio source not available, skipping speech")
                return

            # Reset interrupt flag before speaking
            self._interrupt_speaking = False
            self._barge_in_frames = 0

            self.is_speaking = True
            logger.info(f"Speaking: {text[:50]}...")

            try:
                # Synthesize audio
                wav_bytes = await tts.synthesize_async(text)

                if not wav_bytes:
                    logger.warning("TTS returned empty audio")
                    return

                # Parse WAV and get raw audio
                with io.BytesIO(wav_bytes) as wav_buffer:
                    with wave.open(wav_buffer, 'rb') as wav:
                        tts_sample_rate = wav.getframerate()
                        audio_data = wav.readframes(wav.getnframes())

                # Convert to numpy
                audio_np = np.frombuffer(audio_data, dtype=np.int16)

                # Resample if needed (TTS is typically 22050Hz or 24000Hz, LiveKit wants 48000Hz)
                if tts_sample_rate != SAMPLE_RATE:
                    ratio = SAMPLE_RATE / tts_sample_rate
                    new_length = int(len(audio_np) * ratio)
                    indices = np.floor(np.arange(new_length) / ratio).astype(int)
                    indices = np.clip(indices, 0, len(audio_np) - 1)
                    audio_np = audio_np[indices]

                # Send in chunks (20ms frames)
                samples_per_frame = SAMPLE_RATE // 50  # 20ms = 960 samples at 48kHz
                was_interrupted = False

                for i in range(0, len(audio_np), samples_per_frame):
                    if not self._running:
                        break

                    # Check for barge-in (user interruption)
                    if self._interrupt_speaking:
                        logger.info("🛑 Speech interrupted by user barge-in")
                        was_interrupted = True
                        break

                    chunk = audio_np[i:i + samples_per_frame]
                    if len(chunk) < samples_per_frame:
                        # Pad last chunk with silence
                        chunk = np.pad(chunk, (0, samples_per_frame - len(chunk)))

                    frame = rtc.AudioFrame(
                        data=chunk.tobytes(),
                        sample_rate=SAMPLE_RATE,
                        num_channels=CHANNELS,
                        samples_per_channel=samples_per_frame,
                    )

                    try:
                        await self.audio_source.capture_frame(frame)
                    except Exception as frame_error:
                        if "InvalidState" in str(frame_error):
                            logger.warning("Audio source disconnected, stopping speech")
                            break
                        raise

                if was_interrupted:
                    logger.info("Agent speech stopped due to barge-in")

                    # Small delay to maintain proper playback rate
                    await asyncio.sleep(0.018)  # ~20ms

            except Exception as e:
                logger.error(f"Error speaking: {e}", exc_info=True)
            finally:
                self.is_speaking = False


def create_agent():
    """Factory function to create agent instance."""
    return DealershipVoiceAgent()
