"""
Twilio webhook routes for customer service escalation.

These endpoints handle:
- Voice webhooks (TwiML responses)
- Call status updates
- AMD (Answering Machine Detection) callbacks
- Error fallbacks
"""
import logging
from typing import Optional
from fastapi import APIRouter, Form, Query, Response
from fastapi.responses import PlainTextResponse

from app.services.twilio_service import twilio_service, CallStatus, AMDResult
from app.background.state_store import state_store
from app.schemas.task import Notification, NotificationPriority
from datetime import datetime

logger = logging.getLogger("app.api.twilio")

router = APIRouter(prefix="/twilio", tags=["twilio"])


@router.post("/voice", response_class=PlainTextResponse)
async def twilio_voice_webhook(
    session_id: str = Query(..., description="Session ID for the call"),
    CallSid: str = Form(None),
    CallStatus: str = Form(None),
    AnsweredBy: str = Form(None)
):
    """
    Twilio voice webhook - returns TwiML for call handling.

    Called when:
    - Call is answered (initial webhook)
    - After AMD completes (if synchronous)

    Returns TwiML that:
    - Plays intro message to human agent
    - Bridges call to LiveKit via SIP
    """
    logger.info(
        f"[{session_id}] Voice webhook: CallSid={CallSid}, "
        f"Status={CallStatus}, AnsweredBy={AnsweredBy}"
    )

    # Check if this is voicemail/machine
    pending = twilio_service.get_pending_call(CallSid) if CallSid else None

    # Only hang up for definite machine detection (machine_*, fax)
    # Treat "unknown" and "human" as human - proceed with call
    if pending and pending.amd_result:
        amd_value = pending.amd_result.value if hasattr(pending.amd_result, 'value') else str(pending.amd_result)
        is_machine = amd_value.startswith("machine") or amd_value == "fax"
        if is_machine:
            logger.info(f"[{session_id}] Machine detected ({amd_value}), hanging up")
            return twilio_service.generate_voicemail_twiml(session_id)
        else:
            logger.info(f"[{session_id}] AMD result '{amd_value}' - treating as human")

    # Human answered (or AMD not yet complete or unknown) - proceed with bridging
    twiml = twilio_service.generate_voice_twiml(session_id, CallSid)
    logger.info(f"[{session_id}] === RETURNING TWIML TO TWILIO ===")
    logger.info(f"[{session_id}] TwiML content:\n{twiml}")

    return Response(content=twiml, media_type="application/xml")


@router.post("/status")
async def twilio_status_webhook(
    session_id: str = Query(..., description="Session ID for the call"),
    CallSid: str = Form(...),
    CallStatus: str = Form(...),
    CallDuration: Optional[int] = Form(None),
    Timestamp: Optional[str] = Form(None)
):
    """
    Twilio call status callback.

    Handles status transitions:
    - initiated: Call is being placed
    - ringing: Phone is ringing
    - in-progress: Call answered
    - completed: Call ended normally
    - busy/no-answer/failed/canceled: Call didn't connect
    """
    logger.info(
        f"[{session_id}] Status webhook: CallSid={CallSid}, "
        f"Status={CallStatus}, Duration={CallDuration}"
    )

    result = twilio_service.handle_call_status(
        call_sid=CallSid,
        call_status=CallStatus,
        duration=CallDuration
    )

    # Send notification to customer for terminal states
    if CallStatus in ["busy", "no-answer", "failed", "canceled"]:
        await _send_call_failed_notification(session_id, CallStatus)

    return {"status": "ok", **result}


@router.post("/amd")
async def twilio_amd_webhook(
    session_id: str = Query(..., description="Session ID for the call"),
    CallSid: str = Form(...),
    AnsweredBy: str = Form(...),
    MachineDetectionDuration: Optional[int] = Form(None)
):
    """
    Twilio AMD (Answering Machine Detection) async callback.

    Called when AMD determines if human or machine answered:
    - human: Real person answered
    - machine_start: Machine/voicemail detected at start
    - machine_end_beep: Voicemail beep detected
    - machine_end_silence: Voicemail ended with silence
    - machine_end_other: Other machine end detection
    - fax: Fax machine detected
    - unknown: Couldn't determine
    """
    logger.info(
        f"[{session_id}] AMD webhook: CallSid={CallSid}, "
        f"AnsweredBy={AnsweredBy}, Duration={MachineDetectionDuration}"
    )

    result = twilio_service.handle_amd_result(
        call_sid=CallSid,
        answered_by=AnsweredBy,
        machine_detection_duration=MachineDetectionDuration
    )

    # If definite machine detected, send notification
    # Treat "unknown" as human since we can't be sure
    is_machine = AnsweredBy.startswith("machine") or AnsweredBy == "fax"

    if is_machine:
        await _send_voicemail_notification(session_id, AnsweredBy)

        # Cancel the call if it's a machine
        pending = twilio_service.get_pending_call(CallSid)
        if pending and pending.status in [CallStatus.INITIATED, CallStatus.RINGING]:
            # The call will be hung up via the voice webhook returning hangup TwiML
            logger.info(f"[{session_id}] Machine detected, call will be terminated")
    else:
        # unknown or human - proceed with call
        logger.info(f"[{session_id}] AMD result '{AnsweredBy}' - treating as human, proceeding")

    return {"status": "ok", **result}


@router.post("/fallback", response_class=PlainTextResponse)
async def twilio_fallback_webhook(
    session_id: str = Query(None, description="Session ID for the call"),
    ErrorCode: Optional[str] = Form(None),
    ErrorUrl: Optional[str] = Form(None)
):
    """
    Twilio error fallback webhook.

    Called when the primary voice webhook fails.
    Returns TwiML that apologizes and hangs up.
    """
    logger.error(
        f"[{session_id}] Fallback webhook triggered: "
        f"ErrorCode={ErrorCode}, ErrorUrl={ErrorUrl}"
    )

    if session_id:
        await _send_error_notification(session_id)

    return Response(
        content=twilio_service.generate_fallback_twiml(),
        media_type="application/xml"
    )


async def _send_call_failed_notification(session_id: str, status: str):
    """Send notification when call fails to connect - no hardcoded message."""
    notification = Notification(
        notification_id=f"notif_cs_{int(datetime.utcnow().timestamp() * 1000)}",
        task_id=f"cs_{session_id}",
        data={"type": "call_failed", "status": status},  # Agent generates message
        priority=NotificationPriority.HIGH
    )

    await state_store.append_notification_atomic(session_id, notification)
    logger.info(f"[{session_id}] Sent call failed notification: {status}")


async def _send_voicemail_notification(session_id: str, amd_result: str):
    """Send notification when voicemail is detected - no hardcoded message."""
    notification = Notification(
        notification_id=f"notif_vm_{int(datetime.utcnow().timestamp() * 1000)}",
        task_id=f"cs_{session_id}",
        data={"type": "voicemail_detected", "amd_result": amd_result},  # Agent generates message
        priority=NotificationPriority.HIGH
    )

    await state_store.append_notification_atomic(session_id, notification)
    logger.info(f"[{session_id}] Sent voicemail notification: {amd_result}")


async def _send_error_notification(session_id: str):
    """Send notification when there's a call error - no hardcoded message."""
    notification = Notification(
        notification_id=f"notif_err_{int(datetime.utcnow().timestamp() * 1000)}",
        task_id=f"cs_{session_id}",
        data={"type": "connection_error"},  # Agent generates message
        priority=NotificationPriority.HIGH
    )

    await state_store.append_notification_atomic(session_id, notification)
    logger.info(f"[{session_id}] Sent error notification")
