"""
Twilio Voice Webhook Routes with Media Streams.

Handles:
1. Incoming call -> Start media stream
2. Media stream WebSocket -> Bidirectional audio
3. Escalation -> Conference + call human
4. Real-time dashboard updates
"""
import logging
import uuid
import json
import base64
import asyncio
from typing import Optional
from fastapi import APIRouter, Form, Query, Response, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.services.twilio_voice import twilio_voice, CallState, HumanCallStatus
from app.background.state_store import state_store
from app.api.websocket import get_ws_manager

logger = logging.getLogger("app.api.voice")

router = APIRouter(prefix="/voice", tags=["voice"])


# ==================== Dashboard Callback ====================

async def dashboard_callback(session_id: str, data: dict):
    """Send updates to web dashboard via WebSocket.

    Broadcasts to both the session-specific WebSocket and the global
    'dashboard' WebSocket so the monitoring dashboard can see all calls.
    """
    ws_manager = get_ws_manager()
    # Send to session-specific WebSocket
    await ws_manager.broadcast(session_id, data)
    # Also send to global dashboard WebSocket for monitoring all calls
    await ws_manager.broadcast("dashboard", data)


# Set up the callback
twilio_voice.set_dashboard_callback(dashboard_callback)


# ==================== HTTP Webhooks ====================

@router.post("/incoming")
async def incoming_call(
    CallSid: str = Form(...),
    From: str = Form(None),
    To: str = Form(None),
    session_id: Optional[str] = Query(None)
):
    """
    Handle incoming call - returns TwiML to start media stream.
    """
    # Create or use session
    if not session_id:
        session_id = f"sess_{uuid.uuid4().hex[:12]}"

    logger.info(f"[{session_id}] === INCOMING CALL ===")
    logger.info(f"[{session_id}] CallSid: {CallSid}, From: {From}, To: {To}")

    # Register the call
    twilio_voice.register_call(CallSid, session_id, from_number=From)

    # Initialize conversation state
    try:
        await state_store.get_or_create_state(session_id)
    except Exception as e:
        logger.error(f"[{session_id}] Failed to create state: {e}")

    # Notify dashboard about new call
    await dashboard_callback(session_id, {
        "type": "call_started",
        "session_id": session_id,
        "call_sid": CallSid,
        "customer_phone": From,
        "state": "connecting"
    })

    # Return TwiML to start media stream
    twiml = twilio_voice.generate_stream_twiml(session_id, CallSid)
    logger.info(f"[{session_id}] Returning stream TwiML")

    return Response(content=twiml, media_type="application/xml")


@router.post("/escalate")
async def escalate_to_conference(
    session_id: str = Query(...),
    conference: str = Query(...),
    CallSid: str = Form(None)
):
    """
    Put customer in conference for escalation.
    """
    logger.info(f"[{session_id}] Escalating to conference: {conference}")

    twiml = twilio_voice.generate_escalation_twiml(session_id, conference)
    return Response(content=twiml, media_type="application/xml")


@router.post("/human-answer")
async def human_answered(
    session_id: str = Query(...),
    conference: str = Query(...),
    reason: str = Query("assistance"),
    customer_name: str = Query("Customer"),
    CallSid: str = Form(None),
    CallStatus: str = Form(None)
):
    """
    Called when the human agent answers the escalation call.

    New flow:
    1. Human answers -> this endpoint is called
    2. We add human to conference (waiting for customer)
    3. We queue "connecting you" message for customer
    4. After delay (to let message play), transfer customer to conference
    """
    logger.info(f"[{session_id}] === HUMAN ANSWERED ===")
    logger.info(f"[{session_id}] Conference: {conference}, CallStatus: {CallStatus}, CallSid: {CallSid}")
    logger.info(f"[{session_id}] Reason: {reason}, CustomerName: {customer_name}")

    # Notify dashboard
    await dashboard_callback(session_id, {
        "type": "human_answered",
        "session_id": session_id,
        "conference": conference
    })

    # Transfer customer to conference after a delay
    # This gives time for the "connecting you" message to be spoken
    # The message is queued by update_human_call_status() when it sees "in-progress"
    async def delayed_transfer():
        # Wait for the "connecting you" message to play (~5 seconds for TTS)
        await asyncio.sleep(5)
        await twilio_voice.transfer_customer_to_conference(session_id)

    asyncio.create_task(delayed_transfer())

    # Generate TwiML to add human to conference
    # Human enters conference first and waits briefly for customer
    twiml = twilio_voice.generate_human_answer_twiml(
        session_id=session_id,
        conference_name=conference,
        customer_name=customer_name,
        reason=reason
    )

    return Response(content=twiml, media_type="application/xml")


@router.post("/human-status")
async def human_call_status(
    session_id: str = Query(...),
    CallSid: str = Form(...),
    CallStatus: str = Form(...),
    CallDuration: Optional[int] = Form(None)
):
    """
    Handle human call status updates.

    New flow: Customer stays with AI until human answers.
    Status updates are relayed to AI so it can inform the customer.
    """
    logger.info(f"[{session_id}] Human call status: {CallStatus} (duration: {CallDuration})")

    # Update the call status - this handles all state transitions
    await twilio_voice.update_human_call_status(session_id, CallStatus, CallDuration)

    # Note: human_status event is already sent by twilio_voice.update_human_call_status()
    # No need to send duplicate event here

    return {"status": "ok"}


@router.post("/return-to-ai")
async def return_to_ai(
    session_id: str = Query(...),
    message: str = Query("I'm sorry, a team member isn't available right now. Let me continue helping you."),
    CallSid: str = Form(None)
):
    """
    Return customer to AI conversation after escalation fails or human is unavailable.

    This endpoint is called when we need to redirect the customer from conference back to AI.
    """
    logger.info(f"[{session_id}] Returning to AI conversation")

    # Update call state
    call = twilio_voice.get_call_by_session(session_id)
    if call:
        call.state = CallState.AI_CONVERSATION
        call.conference_name = None

    # Notify dashboard
    await dashboard_callback(session_id, {
        "type": "returned_to_ai",
        "session_id": session_id
    })

    # Generate TwiML to reconnect to AI
    twiml = twilio_voice.generate_return_to_ai_twiml(session_id, message)
    return Response(content=twiml, media_type="application/xml")


@router.post("/conference-status")
async def conference_status(
    session_id: str = Query(...),
    ConferenceSid: str = Form(None),
    StatusCallbackEvent: str = Form(None),
    FriendlyName: str = Form(None)
):
    """Handle conference status events."""
    logger.info(f"[{session_id}] Conference event: {StatusCallbackEvent} ({FriendlyName})")

    if StatusCallbackEvent == "conference-end":
        logger.info(f"[{session_id}] Conference ended")
        call = twilio_voice.get_call_by_session(session_id)
        if call:
            # Only mark as ended if we're not returning to AI
            if call.state != CallState.AI_CONVERSATION:
                call.state = CallState.ENDED
                twilio_voice.cleanup_call(call.call_sid)

                await dashboard_callback(session_id, {
                    "type": "call_ended",
                    "session_id": session_id
                })

    return {"status": "ok"}


@router.post("/status")
async def call_status(
    session_id: str = Query(None),
    CallSid: str = Form(...),
    CallStatus: str = Form(...),
    CallDuration: Optional[int] = Form(None)
):
    """Handle main call status updates."""
    logger.info(f"[{session_id or 'unknown'}] Call status: {CallStatus} (duration: {CallDuration})")

    if CallStatus == "completed":
        if session_id:
            call = twilio_voice.get_call_by_session(session_id)
            if call:
                twilio_voice.cleanup_call(call.call_sid)

            await dashboard_callback(session_id, {
                "type": "call_ended",
                "session_id": session_id,
                "duration": CallDuration
            })

    return {"status": "ok"}


# ==================== Media Stream WebSocket ====================

@router.websocket("/media-stream")
async def media_stream_websocket(websocket: WebSocket):
    """
    Handle Twilio Media Stream WebSocket connection.

    This receives audio from Twilio and sends audio back.
    """
    await websocket.accept()
    logger.info("[MEDIA] WebSocket connection accepted")

    stream_sid = None
    call_sid = None
    session_id = None

    try:
        async for message in websocket.iter_text():
            data = json.loads(message)
            event = data.get("event")

            if event == "connected":
                logger.info("[MEDIA] Stream connected")

            elif event == "start":
                # Stream started - extract metadata
                start_data = data.get("start", {})
                stream_sid = data.get("streamSid")
                call_sid = start_data.get("callSid")

                # Get custom parameters
                custom_params = start_data.get("customParameters", {})
                session_id = custom_params.get("session_id")
                is_resumed = custom_params.get("resumed") == "true"

                logger.info(f"[{session_id}] Stream started: {stream_sid} (resumed={is_resumed})")

                # Register the stream
                if call_sid:
                    twilio_voice.register_stream(stream_sid, call_sid)

                # Get or find the call
                call = twilio_voice.get_call(call_sid)
                if not call:
                    # For resumed sessions, try to find by session_id
                    call = twilio_voice.get_call_by_session(session_id)
                    if call:
                        # Update the stream mapping
                        call.stream_sid = stream_sid
                        twilio_voice._stream_to_call[stream_sid] = call.call_sid

                if call:
                    # Notify dashboard
                    await dashboard_callback(session_id, {
                        "type": "stream_started" if not is_resumed else "stream_resumed",
                        "session_id": session_id,
                        "stream_sid": stream_sid,
                        "resumed": is_resumed
                    })

                    from app.services.audio_processor import audio_processor
                    from app.services.conversation import conversation_service
                    from datetime import datetime

                    if is_resumed:
                        # Resumed session - send a "I'm back" message
                        # The message was already spoken by TwiML, so we just need to
                        # send a short prompt to continue the conversation
                        logger.info(f"[{session_id}] Session resumed from escalation")
                        resume_text = "How else can I help you today?"

                        # Add to transcript
                        call.transcript.append({
                            "role": "assistant",
                            "content": resume_text,
                            "timestamp": datetime.utcnow().isoformat()
                        })
                        await dashboard_callback(session_id, {
                            "type": "transcript",
                            "role": "assistant",
                            "content": resume_text
                        })

                        # Synthesize and send
                        resume_audio = await audio_processor.synthesize(resume_text)
                        if resume_audio:
                            await send_audio_to_stream(websocket, stream_sid, resume_audio, session_id)
                    else:
                        # New session - generate welcome message through the agent
                        try:
                            result = await conversation_service.process_voice_message(
                                session_id=session_id,
                                user_message="[CALL_STARTED]"  # Special marker for initial greeting
                            )
                            welcome_text = result.get("response", "Hello! Welcome to Springfield Auto. How can I help you today?")
                        except Exception as e:
                            logger.error(f"[{session_id}] Failed to generate welcome: {e}")
                            welcome_text = "Hello! Welcome to Springfield Auto. How can I help you today?"

                        # Add to local transcript for dashboard display
                        call.transcript.append({
                            "role": "assistant",
                            "content": welcome_text,
                            "timestamp": datetime.utcnow().isoformat()
                        })
                        await dashboard_callback(session_id, {
                            "type": "transcript",
                            "role": "assistant",
                            "content": welcome_text
                        })

                        # Synthesize welcome message (using Kokoro with default voice)
                        welcome_audio = await audio_processor.synthesize(welcome_text)
                        if welcome_audio:
                            # Send audio back to Twilio
                            await send_audio_to_stream(websocket, stream_sid, welcome_audio, session_id)
                        else:
                            logger.error(f"[{session_id}] Failed to synthesize welcome audio")

            elif event == "media":
                # Audio data received
                media = data.get("media", {})
                payload = media.get("payload")

                if payload and stream_sid:
                    try:
                        # Check for pending events first (real-time status updates)
                        # These trigger immediately with barge-in support
                        while twilio_voice.has_pending_events(session_id):
                            event_data = twilio_voice.pop_pending_event(session_id)
                            if event_data:
                                logger.info(f"[{session_id}] Processing pending event: {event_data['type']}")
                                await process_event_message(websocket, stream_sid, session_id, event_data)

                        # Process audio chunk (VAD + STT + LLM + TTS)
                        response_audio = await twilio_voice.process_audio_chunk(stream_sid, payload)

                        if response_audio:
                            # Send response audio back to Twilio (with barge-in support)
                            result = await send_audio_to_stream(websocket, stream_sid, response_audio, session_id)
                            if result == "barged_in":
                                # Audio was interrupted, process pending events
                                logger.info(f"[{session_id}] Audio barged-in, processing events")
                                twilio_voice.clear_barge_in(session_id)
                                while twilio_voice.has_pending_events(session_id):
                                    event_data = twilio_voice.pop_pending_event(session_id)
                                    if event_data:
                                        await process_event_message(websocket, stream_sid, session_id, event_data)
                            elif not result:
                                logger.warning(f"[{session_id}] Failed to send response audio")

                            # Check if call should end after farewell message
                            call = twilio_voice.get_call_by_session(session_id)
                            if call and call.state == CallState.ENDED:
                                logger.info(f"[{session_id}] Farewell played, ending call after delay")
                                # Wait a moment for audio to finish playing, then disconnect
                                await asyncio.sleep(2)
                                await twilio_voice.end_call(session_id)
                    except Exception as e:
                        logger.error(f"[{session_id}] Error processing audio: {e}")
                        # Try to send an error message to the user
                        await send_error_audio(websocket, stream_sid, session_id)

            elif event == "stop":
                logger.info(f"[{session_id}] Stream stopped")
                if call_sid:
                    call = twilio_voice.get_call(call_sid)
                    if call:
                        # Only mark as ENDED if we're not escalating to conference
                        # During escalation, the call continues in conference
                        if call.state not in (CallState.ESCALATING, CallState.IN_CONFERENCE):
                            call.state = CallState.ENDED

                await dashboard_callback(session_id, {
                    "type": "stream_ended",
                    "session_id": session_id
                })
                break

    except WebSocketDisconnect:
        logger.info(f"[{session_id}] WebSocket disconnected")
    except Exception as e:
        logger.error(f"[{session_id}] WebSocket error: {e}", exc_info=True)
    finally:
        # Only cleanup the call if we're not in an escalation scenario
        # During escalation, the call continues in conference and we need to track it
        if call_sid:
            call = twilio_voice.get_call(call_sid)
            if call and call.state in (CallState.ESCALATING, CallState.IN_CONFERENCE):
                logger.info(f"[{session_id}] Stream ended but call in conference, not cleaning up")
            else:
                twilio_voice.cleanup_call(call_sid)
        logger.info(f"[{session_id}] Media stream ended")


async def send_audio_to_stream(websocket: WebSocket, stream_sid: str, audio_data: bytes, session_id: str = None) -> bool:
    """
    Send audio data to Twilio media stream with barge-in support.

    Twilio expects mulaw 8kHz audio in base64.
    The audio_data is MP3, so we need to convert it.

    Returns True if audio was sent successfully, "barged_in" if interrupted.
    """
    try:
        # Convert MP3 to mulaw using pydub (if available) or ffmpeg
        mulaw_audio = await convert_to_mulaw(audio_data)

        if not mulaw_audio:
            logger.error("Audio conversion returned None - pydub/ffmpeg may not be installed")
            return False

        # Mark that we're playing audio (for barge-in detection)
        if session_id:
            twilio_voice.set_playing_audio(session_id, True)

        # Send in chunks (Twilio expects ~20ms chunks = 160 bytes at 8kHz)
        chunk_size = 160
        chunks_sent = 0
        barged_in = False

        for i in range(0, len(mulaw_audio), chunk_size):
            # Check for barge-in request
            if session_id and twilio_voice.should_barge_in(session_id):
                logger.info(f"[{session_id}] Barge-in detected! Stopping audio playback at chunk {chunks_sent}")
                barged_in = True
                # Send clear message to Twilio to stop any buffered audio
                clear_message = {
                    "event": "clear",
                    "streamSid": stream_sid
                }
                if websocket.client_state == WebSocketState.CONNECTED:
                    await websocket.send_json(clear_message)
                break

            chunk = mulaw_audio[i:i + chunk_size]
            payload = base64.b64encode(chunk).decode('utf-8')

            message = {
                "event": "media",
                "streamSid": stream_sid,
                "media": {
                    "payload": payload
                }
            }

            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.send_json(message)
                chunks_sent += 1
            else:
                logger.warning(f"WebSocket disconnected after {chunks_sent} chunks")
                if session_id:
                    twilio_voice.set_playing_audio(session_id, False)
                return False

            # Small delay to prevent overwhelming
            await asyncio.sleep(0.02)

        # Mark that we're done playing audio
        if session_id:
            twilio_voice.set_playing_audio(session_id, False)

        if barged_in:
            logger.debug(f"Audio interrupted after {chunks_sent} chunks")
            return "barged_in"

        logger.debug(f"Sent {chunks_sent} audio chunks to stream")
        return True

    except Exception as e:
        logger.error(f"Error sending audio to stream: {e}")
        if session_id:
            twilio_voice.set_playing_audio(session_id, False)
        return False


async def send_error_audio(websocket: WebSocket, stream_sid: str, session_id: str):
    """
    Send an error message audio to the user when processing fails.
    """
    try:
        from app.services.audio_processor import audio_processor
        error_text = "I'm sorry, I had trouble processing that. Could you please repeat?"
        error_audio = await audio_processor.synthesize(error_text)
        if error_audio:
            await send_audio_to_stream(websocket, stream_sid, error_audio, session_id)
    except Exception as e:
        logger.error(f"[{session_id}] Failed to send error audio: {e}")


async def process_event_message(websocket: WebSocket, stream_sid: str, session_id: str, event_data: dict):
    """
    Process a real-time event and speak it to the customer.

    This is used for immediate notifications like human call status updates.
    The message is spoken directly without going through the full LLM pipeline.
    """
    from app.services.audio_processor import audio_processor
    from datetime import datetime

    event_type = event_data.get("type", "unknown")
    message = event_data.get("message", "")

    if not message:
        logger.warning(f"[{session_id}] Event {event_type} has no message, skipping")
        return

    logger.info(f"[{session_id}] Speaking event message: {message[:50]}...")

    # Get call for transcript updates
    call = twilio_voice.get_call_by_session(session_id)

    # Add to transcript
    if call:
        call.transcript.append({
            "role": "assistant",
            "content": f"[{event_type}] {message}",
            "timestamp": datetime.utcnow().isoformat()
        })

    # Notify dashboard
    await dashboard_callback(session_id, {
        "type": "event_message",
        "event_type": event_type,
        "session_id": session_id,
        "content": message
    })

    # Synthesize and speak
    try:
        audio = await audio_processor.synthesize(message)
        if audio:
            await send_audio_to_stream(websocket, stream_sid, audio, session_id)
        else:
            logger.error(f"[{session_id}] Failed to synthesize event message")
    except Exception as e:
        logger.error(f"[{session_id}] Error processing event message: {e}")


async def convert_to_mulaw(mp3_data: bytes) -> Optional[bytes]:
    """
    Convert MP3 to mulaw 8kHz for Twilio.

    Uses pydub if available, otherwise falls back to audioop.
    """
    try:
        # Try using pydub (requires ffmpeg)
        from pydub import AudioSegment
        import io

        # Load MP3
        audio = AudioSegment.from_mp3(io.BytesIO(mp3_data))

        # Convert to 8kHz mono
        audio = audio.set_frame_rate(8000).set_channels(1)

        # Export as raw mulaw
        mulaw_buffer = io.BytesIO()
        audio.export(mulaw_buffer, format="mulaw", codec="pcm_mulaw")
        mulaw_buffer.seek(0)

        return mulaw_buffer.read()

    except ImportError:
        logger.warning("pydub not available, audio conversion may not work")
        return None
    except Exception as e:
        logger.error(f"Audio conversion error: {e}")
        return None
