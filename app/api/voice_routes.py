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

from twilio.twiml.voice_response import VoiceResponse

from app.config import get_settings
from app.services.twilio_voice import twilio_voice, CallState, HumanCallStatus
from app.background.state_store import state_store
from app.api.websocket import get_ws_manager

settings = get_settings()

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
async def human_answer_webhook(
    session_id: str = Query(...),
    conference: str = Query(...),
    reason: str = Query("assistance"),
    customer_name: str = Query("Customer"),
    CallSid: str = Form(None),
    CallStatus: str = Form(None)
):
    """
    Called when Twilio connects the outbound call to human agent.

    IMPORTANT: This fires when Twilio detects the call is "answered", but this
    could be triggered by call screening or early media - NOT necessarily a real human!

    New flow with confirmation:
    1. Call connects (could be call screening) -> this endpoint is called
    2. We return TwiML that asks "Press 1 to accept this call"
    3. If human presses 1 -> /human-confirmed is called
    4. Only THEN do we transfer customer to conference
    """
    logger.info(f"[{session_id}] === HUMAN ANSWER WEBHOOK (waiting for confirmation) ===")
    logger.info(f"[{session_id}] Conference: {conference}, CallStatus: {CallStatus}, CallSid: {CallSid}")
    logger.info(f"[{session_id}] Reason: {reason}, CustomerName: {customer_name}")

    # DON'T notify dashboard as "answered" yet - wait for confirmation!
    # The status callback will send "waiting_confirmation" status

    # Generate TwiML that asks human to press 1 to confirm
    # This prevents call screening from falsely triggering transfer
    twiml = twilio_voice.generate_human_confirmation_twiml(
        session_id=session_id,
        conference_name=conference,
        customer_name=customer_name,
        reason=reason
    )

    logger.info(f"[{session_id}] Returning confirmation TwiML (press 1 to accept)")
    return Response(content=twiml, media_type="application/xml")


@router.post("/human-amd")
async def human_amd_result(
    session_id: str = Query(...),
    CallSid: str = Form(...),
    AnsweredBy: str = Form(...),
    MachineDetectionDuration: Optional[int] = Form(None)
):
    """
    Handle AMD (Answering Machine Detection) result for human call.

    AnsweredBy values:
    - "human": Real person answered
    - "machine_start": Machine/voicemail detected at start
    - "machine_end_beep": Voicemail beep detected (ready to leave message)
    - "machine_end_silence": Voicemail ended with silence
    - "machine_end_other": Other machine detection
    - "fax": Fax machine
    - "unknown": Couldn't determine
    """
    logger.info(f"[{session_id}] AMD result: AnsweredBy={AnsweredBy}, Duration={MachineDetectionDuration}ms")

    # If it's a machine/voicemail, hang up - no point leaving a message
    is_machine = AnsweredBy.startswith("machine") or AnsweredBy == "fax"

    if is_machine:
        logger.info(f"[{session_id}] AMD detected machine/voicemail - call will play to voicemail then hang up")
        # Update status to show it went to voicemail
        await dashboard_callback(session_id, {
            "type": "human_status",
            "session_id": session_id,
            "status": "voicemail"
        })
    elif AnsweredBy == "human":
        logger.info(f"[{session_id}] AMD confirmed human answered")
        # Human confirmed by AMD - the Gather TwiML should be playing now
    else:
        logger.info(f"[{session_id}] AMD result unknown: {AnsweredBy}")

    return {"status": "ok", "answered_by": AnsweredBy}


@router.post("/human-detected")
async def human_detected(
    session_id: str = Query(...),
    conference: str = Query(...),
    customer_name: str = Query("Customer"),
    reason: str = Query("assistance"),
    CallSid: str = Form(None),
    Digits: str = Form(None)
):
    """
    Called when someone presses ANY key - proves a human is on the line.

    This defeats call screening because:
    - Call screening just records and never presses keys
    - Real humans hear "press any key" and do so

    Now we play the full message and ask them to press 1 to accept.
    """
    logger.info(f"[{session_id}] === HUMAN DETECTED (pressed: {Digits}) ===")

    # Update status - we know a human is there now
    await dashboard_callback(session_id, {
        "type": "human_status",
        "session_id": session_id,
        "status": "waiting_confirmation"
    })

    # Now play the full message and ask for confirmation
    response = VoiceResponse()

    confirm_url = (
        f"{settings.twilio_webhook_base_url}/api/voice/human-confirmed"
        f"?session_id={session_id}&conference={conference}"
    )

    from twilio.twiml.voice_response import Gather
    gather = Gather(
        num_digits=1,
        action=confirm_url,
        method="POST",
        timeout=10
    )
    gather.say(
        f"You have an incoming customer call. {customer_name} needs help with {reason}. "
        "Press 1 to accept, or any other key to decline.",
        voice="Polly.Matthew"
    )
    response.append(gather)

    # If no response, hang up
    response.say("No response. Goodbye.", voice="Polly.Matthew")
    response.hangup()

    return Response(content=str(response), media_type="application/xml")


@router.post("/human-confirmed")
async def human_confirmed(
    session_id: str = Query(...),
    conference: str = Query(...),
    CallSid: str = Form(None),
    Digits: str = Form(None)
):
    """
    Called when human presses a digit to accept or decline the call.
    """
    logger.info(f"[{session_id}] === HUMAN CONFIRMATION: {Digits} ===")

    if Digits == "1":
        # Human accepted!
        logger.info(f"[{session_id}] Human pressed 1 - ACCEPTED! Connecting to conference")

        # Update status and trigger customer transfer
        await twilio_voice.handle_human_confirmed(session_id)

        # Generate TwiML to add human to conference
        twiml = twilio_voice.generate_human_join_conference_twiml(
            session_id=session_id,
            conference_name=conference
        )

        return Response(content=twiml, media_type="application/xml")
    else:
        # Human declined
        logger.info(f"[{session_id}] Human pressed '{Digits}' - DECLINED")

        # Update state and notify dashboard (this also clears escalation state)
        await twilio_voice.handle_human_declined(session_id)

        # Hang up the human call
        response = VoiceResponse()
        response.say("Call declined. Goodbye.", voice="Polly.Matthew")
        response.hangup()

        return Response(content=str(response), media_type="application/xml")


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
    reason: str = Query("unavailable"),
    CallSid: str = Form(None)
):
    """
    Return customer to AI conversation after escalation fails or human is unavailable.

    This endpoint is called when we need to redirect the customer from conference back to AI.
    No hardcoded messages - AI agent handles all responses.
    """
    logger.info(f"[{session_id}] Returning to AI conversation (reason: {reason})")

    # Update call state
    call = twilio_voice.get_call_by_session(session_id)
    if call:
        call.state = CallState.AI_CONVERSATION
        call.conference_name = None
        call.escalation_return_reason = reason

    # Notify dashboard
    await dashboard_callback(session_id, {
        "type": "returned_to_ai",
        "session_id": session_id,
        "reason": reason
    })

    # Generate TwiML to reconnect to AI - no hardcoded message
    twiml = twilio_voice.generate_return_to_ai_twiml(session_id)
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

async def event_poller(websocket: WebSocket, stream_sid: str, session_id: str):
    """
    Background task that polls for pending events (like escalation status changes)
    and triggers proactive AI responses.

    This allows the AI to speak to the customer without waiting for their input.
    """
    from app.services.audio_processor import audio_processor
    from app.services.conversation import conversation_service
    from starlette.websockets import WebSocketState

    logger.info(f"[{session_id}] Event poller started")

    try:
        while True:
            await asyncio.sleep(1)  # Check every second

            # Check if websocket is still connected
            if websocket.client_state != WebSocketState.CONNECTED:
                logger.info(f"[{session_id}] Event poller: WebSocket disconnected, stopping")
                break

            # Check for pending events
            event = twilio_voice.pop_pending_event(session_id)
            if event:
                event_type = event.get("type", "")
                event_message = event.get("message", "")

                logger.info(f"[{session_id}] Event poller: Processing event {event_type}: {event_message[:50]}...")

                try:
                    # Process through AI to generate natural response
                    result = await conversation_service.process_voice_message(
                        session_id=session_id,
                        user_message=event_message  # e.g., "[ESCALATION_RETURNED:no-answer]"
                    )
                    response_text = result.get("response", "")

                    if response_text:
                        logger.info(f"[{session_id}] Event poller: AI response: '{response_text[:50]}...'")

                        # Get call for transcript
                        call = twilio_voice.get_call_by_session(session_id)
                        if call:
                            from datetime import datetime
                            call.transcript.append({
                                "role": "assistant",
                                "content": response_text,
                                "timestamp": datetime.utcnow().isoformat()
                            })
                            await dashboard_callback(session_id, {
                                "type": "transcript",
                                "role": "assistant",
                                "content": response_text
                            })

                        # Synthesize and send audio
                        response_audio = await audio_processor.synthesize(response_text)
                        if response_audio and stream_sid:
                            await send_audio_to_stream(websocket, stream_sid, response_audio, session_id)
                            logger.info(f"[{session_id}] Event poller: Proactive message sent")
                except Exception as e:
                    logger.error(f"[{session_id}] Event poller error processing event: {e}")

    except asyncio.CancelledError:
        logger.info(f"[{session_id}] Event poller cancelled")
    except Exception as e:
        logger.error(f"[{session_id}] Event poller error: {e}")
    finally:
        logger.info(f"[{session_id}] Event poller stopped")


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
    event_poller_task = None

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
                        # Resumed session - let AI agent generate appropriate response
                        # based on the escalation_return_reason
                        logger.info(f"[{session_id}] Session resumed from escalation")

                        # Get the return reason from the call
                        return_reason = call.escalation_return_reason or "unavailable"

                        # Let the agent generate the appropriate response
                        try:
                            result = await conversation_service.process_voice_message(
                                session_id=session_id,
                                user_message=f"[ESCALATION_RETURNED:{return_reason}]"  # Special marker for agent
                            )
                            resume_text = result.get("response", "")
                        except Exception as e:
                            logger.error(f"[{session_id}] Failed to generate resume message: {e}")
                            resume_text = ""

                        if resume_text:
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

                        # Clear the return reason after handling
                        call.escalation_return_reason = None
                    else:
                        # New session - generate welcome message through the agent
                        # No hardcoded fallback - agent must generate all messages
                        try:
                            result = await conversation_service.process_voice_message(
                                session_id=session_id,
                                user_message="[CALL_STARTED]"  # Special marker for initial greeting
                            )
                            welcome_text = result.get("response", "")
                        except Exception as e:
                            logger.error(f"[{session_id}] Failed to generate welcome: {e}")
                            welcome_text = ""

                        if welcome_text:
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
                        else:
                            logger.warning(f"[{session_id}] Agent returned empty welcome message")

                    # Start event poller to handle proactive messages (escalation results, etc.)
                    if event_poller_task is None:
                        event_poller_task = asyncio.create_task(
                            event_poller(websocket, stream_sid, session_id)
                        )
                        logger.info(f"[{session_id}] Event poller task started")

            elif event == "media":
                # Audio data received
                media = data.get("media", {})
                payload = media.get("payload")

                if payload and stream_sid:
                    try:
                        # Process audio chunk (VAD + STT + LLM + TTS)
                        # All messages are generated by the AI agent - no hardcoded messages
                        response_audio = await twilio_voice.process_audio_chunk(stream_sid, payload)

                        if response_audio:
                            # Send response audio back to Twilio (with barge-in support)
                            result = await send_audio_to_stream(websocket, stream_sid, response_audio, session_id)
                            if result == "barged_in":
                                logger.info(f"[{session_id}] Audio barged-in by user")
                                twilio_voice.clear_barge_in(session_id)
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
                        # Let agent handle error - no hardcoded error message
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
        logger.info(f"[{session_id}] WebSocket disconnected unexpectedly")
        # Customer likely hung up - notify dashboard
        if session_id:
            await dashboard_callback(session_id, {
                "type": "call_ended",
                "session_id": session_id,
                "reason": "customer_disconnected"
            })
    except Exception as e:
        logger.error(f"[{session_id}] WebSocket error: {e}", exc_info=True)
        # Also notify dashboard on errors
        if session_id:
            await dashboard_callback(session_id, {
                "type": "call_ended",
                "session_id": session_id,
                "reason": "error"
            })
    finally:
        # Cancel the event poller task if running
        if event_poller_task is not None:
            event_poller_task.cancel()
            try:
                await event_poller_task
            except asyncio.CancelledError:
                pass
            logger.info(f"[{session_id}] Event poller task cancelled")

        # Only cleanup the call if we're not in an escalation scenario
        # During escalation, the call continues in conference and we need to track it
        if call_sid:
            call = twilio_voice.get_call(call_sid)
            if call and call.state in (CallState.ESCALATING, CallState.IN_CONFERENCE):
                logger.info(f"[{session_id}] Stream ended but call in conference, not cleaning up")
            else:
                twilio_voice.cleanup_call(call_sid)
                # Send call_ended if not already sent by stop event or exception handlers
                if session_id:
                    await dashboard_callback(session_id, {
                        "type": "call_ended",
                        "session_id": session_id,
                        "reason": "stream_ended"
                    })
        logger.info(f"[{session_id}] Media stream ended")


async def send_audio_to_stream(websocket: WebSocket, stream_sid: str, audio_data: bytes, session_id: str = None) -> bool:
    """
    Send audio data to Twilio media stream with barge-in support.

    Twilio expects mulaw 8kHz audio in base64.
    The audio_data is WAV (24kHz), converted using high-quality soxr resampling.

    Returns True if audio was sent successfully, "barged_in" if interrupted.
    """
    try:
        # Convert WAV to mulaw using high-quality soxr resampling
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
    Handle error during processing - let agent generate response.
    No hardcoded messages.
    """
    try:
        from app.services.audio_processor import audio_processor
        from app.services.conversation import conversation_service

        # Let agent generate error response
        result = await conversation_service.process_voice_message(
            session_id=session_id,
            user_message="[PROCESSING_ERROR]"  # Special marker for agent
        )
        error_text = result.get("response", "")

        if error_text:
            error_audio = await audio_processor.synthesize(error_text)
            if error_audio:
                await send_audio_to_stream(websocket, stream_sid, error_audio, session_id)
    except Exception as e:
        logger.error(f"[{session_id}] Failed to handle error: {e}")




async def convert_to_mulaw(wav_data: bytes) -> Optional[bytes]:
    """
    Convert WAV (24kHz) to mulaw 8kHz for Twilio using high-quality resampling.

    Uses soxr for high-quality resampling and audioop for mulaw encoding.
    This avoids the quality loss from MP3 intermediate conversion.
    """
    import io
    import wave
    import audioop
    import numpy as np
    import soxr

    try:
        # Parse WAV and extract PCM samples
        with io.BytesIO(wav_data) as wav_buffer:
            with wave.open(wav_buffer, 'rb') as wav:
                source_sample_rate = wav.getframerate()
                n_channels = wav.getnchannels()
                sample_width = wav.getsampwidth()
                frames = wav.readframes(wav.getnframes())

        # Convert to numpy array
        audio_int16 = np.frombuffer(frames, dtype=np.int16)

        # If stereo, convert to mono
        if n_channels == 2:
            audio_int16 = audio_int16.reshape(-1, 2).mean(axis=1).astype(np.int16)

        # Convert to float64 for high-quality resampling
        audio_float = audio_int16.astype(np.float64)

        # High-quality resample to 8kHz using soxr
        audio_8k = soxr.resample(audio_float, source_sample_rate, 8000, quality='HQ')

        # Normalize to prevent clipping
        max_val = np.max(np.abs(audio_8k))
        if max_val > 0:
            audio_8k = audio_8k * (32767 / max_val) * 0.95  # Leave headroom

        # Convert back to int16
        audio_8k_int16 = audio_8k.astype(np.int16)

        # Encode to mulaw using audioop
        mulaw_data = audioop.lin2ulaw(audio_8k_int16.tobytes(), 2)

        logger.debug(f"Converted {len(wav_data)} bytes WAV ({source_sample_rate}Hz) -> {len(mulaw_data)} bytes mulaw (8kHz)")
        return mulaw_data

    except Exception as e:
        logger.error(f"Audio conversion error: {e}")
        return None
