"""
Twilio service for customer service escalation via phone calls.

This service handles:
- Outbound calls to customer service with AMD (Answering Machine Detection)
- Webhook handling for call status and AMD results
- SIP bridge to LiveKit for call connection
"""
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger("app.services.twilio")


class CallStatus(str, Enum):
    """Twilio call status values."""
    INITIATED = "initiated"
    RINGING = "ringing"
    IN_PROGRESS = "in-progress"
    COMPLETED = "completed"
    BUSY = "busy"
    NO_ANSWER = "no-answer"
    CANCELED = "canceled"
    FAILED = "failed"


class AMDResult(str, Enum):
    """AMD detection results."""
    HUMAN = "human"
    MACHINE_START = "machine_start"
    MACHINE_END_BEEP = "machine_end_beep"
    MACHINE_END_SILENCE = "machine_end_silence"
    MACHINE_END_OTHER = "machine_end_other"
    FAX = "fax"
    UNKNOWN = "unknown"


@dataclass
class PendingCall:
    """Tracks a pending outbound call."""
    call_sid: str
    session_id: str
    customer_name: Optional[str]
    reason: Optional[str]
    created_at: datetime = field(default_factory=datetime.utcnow)
    status: CallStatus = CallStatus.INITIATED
    amd_result: Optional[AMDResult] = None
    answered_by_human: bool = False


class TwilioService:
    """
    Twilio client wrapper for customer service escalation.

    Handles outbound calls with AMD and SIP bridging to LiveKit.
    """

    def __init__(self):
        self._client = None
        self._pending_calls: Dict[str, PendingCall] = {}  # call_sid -> PendingCall
        self._session_to_call: Dict[str, str] = {}  # session_id -> call_sid

    @property
    def client(self):
        """Lazy-load Twilio client."""
        if self._client is None:
            if not settings.twilio_account_sid or not settings.twilio_auth_token:
                logger.warning("Twilio credentials not configured")
                return None

            from twilio.rest import Client
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
            settings.customer_service_phone and
            settings.twilio_webhook_base_url
        )

    async def initiate_call(
        self,
        session_id: str,
        customer_name: Optional[str] = None,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Initiate an outbound call to customer service with AMD.

        Args:
            session_id: The conversation session ID
            customer_name: Name of the customer requesting help
            reason: Reason for the escalation

        Returns:
            Dict with call_sid and status, or error info
        """
        if not self.is_configured:
            logger.error("Twilio is not properly configured")
            return {
                "success": False,
                "error": "Twilio not configured",
                "message": "Customer service phone escalation is not available"
            }

        if not self.client:
            return {
                "success": False,
                "error": "Twilio client initialization failed",
                "message": "Unable to connect to phone service"
            }

        try:
            # Build webhook URLs
            base_url = settings.twilio_webhook_base_url.rstrip('/')
            voice_url = f"{base_url}/api/twilio/voice?session_id={session_id}"
            status_url = f"{base_url}/api/twilio/status?session_id={session_id}"
            amd_url = f"{base_url}/api/twilio/amd?session_id={session_id}"
            fallback_url = f"{base_url}/api/twilio/fallback?session_id={session_id}"

            logger.info(f"[{session_id}] === INITIATING TWILIO CALL ===")
            logger.info(f"[{session_id}] To: {settings.customer_service_phone}")
            logger.info(f"[{session_id}] From: {settings.twilio_phone_number}")
            logger.info(f"[{session_id}] Voice URL: {voice_url}")
            logger.info(f"[{session_id}] Status URL: {status_url}")

            # Create outbound call
            # NOTE: AMD disabled - doesn't work well with Twilio trial accounts
            # (trial message "Press any key..." confuses AMD detection)
            # Re-enable for production with paid account:
            #   machine_detection="Enable",
            #   machine_detection_timeout=5,
            #   async_amd=True,
            #   async_amd_status_callback=amd_url,
            #   async_amd_status_callback_method="POST",
            call = self.client.calls.create(
                to=settings.customer_service_phone,
                from_=settings.twilio_phone_number,
                url=voice_url,
                status_callback=status_url,
                status_callback_event=["initiated", "ringing", "answered", "completed"],
                status_callback_method="POST",
                fallback_url=fallback_url,
                fallback_method="POST",
                timeout=30  # Ring for 30 seconds max
            )

            # Track the pending call
            pending = PendingCall(
                call_sid=call.sid,
                session_id=session_id,
                customer_name=customer_name,
                reason=reason
            )
            self._pending_calls[call.sid] = pending
            self._session_to_call[session_id] = call.sid

            logger.info(f"[{session_id}] Call initiated: {call.sid}")

            return {
                "success": True,
                "call_sid": call.sid,
                "status": call.status,
                "message": "Call initiated to customer service"
            }

        except Exception as e:
            logger.error(f"[{session_id}] Failed to initiate call: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Failed to connect to customer service"
            }

    def get_pending_call(self, call_sid: str) -> Optional[PendingCall]:
        """Get a pending call by SID."""
        return self._pending_calls.get(call_sid)

    def get_call_by_session(self, session_id: str) -> Optional[PendingCall]:
        """Get a pending call by session ID."""
        call_sid = self._session_to_call.get(session_id)
        if call_sid:
            return self._pending_calls.get(call_sid)
        return None

    def handle_amd_result(
        self,
        call_sid: str,
        answered_by: str,
        machine_detection_duration: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Process AMD (Answering Machine Detection) result.

        Args:
            call_sid: The Twilio call SID
            answered_by: AMD result (human, machine_start, etc.)
            machine_detection_duration: Time taken for detection in ms

        Returns:
            Dict with processing result
        """
        pending = self._pending_calls.get(call_sid)
        if not pending:
            logger.warning(f"AMD result for unknown call: {call_sid}")
            return {"success": False, "error": "Unknown call"}

        try:
            amd_result = AMDResult(answered_by)
        except ValueError:
            amd_result = AMDResult.UNKNOWN

        pending.amd_result = amd_result
        pending.answered_by_human = (amd_result == AMDResult.HUMAN)

        logger.info(
            f"[{pending.session_id}] AMD result: {answered_by} "
            f"(human={pending.answered_by_human}, duration={machine_detection_duration}ms)"
        )

        return {
            "success": True,
            "session_id": pending.session_id,
            "answered_by": answered_by,
            "is_human": pending.answered_by_human
        }

    def handle_call_status(
        self,
        call_sid: str,
        call_status: str,
        duration: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Process call status update from Twilio.

        Args:
            call_sid: The Twilio call SID
            call_status: New status (ringing, in-progress, completed, etc.)
            duration: Call duration in seconds (for completed calls)

        Returns:
            Dict with processing result
        """
        pending = self._pending_calls.get(call_sid)
        if not pending:
            logger.warning(f"Status update for unknown call: {call_sid}")
            return {"success": False, "error": "Unknown call"}

        try:
            status = CallStatus(call_status)
        except ValueError:
            logger.warning(f"Unknown call status: {call_status}")
            status = CallStatus.FAILED

        old_status = pending.status
        pending.status = status

        logger.info(
            f"[{pending.session_id}] Call status: {old_status.value} -> {status.value}"
            f"{f' (duration={duration}s)' if duration else ''}"
        )

        # Clean up completed/failed calls after processing
        if status in [CallStatus.COMPLETED, CallStatus.FAILED,
                      CallStatus.BUSY, CallStatus.NO_ANSWER, CallStatus.CANCELED]:
            self._cleanup_call(call_sid)

        return {
            "success": True,
            "session_id": pending.session_id,
            "old_status": old_status.value,
            "new_status": status.value,
            "duration": duration
        }

    def _cleanup_call(self, call_sid: str):
        """Remove a call from pending tracking."""
        pending = self._pending_calls.pop(call_sid, None)
        if pending:
            self._session_to_call.pop(pending.session_id, None)
            logger.info(f"[{pending.session_id}] Call cleaned up: {call_sid}")

    @property
    def is_sip_configured(self) -> bool:
        """Check if LiveKit SIP is properly configured."""
        return bool(
            settings.livekit_sip_host and
            settings.livekit_sip_trunk_username and
            settings.livekit_sip_trunk_password
        )

    def generate_voice_twiml(
        self,
        session_id: str,
        call_sid: Optional[str] = None
    ) -> str:
        """
        Generate TwiML for when human answers the call.

        This plays an intro message and then either:
        - Bridges to LiveKit via SIP (if configured)
        - Or plays a message and records (fallback mode)

        Args:
            session_id: The conversation session ID
            call_sid: Optional call SID to look up context

        Returns:
            TwiML XML string
        """
        # Get call context
        pending = None
        if call_sid:
            pending = self._pending_calls.get(call_sid)
        elif session_id:
            pending = self.get_call_by_session(session_id)

        customer_name = pending.customer_name if pending else "A customer"
        reason = pending.reason if pending else "assistance"

        # Check if SIP is configured
        if not self.is_sip_configured:
            logger.warning(f"[{session_id}] SIP not configured, using fallback TwiML")
            # Fallback: No voice message, just hang up
            # The AI agent will handle informing the customer
            return """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Hangup/>
</Response>"""

        # Build SIP URI for LiveKit
        # Format: sip:{session_id}@{livekit_sip_host}
        # NOTE: Room name must match the customer's room (just session_id, no prefix)
        sip_uri = f"sip:{session_id}@{settings.livekit_sip_host}"

        logger.info(f"[{session_id}] === GENERATING SIP TWIML ===")
        logger.info(f"[{session_id}] SIP URI: {sip_uri}")
        logger.info(f"[{session_id}] SIP Host: {settings.livekit_sip_host}")
        logger.info(f"[{session_id}] SIP Username: {settings.livekit_sip_trunk_username}")
        logger.info(f"[{session_id}] Customer: {customer_name}, Reason: {reason}")

        # Build TwiML with SIP bridge - no hardcoded voice messages
        # IMPORTANT: No extra whitespace in SIP URI - Twilio is sensitive to this
        twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Dial>
        <Sip username="{settings.livekit_sip_trunk_username}" password="{settings.livekit_sip_trunk_password}">{sip_uri}</Sip>
    </Dial>
</Response>'''

        return twiml

    def generate_voicemail_twiml(self, session_id: str) -> str:
        """
        Generate TwiML for when voicemail is detected.

        Just hangs up - we don't leave voicemails.
        """
        return """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Hangup/>
</Response>"""

    def generate_fallback_twiml(self) -> str:
        """Generate TwiML for error fallback - no hardcoded messages."""
        return """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Hangup/>
</Response>"""

    async def cancel_call(self, session_id: str) -> bool:
        """
        Cancel a pending call for a session.

        Args:
            session_id: The session ID

        Returns:
            True if call was cancelled, False otherwise
        """
        call_sid = self._session_to_call.get(session_id)
        if not call_sid:
            return False

        pending = self._pending_calls.get(call_sid)
        if not pending:
            return False

        # Only cancel if still ringing
        if pending.status not in [CallStatus.INITIATED, CallStatus.RINGING]:
            return False

        try:
            if self.client:
                self.client.calls(call_sid).update(status="canceled")
                logger.info(f"[{session_id}] Call cancelled: {call_sid}")
                self._cleanup_call(call_sid)
                return True
        except Exception as e:
            logger.error(f"[{session_id}] Failed to cancel call: {e}")

        return False


# Global singleton
twilio_service = TwilioService()
