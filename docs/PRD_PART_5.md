# Car Dealership Voice Agent - PRD Part 5 of 6
## Voice Worker (STT/TTS/LiveKit)

---

# SECTION 1: VOICE WORKER OVERVIEW

## 1.1 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      VOICE WORKER                                │
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │   LiveKit    │    │    Agent     │    │     App      │      │
│  │    Room      │◄──►│   Handler    │◄──►│     API      │      │
│  └──────┬───────┘    └──────────────┘    └──────────────┘      │
│         │                   │                                    │
│         │            ┌──────┴──────┐                            │
│         │            │             │                            │
│         ▼            ▼             ▼                            │
│  ┌──────────────┐  ┌─────────┐  ┌─────────┐                    │
│  │    Audio     │  │   STT   │  │   TTS   │                    │
│  │   Stream     │  │ Whisper │  │  Piper  │                    │
│  └──────────────┘  └─────────┘  └─────────┘                    │
└─────────────────────────────────────────────────────────────────┘
```

## 1.2 Flow

```
1. User speaks → LiveKit captures audio
2. VAD detects speech end → Audio sent to STT
3. STT transcribes → Text sent to App API
4. App processes (LangGraph) → Response text returned
5. TTS synthesizes → Audio stream
6. Audio sent to LiveKit → User hears response
```

---

# SECTION 2: STT (SPEECH-TO-TEXT)

## 2.1 voice_worker/stt.py

```python
import numpy as np
from typing import Optional, Union
from pathlib import Path
import io
import wave
import struct

from faster_whisper import WhisperModel

from .config import get_voice_settings

settings = get_voice_settings()


class SpeechToText:
    """
    Speech-to-Text using Faster Whisper.
    
    Faster Whisper is a reimplementation of OpenAI's Whisper
    using CTranslate2, which is 4x faster with lower memory usage.
    """
    
    def __init__(self):
        self.model: Optional[WhisperModel] = None
        self._model_loaded = False
    
    def load_model(self):
        """Load the Whisper model."""
        if self._model_loaded:
            return
        
        print(f"Loading Whisper model: {settings.whisper_model}")
        print(f"Device: {settings.whisper_device}")
        
        # Determine compute type based on device
        if settings.whisper_device == "cuda":
            compute_type = "float16"
        else:
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
        
        # Transcribe
        segments, info = self.model.transcribe(
            audio_array,
            language="en",
            beam_size=5,
            best_of=5,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=500,
                speech_pad_ms=200
            )
        )
        
        # Combine segments
        text = " ".join(segment.text.strip() for segment in segments)
        
        return text.strip()
    
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


# Global instance
stt = SpeechToText()
```

---

# SECTION 3: TTS (TEXT-TO-SPEECH)

## 3.1 voice_worker/tts.py

```python
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
```

---

# SECTION 4: VOICE WORKER CONFIGURATION

## 4.1 voice_worker/config.py

```python
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
    whisper_model: str = Field(default="base")
    whisper_device: str = Field(default="cpu")
    
    # Piper TTS
    piper_voice: str = Field(default="en_US-amy-medium")
    
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
```

---

# SECTION 5: LIVEKIT AGENT

## 5.1 voice_worker/agent.py

```python
import asyncio
import httpx
from typing import Optional
from datetime import datetime

from livekit import agents, rtc
from livekit.agents import (
    AgentSession,
    Agent,
    RoomInputOptions,
    RunContext,
    function_tool,
    llm,
)
from livekit.agents.voice import AgentOutput, AgentInput
from livekit.plugins import silero

from .stt import stt
from .tts import tts
from .config import get_voice_settings

settings = get_voice_settings()


class DealershipVoiceAgent:
    """
    LiveKit Voice Agent for car dealership.
    
    Handles:
    - Audio input/output via LiveKit
    - VAD (Voice Activity Detection)
    - STT transcription
    - Communication with main app API
    - TTS synthesis and playback
    """
    
    def __init__(self):
        self.session_id: Optional[str] = None
        self.http_client: Optional[httpx.AsyncClient] = None
        self.is_speaking = False
        self.current_audio_task: Optional[asyncio.Task] = None
    
    async def initialize(self):
        """Initialize the agent."""
        # Load models
        stt.load_model()
        tts.load_model()
        
        # Create HTTP client
        self.http_client = httpx.AsyncClient(
            base_url=settings.app_api_url,
            timeout=30.0
        )
        
        print("Voice agent initialized")
    
    async def cleanup(self):
        """Cleanup resources."""
        if self.http_client:
            await self.http_client.aclose()
    
    async def on_room_connected(self, room: rtc.Room):
        """Called when connected to LiveKit room."""
        self.session_id = room.name
        print(f"Connected to room: {self.session_id}")
        
        # Create session in app
        try:
            response = await self.http_client.post(
                "/api/sessions",
                json={"session_id": self.session_id}
            )
            response.raise_for_status()
        except Exception as e:
            print(f"Failed to create session: {e}")
        
        # Play greeting
        await self.speak("Hello! Welcome to Springfield Auto. How can I help you today?")
    
    async def on_user_speech(self, audio_data: bytes):
        """
        Called when user finishes speaking (VAD detected end).
        
        Args:
            audio_data: Complete utterance audio
        """
        # Transcribe
        print("Transcribing user speech...")
        text = await stt.transcribe(audio_data)
        
        if not text.strip():
            print("No speech detected")
            return
        
        print(f"User said: {text}")
        
        # Send to app API
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
            
            agent_response = data.get("response", "I'm sorry, I didn't catch that.")
            print(f"Agent response: {agent_response}")
            
            # Speak response
            await self.speak(agent_response)
            
        except Exception as e:
            print(f"Error processing message: {e}")
            await self.speak("I'm having some trouble right now. Could you please try again?")
    
    async def speak(self, text: str):
        """
        Synthesize and play speech.
        
        Args:
            text: Text to speak
        """
        if not text.strip():
            return
        
        self.is_speaking = True
        
        try:
            # Synthesize audio
            audio_bytes = await tts.synthesize_async(text)
            
            # Publish to LiveKit room
            if self.current_audio_task:
                self.current_audio_task.cancel()
            
            self.current_audio_task = asyncio.create_task(
                self._publish_audio(audio_bytes)
            )
            await self.current_audio_task
            
        except asyncio.CancelledError:
            print("Speech interrupted")
        except Exception as e:
            print(f"Error speaking: {e}")
        finally:
            self.is_speaking = False
    
    async def _publish_audio(self, audio_bytes: bytes):
        """Publish audio to LiveKit room."""
        # This would use LiveKit's audio publishing API
        # Implementation depends on room reference
        pass
    
    async def interrupt(self):
        """Interrupt current speech (user barged in)."""
        if self.current_audio_task:
            self.current_audio_task.cancel()
            self.is_speaking = False
            print("Speech interrupted by user")


# ============================================
# LiveKit Agents SDK Integration
# ============================================

class DealershipAgentWorker(Agent):
    """
    LiveKit Agents SDK compatible worker.
    
    This integrates with the livekit-agents framework
    for production deployment.
    """
    
    def __init__(self):
        super().__init__()
        self.agent = DealershipVoiceAgent()
        self._vad = silero.VAD.load()
    
    async def on_enter(self, ctx: RunContext):
        """Called when agent enters the room."""
        await self.agent.initialize()
        await self.agent.on_room_connected(ctx.room)
    
    async def on_exit(self, ctx: RunContext):
        """Called when agent exits the room."""
        await self.agent.cleanup()
    
    async def on_user_turn(self, ctx: RunContext, audio: AgentInput):
        """
        Called when user's turn is complete.
        
        Args:
            ctx: Run context
            audio: User's audio input
        """
        # Get audio data
        audio_data = audio.audio_bytes
        
        # Process
        await self.agent.on_user_speech(audio_data)
    
    async def on_agent_turn(self, ctx: RunContext) -> AgentOutput:
        """
        Called when it's agent's turn to speak.
        
        Returns:
            Agent's audio output
        """
        # This is handled by speak() method
        pass


def create_agent():
    """Factory function for LiveKit agents SDK."""
    return DealershipAgentWorker()
```

---

# SECTION 6: VOICE WORKER MAIN

## 6.1 voice_worker/main.py

```python
import asyncio
import logging
import signal
from typing import Optional

from livekit import agents
from livekit.agents import AgentSession, WorkerOptions

from .agent import create_agent, DealershipVoiceAgent
from .config import get_voice_settings
from .stt import stt
from .tts import tts

settings = get_voice_settings()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("voice_worker")


async def entrypoint(ctx: agents.JobContext):
    """
    Main entrypoint for LiveKit agent job.
    
    This is called by the LiveKit agents framework when
    a new room needs an agent.
    """
    logger.info(f"Agent job started for room: {ctx.room.name}")
    
    # Create and run agent
    agent = DealershipVoiceAgent()
    
    try:
        await agent.initialize()
        await agent.on_room_connected(ctx.room)
        
        # Keep agent running until room closes
        await ctx.wait_for_disconnect()
        
    except Exception as e:
        logger.error(f"Agent error: {e}")
    finally:
        await agent.cleanup()
        logger.info("Agent job completed")


async def preload_models():
    """Preload ML models at startup."""
    logger.info("Preloading models...")
    
    try:
        stt.load_model()
        logger.info("STT model loaded")
    except Exception as e:
        logger.error(f"Failed to load STT model: {e}")
    
    try:
        tts.load_model()
        logger.info("TTS model loaded")
    except Exception as e:
        logger.error(f"Failed to load TTS model: {e}")
    
    logger.info("Model preloading complete")


def main():
    """Main entry point for voice worker."""
    logger.info("Starting Voice Worker...")
    logger.info(f"LiveKit URL: {settings.livekit_url}")
    logger.info(f"App API URL: {settings.app_api_url}")
    logger.info(f"Whisper model: {settings.whisper_model}")
    logger.info(f"Piper voice: {settings.piper_voice}")
    
    # Preload models
    asyncio.get_event_loop().run_until_complete(preload_models())
    
    # Configure worker
    worker_options = WorkerOptions(
        entrypoint_fnc=entrypoint,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
        ws_url=settings.livekit_url,
    )
    
    # Run worker
    logger.info("Starting LiveKit agent worker...")
    agents.run_app(worker_options)


if __name__ == "__main__":
    main()
```

## 6.2 voice_worker/__init__.py

```python
from .stt import stt, SpeechToText
from .tts import tts, TextToSpeech
from .agent import DealershipVoiceAgent, create_agent
from .config import get_voice_settings

__all__ = [
    "stt",
    "SpeechToText",
    "tts", 
    "TextToSpeech",
    "DealershipVoiceAgent",
    "create_agent",
    "get_voice_settings",
]
```

---

# SECTION 7: SIMPLIFIED VOICE AGENT (Alternative)

## 7.1 voice_worker/simple_agent.py

This is a simpler implementation that doesn't require the full LiveKit agents SDK, useful for testing or simpler deployments.

```python
import asyncio
import httpx
import numpy as np
from typing import Optional, Callable, Awaitable
from dataclasses import dataclass
from datetime import datetime

from livekit import rtc

from .stt import stt
from .tts import tts
from .config import get_voice_settings

settings = get_voice_settings()


@dataclass
class AudioBuffer:
    """Buffer for collecting audio frames."""
    frames: list
    start_time: datetime
    sample_rate: int = 16000
    
    def add_frame(self, frame: bytes):
        self.frames.append(frame)
    
    def get_audio(self) -> bytes:
        return b"".join(self.frames)
    
    def get_numpy(self) -> np.ndarray:
        audio_bytes = self.get_audio()
        return np.frombuffer(audio_bytes, dtype=np.int16)
    
    def duration_seconds(self) -> float:
        total_samples = sum(len(f) // 2 for f in self.frames)  # 16-bit = 2 bytes
        return total_samples / self.sample_rate
    
    def clear(self):
        self.frames = []
        self.start_time = datetime.now()


class SimpleVoiceAgent:
    """
    Simplified voice agent using direct LiveKit SDK.
    
    This provides more control over audio handling
    without the agents framework abstraction.
    """
    
    def __init__(self):
        self.room: Optional[rtc.Room] = None
        self.audio_source: Optional[rtc.AudioSource] = None
        self.audio_track: Optional[rtc.LocalAudioTrack] = None
        
        self.session_id: Optional[str] = None
        self.http_client: Optional[httpx.AsyncClient] = None
        
        self.audio_buffer = AudioBuffer(frames=[], start_time=datetime.now())
        self.is_speaking = False
        self.is_listening = True
        
        # VAD state
        self.speech_started = False
        self.silence_frames = 0
        self.silence_threshold = 25  # ~500ms at 50fps
    
    async def connect(self, url: str, token: str):
        """Connect to LiveKit room."""
        self.room = rtc.Room()
        
        # Set up event handlers
        self.room.on("track_subscribed", self._on_track_subscribed)
        self.room.on("disconnected", self._on_disconnected)
        
        # Connect
        await self.room.connect(url, token)
        self.session_id = self.room.name
        
        # Create audio source for output
        self.audio_source = rtc.AudioSource(
            sample_rate=tts.sample_rate,
            num_channels=1
        )
        self.audio_track = rtc.LocalAudioTrack.create_audio_track(
            "agent-audio",
            self.audio_source
        )
        
        # Publish audio track
        await self.room.local_participant.publish_track(self.audio_track)
        
        # Initialize HTTP client
        self.http_client = httpx.AsyncClient(
            base_url=settings.app_api_url,
            timeout=30.0
        )
        
        # Create session
        await self.http_client.post(
            "/api/sessions",
            json={"session_id": self.session_id}
        )
        
        print(f"Connected to room: {self.session_id}")
        
        # Greeting
        await self.speak("Hello! Welcome to Springfield Auto. How can I help you today?")
    
    async def disconnect(self):
        """Disconnect from room."""
        if self.http_client:
            await self.http_client.aclose()
        if self.room:
            await self.room.disconnect()
    
    def _on_track_subscribed(
        self,
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant
    ):
        """Handle incoming audio track."""
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            audio_stream = rtc.AudioStream(track)
            asyncio.create_task(self._process_audio_stream(audio_stream))
    
    def _on_disconnected(self):
        """Handle disconnection."""
        print("Disconnected from room")
    
    async def _process_audio_stream(self, stream: rtc.AudioStream):
        """Process incoming audio frames with VAD."""
        async for frame_event in stream:
            if not self.is_listening:
                continue
            
            frame = frame_event.frame
            audio_data = frame.data.tobytes()
            
            # Simple energy-based VAD
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            energy = np.sqrt(np.mean(audio_array.astype(np.float32) ** 2))
            
            is_speech = energy > 500  # Threshold
            
            if is_speech:
                if not self.speech_started:
                    # Speech started
                    self.speech_started = True
                    self.audio_buffer = AudioBuffer(
                        frames=[],
                        start_time=datetime.now()
                    )
                    print("Speech started")
                
                self.audio_buffer.add_frame(audio_data)
                self.silence_frames = 0
                
            elif self.speech_started:
                # Potential end of speech
                self.silence_frames += 1
                self.audio_buffer.add_frame(audio_data)  # Include trailing silence
                
                if self.silence_frames >= self.silence_threshold:
                    # Speech ended
                    self.speech_started = False
                    print(f"Speech ended (duration: {self.audio_buffer.duration_seconds():.2f}s)")
                    
                    # Process the utterance
                    audio = self.audio_buffer.get_audio()
                    asyncio.create_task(self._process_utterance(audio))
    
    async def _process_utterance(self, audio_data: bytes):
        """Process a complete user utterance."""
        # Disable listening while processing
        self.is_listening = False
        
        try:
            # Transcribe
            text = await stt.transcribe(audio_data)
            
            if not text.strip():
                print("No speech detected in utterance")
                self.is_listening = True
                return
            
            print(f"User: {text}")
            
            # Get response from app
            response = await self.http_client.post(
                "/api/chat",
                json={
                    "session_id": self.session_id,
                    "message": text
                }
            )
            response.raise_for_status()
            data = response.json()
            
            agent_response = data.get("response", "I'm sorry, could you repeat that?")
            print(f"Agent: {agent_response}")
            
            # Speak response
            await self.speak(agent_response)
            
        except Exception as e:
            print(f"Error processing utterance: {e}")
            await self.speak("I'm having some trouble. Could you try again?")
        finally:
            self.is_listening = True
    
    async def speak(self, text: str):
        """Synthesize and play speech."""
        if not text.strip():
            return
        
        self.is_speaking = True
        
        try:
            # Synthesize in chunks for lower latency
            async for audio_chunk in tts.synthesize_stream_async(text):
                # Convert to AudioFrame
                audio_array = np.frombuffer(audio_chunk, dtype=np.int16)
                
                frame = rtc.AudioFrame(
                    data=audio_array.tobytes(),
                    sample_rate=tts.sample_rate,
                    num_channels=1,
                    samples_per_channel=len(audio_array)
                )
                
                await self.audio_source.capture_frame(frame)
                
        except Exception as e:
            print(f"Error speaking: {e}")
        finally:
            self.is_speaking = False
    
    async def interrupt(self):
        """Stop current speech."""
        self.is_speaking = False


async def run_simple_agent(room_name: str, token: str):
    """Run the simple voice agent."""
    agent = SimpleVoiceAgent()
    
    # Load models
    stt.load_model()
    tts.load_model()
    
    try:
        await agent.connect(settings.livekit_url, token)
        
        # Keep running
        while True:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        print("Shutting down...")
    finally:
        await agent.disconnect()
```

---

# SECTION 8: REQUIREMENTS & NOTES

## 8.1 Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 4 cores | 8+ cores |
| RAM | 8 GB | 16+ GB |
| GPU (for fast STT) | None | 8GB VRAM |
| Storage | 10 GB | 20+ GB |

## 8.2 Model Sizes

| Model | Size | Speed (CPU) | Speed (GPU) |
|-------|------|-------------|-------------|
| whisper-tiny | 75 MB | ~1x real-time | ~10x |
| whisper-base | 145 MB | ~0.5x real-time | ~8x |
| whisper-small | 488 MB | ~0.3x real-time | ~5x |
| whisper-medium | 1.5 GB | ~0.1x real-time | ~3x |
| whisper-large-v3 | 3 GB | Too slow | ~1.5x |

## 8.3 Latency Budget

| Stage | Target | Notes |
|-------|--------|-------|
| VAD detection | <50ms | Silero VAD |
| STT | <500ms | Depends on model/hardware |
| LangGraph | <500ms | Includes API calls |
| TTS | <200ms | Streaming helps |
| **Total** | **<1.2s** | Acceptable for voice |

---

**END OF PART 5**

Say "continue" to get Part 6: Frontend Dashboard & FastAPI Routes
