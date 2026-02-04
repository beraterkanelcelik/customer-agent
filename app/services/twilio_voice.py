"""
Twilio Voice Service - Complete voice conversation handling with Media Streams.

This service manages:
- Incoming voice calls with audio streaming
- AI conversation via custom STT/TTS (not Twilio's)
- Human escalation via Twilio Conference
- Real-time updates to web dashboard
"""
import logging
import asyncio
import base64
import json
import uuid
import audioop
from typing import Optional, Dict, Any, Callable, Awaitable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from collections import deque
from urllib.parse import quote

from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream, Dial, Conference

from app.config import get_settings
from app.services.audio_processor import audio_processor
from app.services.conversation import conversation_service

settings = get_settings()
logger = logging.getLogger("app.services.twilio_voice")


class CallState(str, Enum):
    """Call state tracking."""
    CONNECTING = "connecting"
    AI_CONVERSATION = "ai_conversation"
    PROCESSING = "processing"
    ESCALATING = "escalating"
    IN_CONFERENCE = "in_conference"
    ENDED = "ended"


class HumanCallStatus(str, Enum):
    """Status of the outbound call to human agent."""
    NONE = "none"
    CALLING = "calling"
    RINGING = "ringing"
    WAITING_CONFIRMATION = "waiting_confirmation"  # Call connected, waiting for human to press 1
    CONFIRMED = "confirmed"  # Human pressed 1, ready to transfer
    IN_CONFERENCE = "in_conference"  # Customer transferred to conference
    FAILED = "failed"
    COMPLETED = "completed"


@dataclass
class ActiveCall:
    """Tracks an active call session."""
    call_sid: str
    session_id: str
    stream_sid: Optional[str] = None
    state: CallState = CallState.CONNECTING
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    conference_name: Optional[str] = None
    human_call_sid: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    # Audio buffering for STT
    audio_buffer: bytes = field(default_factory=bytes)
    silence_frames: int = 0
    is_speaking: bool = False
    # Transcript for dashboard
    transcript: list = field(default_factory=list)
    # Human escalation tracking (customer stays with AI until human ready)
    human_call_status: HumanCallStatus = HumanCallStatus.NONE
    escalation_reason: Optional[str] = None
    escalation_return_reason: Optional[str] = None  # Reason for returning from escalation
    human_status_message: Optional[str] = None  # Status message for AI to relay
    # Event queue for real-time notifications (barge-in support)
    pending_events: deque = field(default_factory=deque)
    # Audio playback tracking (for barge-in)
    is_playing_audio: bool = False
    barge_in_requested: bool = False


class TwilioVoiceService:
    """
    Twilio Voice Service with Media Streams for custom STT/TTS.

    Flow:
    1. Customer calls -> <Connect><Stream> starts WebSocket
    2. Audio streamed to our server -> STT transcribes
    3. LLM processes -> TTS generates response
    4. Audio streamed back to Twilio
    5. Real-time updates to web dashboard
    """

    # VAD settings
    SILENCE_THRESHOLD = 500  # Audio energy threshold
    MIN_SILENCE_FRAMES = 30  # ~600ms of silence to end utterance
    MIN_SPEECH_FRAMES = 5   # ~100ms to confirm speech
    SAMPLE_RATE = 8000      # Twilio uses 8kHz mulaw

    def __init__(self):
        self._client = None
        self._active_calls: Dict[str, ActiveCall] = {}  # call_sid -> ActiveCall
        self._stream_to_call: Dict[str, str] = {}  # stream_sid -> call_sid
        self._session_to_call: Dict[str, str] = {}  # session_id -> call_sid
        self._dashboard_callback: Optional[Callable] = None

    def set_dashboard_callback(self, callback: Callable[[str, dict], Awaitable[None]]):
        """Set callback for dashboard updates."""
        self._dashboard_callback = callback

    @property
    def client(self) -> Optional[Client]:
        """Lazy-load Twilio client."""
        if self._client is None:
            if not settings.twilio_account_sid or not settings.twilio_auth_token:
                logger.warning("Twilio credentials not configured")
                return None
            self._client = Client(
                settings.twilio_account_sid,
                settings.twilio_auth_token
            )
        return self._client

    @property
    def is_configured(self) -> bool:
        """Check if Twilio is properly configured."""
        return bool(
            settings.twilio_account_sid and
            settings.twilio_auth_token and
            settings.twilio_phone_number and
            settings.twilio_webhook_base_url
        )

    def register_call(self, call_sid: str, session_id: str, from_number: str = None) -> ActiveCall:
        """Register a new incoming call."""
        call = ActiveCall(
            call_sid=call_sid,
            session_id=session_id,
            customer_phone=from_number
        )
        self._active_calls[call_sid] = call
        self._session_to_call[session_id] = call_sid
        logger.info(f"[{session_id}] Registered call: {call_sid} from {from_number}")
        return call

    def register_stream(self, stream_sid: str, call_sid: str):
        """Register a media stream to a call."""
        self._stream_to_call[stream_sid] = call_sid
        call = self._active_calls.get(call_sid)
        if call:
            call.stream_sid = stream_sid
            call.state = CallState.AI_CONVERSATION
            logger.info(f"[{call.session_id}] Stream registered: {stream_sid}")

    def get_call(self, call_sid: str) -> Optional[ActiveCall]:
        """Get call by SID."""
        return self._active_calls.get(call_sid)

    def get_call_by_stream(self, stream_sid: str) -> Optional[ActiveCall]:
        """Get call by stream SID."""
        call_sid = self._stream_to_call.get(stream_sid)
        return self._active_calls.get(call_sid) if call_sid else None

    def get_call_by_session(self, session_id: str) -> Optional[ActiveCall]:
        """Get call by session ID."""
        call_sid = self._session_to_call.get(session_id)
        return self._active_calls.get(call_sid) if call_sid else None

    def cleanup_call(self, call_sid: str):
        """Remove call from tracking."""
        call = self._active_calls.pop(call_sid, None)
        if call:
            if call.stream_sid:
                self._stream_to_call.pop(call.stream_sid, None)
            self._session_to_call.pop(call.session_id, None)
            logger.info(f"[{call.session_id}] Call cleaned up: {call_sid}")

    # ==================== TwiML Generators ====================

    def generate_stream_twiml(self, session_id: str, call_sid: str) -> str:
        """Generate TwiML that connects to our media stream WebSocket."""
        response = VoiceResponse()

        # Connect to our WebSocket for bidirectional audio
        connect = Connect()
        stream = Stream(
            url=f"wss://{settings.twilio_webhook_base_url.replace('https://', '').replace('http://', '')}/api/voice/media-stream",
            name=f"stream_{session_id}"
        )
        stream.parameter(name="session_id", value=session_id)
        stream.parameter(name="call_sid", value=call_sid)
        connect.append(stream)
        response.append(connect)

        return str(response)

    def generate_escalation_twiml(self, session_id: str, conference_name: str) -> str:
        """Generate TwiML to put customer in conference for escalation."""
        response = VoiceResponse()

        # Put customer in conference (AI message already played via TTS before redirect)
        dial = Dial()
        dial.conference(
            conference_name,
            start_conference_on_enter=True,
            end_conference_on_exit=True,
            wait_url="http://twimlets.com/holdmusic?Bucket=com.twilio.music.classical",
            status_callback=f"{settings.twilio_webhook_base_url}/api/voice/conference-status?session_id={session_id}",
            status_callback_event="start end join leave"
        )
        response.append(dial)

        return str(response)

    def generate_human_confirmation_twiml(self, session_id: str, conference_name: str,
                                          customer_name: str, reason: str) -> str:
        """
        Generate TwiML that defeats call screening by requiring DTMF input.

        Strategy:
        1. Play message IMMEDIATELY (no delays - call screening hangs up fast!)
        2. Wait for ANY keypress (call screening won't press keys)
        3. If key pressed → human confirmed → play details and connect
        4. If no key → call screening/voicemail → hang up

        Critical timing: Must speak within 500ms or call screening records silence and hangs up.
        """
        from twilio.twiml.voice_response import Gather

        response = VoiceResponse()

        # URL for when human presses any key (proves they're human)
        human_detected_url = (
            f"{settings.twilio_webhook_base_url}/api/voice/human-detected"
            f"?session_id={session_id}&conference={conference_name}"
            f"&customer_name={quote(customer_name)}&reason={quote(reason)}"
        )

        # CRITICAL: Start speaking IMMEDIATELY - no pauses, no dots
        # Call screening only waits ~1-2 seconds before hanging up
        gather = Gather(
            num_digits=1,
            action=human_detected_url,
            method="POST",
            timeout=10,
            finish_on_key=""  # Any key works
        )
        # Speak the message right away - urgent and clear
        # Repeat twice to ensure human hears it if they picked up mid-ring
        gather.say(
            "Incoming customer call. Press any key to accept. "
            "Press any key to accept the call.",
            voice="Polly.Matthew"
        )
        response.append(gather)

        # If no input after timeout, likely call screening or voicemail - hang up
        response.hangup()

        return str(response)

    def generate_human_join_conference_twiml(self, session_id: str, conference_name: str) -> str:
        """Generate TwiML to add confirmed human to conference."""
        response = VoiceResponse()

        response.say("Connecting you to the customer now.", voice="Polly.Matthew")

        dial = Dial()
        dial.conference(
            conference_name,
            start_conference_on_enter=True,
            end_conference_on_exit=False,
            beep=True
        )
        response.append(dial)

        return str(response)

    def generate_return_to_ai_twiml(self, session_id: str, message: str = None) -> str:
        """
        Generate TwiML to return customer to AI conversation after failed escalation.

        This creates a new media stream connection so the AI can resume the conversation.
        No hardcoded messages - the AI agent will generate appropriate responses.
        """
        response = VoiceResponse()

        # No hardcoded message - AI agent will handle the conversation
        # Reconnect to our media stream for AI conversation
        connect = Connect()
        stream = Stream(
            url=f"wss://{settings.twilio_webhook_base_url.replace('https://', '').replace('http://', '')}/api/voice/media-stream",
            name=f"stream_{session_id}_resumed"
        )
        stream.parameter(name="session_id", value=session_id)
        stream.parameter(name="resumed", value="true")
        connect.append(stream)
        response.append(connect)

        return str(response)

    async def return_to_ai_conversation(self, session_id: str, reason: str = "unavailable"):
        """
        Return customer from conference back to AI conversation.

        Called when human agent is unavailable or declines the call.
        No hardcoded messages - AI agent handles all responses.
        """
        logger.info(f"[{session_id}] === RETURN TO AI REQUESTED === reason={reason}")
        call = self.get_call_by_session(session_id)
        if not call:
            logger.warning(f"[{session_id}] Cannot return to AI - call not found in registry")
            logger.info(f"[{session_id}] Active sessions: {list(self._session_to_call.keys())}")
            return False
        if not self.client:
            logger.warning(f"[{session_id}] Cannot return to AI - Twilio client not configured")
            return False

        logger.info(f"[{session_id}] Found call: call_sid={call.call_sid}, state={call.state}")

        try:
            # Update call state
            call.state = CallState.AI_CONVERSATION
            call.conference_name = None
            call.human_call_sid = None
            # Store the reason so AI agent can access it and generate appropriate response
            call.escalation_return_reason = reason

            # Redirect customer back to AI - no hardcoded message
            redirect_url = f"{settings.twilio_webhook_base_url}/api/voice/return-to-ai?session_id={session_id}&reason={reason}"
            logger.info(f"[{session_id}] Redirecting call {call.call_sid} to: {redirect_url}")

            self.client.calls(call.call_sid).update(
                url=redirect_url,
                method="POST"
            )

            logger.info(f"[{session_id}] Successfully redirected customer to AI conversation (reason: {reason})")

            await self._notify_dashboard(call, "escalation", {
                "status": "returned_to_ai",
                "reason": reason
            })

            return True

        except Exception as e:
            logger.error(f"[{session_id}] Failed to return to AI: {e}")
            return False

    # ==================== Audio Processing ====================

    async def process_audio_chunk(self, stream_sid: str, payload: str) -> Optional[bytes]:
        """
        Process incoming audio chunk from Twilio Media Stream.

        Args:
            stream_sid: The stream SID
            payload: Base64 encoded mulaw audio

        Returns:
            Response audio bytes if ready, None otherwise
        """
        call = self.get_call_by_stream(stream_sid)
        if not call:
            return None

        # Decode audio
        audio_data = base64.b64decode(payload)

        # Calculate energy for VAD
        try:
            # Convert mulaw to linear for energy calculation
            linear = audioop.ulaw2lin(audio_data, 2)
            energy = audioop.rms(linear, 2)
        except Exception:
            energy = 0

        # Voice Activity Detection with barge-in support
        if energy > self.SILENCE_THRESHOLD:
            call.silence_frames = 0
            if not call.is_speaking:
                call.is_speaking = True
                logger.debug(f"[{call.session_id}] Speech started")

                # Barge-in: If we're playing audio and user starts speaking, interrupt
                if call.is_playing_audio:
                    call.barge_in_requested = True
                    logger.info(f"[{call.session_id}] User started speaking during playback - barge-in triggered")

            call.audio_buffer += audio_data
        else:
            if call.is_speaking:
                call.silence_frames += 1
                call.audio_buffer += audio_data  # Include trailing silence

                if call.silence_frames >= self.MIN_SILENCE_FRAMES:
                    # End of utterance detected
                    call.is_speaking = False
                    logger.info(f"[{call.session_id}] Speech ended, processing {len(call.audio_buffer)} bytes")

                    # Process the complete utterance
                    response_audio = await self._process_utterance(call)

                    # Clear buffer
                    call.audio_buffer = bytes()
                    call.silence_frames = 0

                    return response_audio

        return None

    async def _process_utterance(self, call: ActiveCall) -> Optional[bytes]:
        """
        Process a complete utterance: STT -> LLM -> TTS.

        Returns audio bytes to stream back to Twilio, or None if escalation is happening.
        """
        import time
        call.state = CallState.PROCESSING

        # Timing tracking
        timings = {"stt_ms": 0, "llm_ms": 0, "tts_ms": 0}

        # Convert mulaw to wav for STT
        try:
            # Convert mulaw 8kHz to linear PCM
            linear = audioop.ulaw2lin(call.audio_buffer, 2)
            # Resample to 16kHz for better STT
            linear_16k = audioop.ratecv(linear, 2, 1, 8000, 16000, None)[0]

            # Create WAV header
            import struct
            wav_header = struct.pack(
                '<4sI4s4sIHHIIHH4sI',
                b'RIFF',
                len(linear_16k) + 36,
                b'WAVE',
                b'fmt ',
                16,  # PCM header size
                1,   # PCM format
                1,   # Mono
                16000,  # Sample rate
                32000,  # Byte rate
                2,   # Block align
                16,  # Bits per sample
                b'data',
                len(linear_16k)
            )
            wav_data = wav_header + linear_16k

        except Exception as e:
            logger.error(f"[{call.session_id}] Audio conversion error: {e}")
            call.state = CallState.AI_CONVERSATION
            return None

        # Transcribe (with timing)
        stt_start = time.time()
        text = await audio_processor.transcribe(wav_data, format="wav")
        timings["stt_ms"] = int((time.time() - stt_start) * 1000)

        if not text:
            logger.warning(f"[{call.session_id}] No transcription result")
            call.state = CallState.AI_CONVERSATION
            return None

        logger.info(f"[{call.session_id}] User said: '{text}' (STT: {timings['stt_ms']}ms)")

        # Add to transcript and notify dashboard
        call.transcript.append({"role": "user", "content": text, "timestamp": datetime.utcnow().isoformat()})
        await self._notify_dashboard(call, "transcript", {"role": "user", "content": text})

        # Process with LLM (with timing)
        should_end = False
        needs_escalation = False
        result = {}  # Initialize result for use in state_update
        llm_start = time.time()
        try:
            result = await conversation_service.process_voice_message(
                session_id=call.session_id,
                user_message=text
            )
            timings["llm_ms"] = int((time.time() - llm_start) * 1000)

            ai_response = result.get("response", "")
            needs_escalation = result.get("needs_escalation", False)
            escalation_reason = result.get("escalation_reason", "assistance")
            should_end = result.get("should_end", False)
            customer_name = result.get("customer_name")

            if customer_name:
                call.customer_name = customer_name

            logger.info(f"[{call.session_id}] AI response: '{ai_response[:100]}...' (end_call={should_end}, escalate={needs_escalation})")

        except Exception as e:
            timings["llm_ms"] = int((time.time() - llm_start) * 1000)
            logger.error(f"[{call.session_id}] LLM error: {e}")
            # Let agent generate error response - no hardcoded message
            try:
                error_result = await conversation_service.process_voice_message(
                    session_id=call.session_id,
                    user_message="[PROCESSING_ERROR]"
                )
                ai_response = error_result.get("response", "")
            except Exception:
                ai_response = ""  # No response if agent also fails
            needs_escalation = False
            result = {}  # Ensure result is empty dict on error

        # Add to transcript and notify dashboard
        call.transcript.append({"role": "assistant", "content": ai_response, "timestamp": datetime.utcnow().isoformat()})
        await self._notify_dashboard(call, "transcript", {"role": "assistant", "content": ai_response})

        # Fetch current state to get customer info and other state data
        from app.background.state_store import state_store
        current_state = await state_store.get_state(call.session_id)

        # Prepare customer data for dashboard
        customer_data = None
        if current_state:
            customer = current_state.customer
            logger.info(f"[{call.session_id}] Customer state: id={customer.customer_id}, name={customer.name}, is_identified={customer.is_identified}")
            if customer and customer.is_identified:
                customer_data = {
                    "customer_id": customer.customer_id,  # Frontend expects "customer_id" not "id"
                    "name": customer.name,
                    "phone": customer.phone,
                    "email": customer.email,
                    "is_identified": True
                }
                logger.info(f"[{call.session_id}] Sending customer data to dashboard: {customer_data}")

        # Prepare pending tasks data
        pending_tasks_data = []
        if current_state and current_state.pending_tasks:
            for task in current_state.pending_tasks:
                task_dict = task.model_dump() if hasattr(task, 'model_dump') else task
                # Convert enum values to strings
                if 'task_type' in task_dict and hasattr(task_dict['task_type'], 'value'):
                    task_dict['task_type'] = task_dict['task_type'].value
                if 'status' in task_dict and hasattr(task_dict['status'], 'value'):
                    task_dict['status'] = task_dict['status'].value
                pending_tasks_data.append(task_dict)

        # Send state_update with booking slots, customer info, etc.
        # This ensures the UI updates in real-time after each turn
        # Only send human_agent_status if there's an actual escalation (not "none")
        human_status = None
        if call.human_call_status and call.human_call_status != HumanCallStatus.NONE:
            human_status = call.human_call_status.value

        logger.info(f"[{call.session_id}] Sending state_update to dashboard: customer_data={customer_data}, booking_slots={result.get('booking_slots')}")
        await self._notify_dashboard(call, "state_update", {
            "current_agent": "unified",
            "intent": result.get("intent"),
            "confidence": 0.9,
            "escalation_in_progress": needs_escalation,
            "human_agent_status": human_status,
            "booking_slots": result.get("booking_slots"),
            "confirmed_appointment": result.get("confirmed_appointment"),
            "customer": customer_data,
            "pending_tasks": pending_tasks_data,
        })

        # Start human call in background - customer stays with AI until human answers
        if needs_escalation and call.human_call_status == HumanCallStatus.NONE:
            logger.info(f"[{call.session_id}] Starting human call in background - customer stays with AI")
            call.escalation_reason = escalation_reason
            # Start calling human (non-blocking) - customer continues talking to AI
            asyncio.create_task(self._start_human_call_background(call, escalation_reason))
            await self._notify_dashboard(call, "escalation", {"status": "calling", "reason": escalation_reason})

        # Check for call ending (agent decided to end the call)
        if should_end:
            logger.info(f"[{call.session_id}] Agent requested call end")
            call.state = CallState.ENDED
            await self._notify_dashboard(call, "call_ending", {
                "reason": "agent_ended",
                "farewell": ai_response
            })

        # Synthesize response (using Kokoro with default voice from env) - with timing
        tts_start = time.time()
        audio_mp3 = await audio_processor.synthesize(ai_response)
        timings["tts_ms"] = int((time.time() - tts_start) * 1000)

        if not audio_mp3:
            logger.error(f"[{call.session_id}] TTS failed")
            call.state = CallState.AI_CONVERSATION
            return None

        total_ms = timings["stt_ms"] + timings["llm_ms"] + timings["tts_ms"]
        logger.info(f"[{call.session_id}] Latency: STT={timings['stt_ms']}ms, LLM={timings['llm_ms']}ms, TTS={timings['tts_ms']}ms, TOTAL={total_ms}ms")

        # Notify dashboard with latency data
        await self._notify_dashboard(call, "latency", {
            "stt_ms": timings["stt_ms"],
            "llm_ms": timings["llm_ms"],
            "tts_ms": timings["tts_ms"],
            "total_ms": total_ms
        })

        # Convert MP3 to mulaw 8kHz for Twilio
        # Note: This requires ffmpeg or pydub for proper conversion
        # For now, we'll return the MP3 and handle conversion in the WebSocket handler
        # Only reset state to AI_CONVERSATION if we're NOT ending the call
        if not should_end:
            call.state = CallState.AI_CONVERSATION
        return audio_mp3

    async def _notify_dashboard(self, call: ActiveCall, event_type: str, data: dict):
        """Send update to web dashboard."""
        if self._dashboard_callback:
            try:
                await self._dashboard_callback(call.session_id, {
                    "type": event_type,
                    "session_id": call.session_id,
                    "call_sid": call.call_sid,
                    "state": call.state.value,
                    "customer_phone": call.customer_phone,
                    "customer_name": call.customer_name,
                    **data
                })
            except Exception as e:
                logger.warning(f"[{call.session_id}] Dashboard notification failed: {e}")

    def get_human_call_status(self, session_id: str) -> Optional[dict]:
        """Get the current status of human escalation for AI to relay to customer."""
        call = self.get_call_by_session(session_id)
        if not call:
            return None

        return {
            "status": call.human_call_status.value,
            "message": call.human_status_message,
            "reason": call.escalation_reason
        }

    def clear_human_status_message(self, session_id: str):
        """Clear the human status message after it's been delivered."""
        call = self.get_call_by_session(session_id)
        if call:
            call.human_status_message = None

    def queue_event(self, session_id: str, event_type: str, message: str):
        """
        Queue an event for immediate processing.
        This triggers barge-in if audio is playing.
        """
        call = self.get_call_by_session(session_id)
        if not call:
            logger.warning(f"[{session_id}] Cannot queue event - call not found")
            return

        event = {
            "type": event_type,
            "message": message,
            "timestamp": datetime.utcnow().isoformat()
        }
        call.pending_events.append(event)
        logger.info(f"[{session_id}] Queued event: {event_type} - {message[:50]}...")

        # If audio is playing, trigger barge-in
        if call.is_playing_audio:
            call.barge_in_requested = True
            logger.info(f"[{session_id}] Barge-in requested - will interrupt audio playback")

    def pop_pending_event(self, session_id: str) -> Optional[dict]:
        """Get and remove the next pending event."""
        call = self.get_call_by_session(session_id)
        if not call or not call.pending_events:
            return None

        return call.pending_events.popleft()

    def has_pending_events(self, session_id: str) -> bool:
        """Check if there are pending events."""
        call = self.get_call_by_session(session_id)
        return call is not None and len(call.pending_events) > 0

    def set_playing_audio(self, session_id: str, is_playing: bool):
        """Set audio playback state for barge-in tracking."""
        call = self.get_call_by_session(session_id)
        if call:
            call.is_playing_audio = is_playing
            if not is_playing:
                call.barge_in_requested = False

    def should_barge_in(self, session_id: str) -> bool:
        """Check if barge-in has been requested."""
        call = self.get_call_by_session(session_id)
        return call is not None and call.barge_in_requested

    def clear_barge_in(self, session_id: str):
        """Clear barge-in flag."""
        call = self.get_call_by_session(session_id)
        if call:
            call.barge_in_requested = False

    async def end_call(self, session_id: str):
        """
        End the Twilio call gracefully.
        Called after farewell message has been played.
        """
        call = self.get_call_by_session(session_id)
        if not call or not self.client:
            logger.warning(f"[{session_id}] Cannot end call - call not found or Twilio not configured")
            return False

        try:
            logger.info(f"[{session_id}] Ending call: {call.call_sid}")
            self.client.calls(call.call_sid).update(status="completed")
            call.state = CallState.ENDED
            self.cleanup_call(call.call_sid)

            await self._notify_dashboard(call, "call_ended", {
                "reason": "agent_ended"
            })

            return True
        except Exception as e:
            logger.error(f"[{session_id}] Failed to end call: {e}")
            return False

    async def update_human_call_status(self, session_id: str, status: str, duration: int = None):
        """
        Update human call status based on Twilio webhook.
        Called from /human-status endpoint.

        Updates both:
        1. In-memory ActiveCall state
        2. Redis ConversationState (so AI agent knows the status)
        3. Dashboard via WebSocket

        Flow with confirmation:
        1. initiated -> calling
        2. ringing -> ringing
        3. in-progress -> waiting_confirmation (human/call-screening answered, waiting for press 1)
        4. (human presses 1) -> confirmed (via /human-confirmed endpoint)
        5. completed -> handles various end states
        """
        from app.background.state_store import state_store
        from app.schemas.enums import HumanAgentStatus as StateHumanAgentStatus

        call = self.get_call_by_session(session_id)
        if not call:
            logger.warning(f"[{session_id}] Cannot update human status - call not found")
            return

        old_status = call.human_call_status
        logger.info(f"[{session_id}] Human call status update: {status} (was {old_status.value})")

        # Use specific status for frontend display (more granular than internal enum)
        frontend_status = status
        escalation_in_progress = True  # Default to true, set false on terminal states

        if status == "initiated":
            call.human_call_status = HumanCallStatus.CALLING
            frontend_status = "calling"

        elif status == "ringing":
            call.human_call_status = HumanCallStatus.RINGING
            frontend_status = "ringing"

        elif status == "in-progress":
            # Call connected - but could be call screening or early media!
            # Don't assume human answered. The /human-answer endpoint will play
            # "press 1 to accept" and we'll update to CONFIRMED when they do.
            call.human_call_status = HumanCallStatus.WAITING_CONFIRMATION
            frontend_status = "waiting_confirmation"
            logger.info(f"[{session_id}] Call connected - waiting for human to press 1 to confirm")

        elif status in ("busy", "no-answer", "failed", "canceled"):
            call.human_call_status = HumanCallStatus.FAILED
            # Keep specific status for frontend (no-answer, busy, canceled, failed)
            frontend_status = status if status in ("busy", "no-answer", "canceled") else "failed"
            # Reset escalation state so customer can try again later
            call.escalation_reason = None
            call.human_call_sid = None
            call.conference_name = None
            escalation_in_progress = False
            logger.info(f"[{session_id}] Human call failed with status: {status}")
            # Queue event so AI can inform customer proactively
            self.queue_event(session_id, "escalation_failed", f"[ESCALATION_RETURNED:{frontend_status}]")

        elif status == "completed":
            if call.human_call_status == HumanCallStatus.IN_CONFERENCE:
                # Human hung up after being in conference - return customer to AI
                call.human_call_status = HumanCallStatus.COMPLETED
                frontend_status = "returned_to_ai"
                escalation_in_progress = False
                logger.info(f"[{session_id}] Human completed - returning customer to AI")
                await self.return_to_ai_conversation(session_id, reason="human_ended")
            elif call.human_call_status == HumanCallStatus.CONFIRMED:
                # Human hung up after confirming but before conference (quick hangup)
                call.human_call_status = HumanCallStatus.FAILED
                frontend_status = "failed"
                escalation_in_progress = False
                call.escalation_reason = None
                # Queue event so AI can inform customer proactively
                self.queue_event(session_id, "escalation_failed", "[ESCALATION_RETURNED:failed]")
            elif call.human_call_status == HumanCallStatus.WAITING_CONFIRMATION:
                # Human (or call screening) didn't press 1 - treat as no answer
                # This happens when human declines by hanging up during the Gather prompt
                call.human_call_status = HumanCallStatus.FAILED
                frontend_status = "no-answer"
                escalation_in_progress = False
                call.escalation_reason = None
                logger.info(f"[{session_id}] Human did not confirm (no press 1) - treating as no-answer")
                # Queue event so AI can inform customer proactively
                self.queue_event(session_id, "escalation_failed", "[ESCALATION_RETURNED:no-answer]")

        # Update conversation state in Redis so AI agent knows the status
        try:
            state = await state_store.get_state(session_id)
            if state:
                # Map frontend status to HumanAgentStatus enum
                status_mapping = {
                    "calling": StateHumanAgentStatus.CALLING,
                    "ringing": StateHumanAgentStatus.RINGING,
                    "waiting_confirmation": StateHumanAgentStatus.WAITING,
                    "confirmed": StateHumanAgentStatus.CONNECTED,
                    "connected": StateHumanAgentStatus.CONNECTED,
                    "no-answer": StateHumanAgentStatus.UNAVAILABLE,
                    "busy": StateHumanAgentStatus.UNAVAILABLE,
                    "failed": StateHumanAgentStatus.UNAVAILABLE,
                    "returned_to_ai": StateHumanAgentStatus.UNAVAILABLE,
                }
                state.human_agent_status = status_mapping.get(frontend_status)
                state.escalation_in_progress = escalation_in_progress
                await state_store.set_state(session_id, state)
                logger.info(f"[{session_id}] Updated Redis state: human_agent_status={state.human_agent_status}, escalation_in_progress={escalation_in_progress}")
        except Exception as e:
            logger.error(f"[{session_id}] Failed to update Redis state: {e}")

        # Send real-time update to frontend dashboard
        logger.info(f"[{session_id}] Sending human_status to dashboard: {frontend_status}")
        await self._notify_dashboard(call, "human_status", {
            "status": frontend_status
        })

    async def handle_human_declined(self, session_id: str) -> bool:
        """
        Handle human pressing a key other than 1 (declining the call).

        This resets the escalation state so the customer can continue with AI
        and potentially try again later.
        """
        from app.background.state_store import state_store
        from app.schemas.enums import HumanAgentStatus as StateHumanAgentStatus

        call = self.get_call_by_session(session_id)
        if not call:
            logger.warning(f"[{session_id}] Cannot handle decline - call not found")
            return False

        logger.info(f"[{session_id}] Human declined the call")

        # Reset call state
        call.human_call_status = HumanCallStatus.FAILED
        call.escalation_reason = None
        call.human_call_sid = None
        call.conference_name = None

        # Update Redis state so AI knows escalation failed
        try:
            state = await state_store.get_state(session_id)
            if state:
                state.human_agent_status = StateHumanAgentStatus.UNAVAILABLE
                state.escalation_in_progress = False
                await state_store.set_state(session_id, state)
                logger.info(f"[{session_id}] Updated Redis state: human declined, escalation cleared")
        except Exception as e:
            logger.error(f"[{session_id}] Failed to update Redis state: {e}")

        # Notify dashboard
        await self._notify_dashboard(call, "human_status", {
            "status": "declined"
        })

        # Queue event so AI can inform customer proactively
        self.queue_event(session_id, "escalation_failed", "[ESCALATION_RETURNED:declined]")

        return True

    async def handle_human_confirmed(self, session_id: str) -> bool:
        """
        Handle human pressing 1 to confirm they want to take the call.

        Returns True if confirmation was successful.
        """
        from app.background.state_store import state_store
        from app.schemas.enums import HumanAgentStatus as StateHumanAgentStatus

        call = self.get_call_by_session(session_id)
        if not call:
            logger.warning(f"[{session_id}] Cannot confirm human - call not found")
            return False

        if call.human_call_status != HumanCallStatus.WAITING_CONFIRMATION:
            logger.warning(f"[{session_id}] Unexpected confirmation - status was {call.human_call_status}")

        call.human_call_status = HumanCallStatus.CONFIRMED
        logger.info(f"[{session_id}] Human confirmed! Will transfer customer to conference")

        # Update Redis state so AI knows
        try:
            state = await state_store.get_state(session_id)
            if state:
                state.human_agent_status = StateHumanAgentStatus.CONNECTED
                state.escalation_in_progress = True
                await state_store.set_state(session_id, state)
                logger.info(f"[{session_id}] Updated Redis state: human confirmed")
        except Exception as e:
            logger.error(f"[{session_id}] Failed to update Redis state: {e}")

        # Notify dashboard
        await self._notify_dashboard(call, "human_status", {
            "status": "confirmed"
        })

        # Now transfer customer to conference
        # Small delay to let the "connecting you" message play on human's end
        async def delayed_transfer():
            await asyncio.sleep(2)  # Shorter delay since human is already confirmed
            await self.transfer_customer_to_conference(session_id)

        asyncio.create_task(delayed_transfer())

        return True

    async def transfer_customer_to_conference(self, session_id: str) -> bool:
        """
        Transfer customer from AI conversation to conference with human.
        Called when human has CONFIRMED (pressed 1) and customer should be transferred.
        """
        call = self.get_call_by_session(session_id)
        if not call or not self.client:
            logger.warning(f"[{session_id}] Cannot transfer - call not found or Twilio not configured")
            return False

        if call.human_call_status != HumanCallStatus.CONFIRMED:
            logger.warning(f"[{session_id}] Cannot transfer - human not confirmed (status: {call.human_call_status})")
            return False

        conference_name = call.conference_name
        if not conference_name:
            logger.error(f"[{session_id}] Cannot transfer - no conference name")
            return False

        try:
            logger.info(f"[{session_id}] Transferring customer to conference: {conference_name}")
            call.state = CallState.ESCALATING
            call.human_call_status = HumanCallStatus.IN_CONFERENCE

            # Redirect customer to conference
            self.client.calls(call.call_sid).update(
                url=f"{settings.twilio_webhook_base_url}/api/voice/escalate?session_id={session_id}&conference={conference_name}",
                method="POST"
            )

            # Send human_status with "connected" - don't send escalation event
            # which would reset the status display
            await self._notify_dashboard(call, "human_status", {
                "status": "connected"
            })

            return True

        except Exception as e:
            logger.error(f"[{session_id}] Failed to transfer customer: {e}")
            call.human_call_status = HumanCallStatus.FAILED
            return False

    async def _start_human_call_background(self, call: ActiveCall, reason: str):
        """
        Start calling human agent in background.
        Customer stays in AI conversation until human confirms (presses 1).
        No hardcoded messages - AI agent handles all responses.
        """
        if not self.client or not settings.customer_service_phone:
            logger.error(f"[{call.session_id}] Cannot escalate - not configured")
            call.human_call_status = HumanCallStatus.FAILED
            return

        conference_name = f"support_{call.session_id}"
        call.conference_name = conference_name
        call.human_call_status = HumanCallStatus.CALLING

        logger.info(f"[{call.session_id}] Starting human call to {settings.customer_service_phone}")

        # URL-encode parameters that might contain special characters
        encoded_reason = quote(reason or "assistance")
        encoded_customer_name = quote(call.customer_name or "Customer")

        try:
            # Only call the human - DON'T redirect customer yet
            # Customer stays talking to AI until human CONFIRMS
            #
            # Two-step DTMF confirmation defeats call screening:
            # 1. Play "press any key" - call screening won't press anything
            # 2. If key pressed, play details and ask for "1" to accept
            # 3. If "1" pressed, transfer customer to conference
            human_call = self.client.calls.create(
                to=settings.customer_service_phone,
                from_=settings.twilio_phone_number,
                url=f"{settings.twilio_webhook_base_url}/api/voice/human-answer?session_id={call.session_id}&conference={conference_name}&reason={encoded_reason}&customer_name={encoded_customer_name}",
                status_callback=f"{settings.twilio_webhook_base_url}/api/voice/human-status?session_id={call.session_id}",
                # Event names: initiated, ringing, answered, completed
                # Note: "answered" event sends CallStatus="in-progress" in the callback
                status_callback_event=["initiated", "ringing", "answered", "completed"],
                timeout=45  # Give more time for the two-step confirmation
            )

            call.human_call_sid = human_call.sid
            logger.info(f"[{call.session_id}] Human call initiated: {human_call.sid}")

            await self._notify_dashboard(call, "escalation", {
                "status": "calling",
                "human_call_sid": human_call.sid
            })

            # Start a watchdog task to check for stalled/missed status callbacks
            asyncio.create_task(self._human_call_watchdog(call.session_id, human_call.sid))

        except Exception as e:
            logger.error(f"[{call.session_id}] Failed to call human: {e}")
            call.human_call_status = HumanCallStatus.FAILED

    async def _human_call_watchdog(self, session_id: str, human_call_sid: str):
        """
        Watchdog task that monitors human call status and handles cases where
        Twilio doesn't send status callbacks (e.g., quickly declined calls).

        Checks the call status via REST API if no progress is made.
        """
        WATCHDOG_CHECK_INTERVAL = 5  # Check every 5 seconds
        WATCHDOG_TIMEOUT = 60  # Total timeout
        RINGING_TIMEOUT = 30  # Max time to stay in ringing state

        start_time = datetime.utcnow()
        last_status = None
        ringing_start_time = None

        while True:
            await asyncio.sleep(WATCHDOG_CHECK_INTERVAL)

            call = self.get_call_by_session(session_id)
            if not call:
                logger.info(f"[{session_id}] Watchdog: Call no longer exists, stopping")
                break

            current_status = call.human_call_status
            elapsed = (datetime.utcnow() - start_time).total_seconds()

            # Track when we started ringing
            if current_status == HumanCallStatus.RINGING and ringing_start_time is None:
                ringing_start_time = datetime.utcnow()

            # If status changed to a terminal state, we're done
            if current_status in (HumanCallStatus.FAILED, HumanCallStatus.COMPLETED,
                                  HumanCallStatus.IN_CONFERENCE, HumanCallStatus.CONFIRMED):
                logger.info(f"[{session_id}] Watchdog: Human call reached terminal state: {current_status.value}")
                break

            # Check for ringing timeout (call might have been declined without callback)
            if ringing_start_time:
                ringing_elapsed = (datetime.utcnow() - ringing_start_time).total_seconds()
                if ringing_elapsed > RINGING_TIMEOUT:
                    logger.warning(f"[{session_id}] Watchdog: Ringing timeout ({ringing_elapsed:.0f}s) - checking call status via API")
                    await self._check_and_update_call_status(session_id, human_call_sid)
                    break

            # Check total timeout
            if elapsed > WATCHDOG_TIMEOUT:
                logger.warning(f"[{session_id}] Watchdog: Total timeout ({elapsed:.0f}s) - checking call status via API")
                await self._check_and_update_call_status(session_id, human_call_sid)
                break

            # If status hasn't changed for a while and we're in CALLING state, check via API
            if current_status == HumanCallStatus.CALLING and elapsed > 15:
                logger.info(f"[{session_id}] Watchdog: Still in CALLING state after {elapsed:.0f}s, checking via API")
                await self._check_and_update_call_status(session_id, human_call_sid)
                # Don't break - let the status update trigger the appropriate action

            last_status = current_status

        logger.info(f"[{session_id}] Watchdog: Stopped monitoring human call")

    async def _check_and_update_call_status(self, session_id: str, human_call_sid: str):
        """
        Check the actual call status via Twilio REST API and update our state.
        Used when we suspect a status callback was missed.
        """
        if not self.client:
            logger.error(f"[{session_id}] Cannot check call status - Twilio client not configured")
            return

        try:
            # Fetch the call status from Twilio
            twilio_call = self.client.calls(human_call_sid).fetch()
            status = twilio_call.status

            logger.info(f"[{session_id}] Watchdog: Twilio API reports call status: {status}")

            call = self.get_call_by_session(session_id)
            if not call:
                return

            # Map Twilio status to our handling
            # Twilio statuses: queued, ringing, in-progress, completed, busy, failed, no-answer, canceled
            if status in ("busy", "no-answer", "failed", "canceled", "completed"):
                # Call ended - determine why
                if status == "completed" and call.human_call_status == HumanCallStatus.IN_CONFERENCE:
                    # Normal completion after conference
                    logger.info(f"[{session_id}] Watchdog: Call completed normally after conference")
                else:
                    # Call failed or was declined
                    logger.warning(f"[{session_id}] Watchdog: Call ended with status '{status}' - marking as failed")

                    # Update status (this also notifies dashboard and updates Redis)
                    await self.update_human_call_status(session_id, status, None)
            elif status == "in-progress":
                # Call is connected but we might have missed the callback
                if call.human_call_status not in (HumanCallStatus.WAITING_CONFIRMATION,
                                                   HumanCallStatus.CONFIRMED,
                                                   HumanCallStatus.IN_CONFERENCE):
                    logger.info(f"[{session_id}] Watchdog: Call is in-progress but status is {call.human_call_status.value}")
                    await self.update_human_call_status(session_id, "in-progress", None)
            elif status == "ringing":
                # Still ringing - update if needed
                if call.human_call_status != HumanCallStatus.RINGING:
                    await self.update_human_call_status(session_id, "ringing", None)
            elif status == "queued":
                # Still queued - call hasn't started yet
                logger.info(f"[{session_id}] Watchdog: Call still queued")

        except Exception as e:
            logger.error(f"[{session_id}] Watchdog: Failed to check call status: {e}")


# Global singleton
twilio_voice = TwilioVoiceService()
