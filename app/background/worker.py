import asyncio
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from typing import Optional, Callable, Awaitable
import logging

from app.config import get_settings
from app.schemas.task import (
    BackgroundTask, Notification, HumanCheckResult,
    TaskStatus, TaskType, NotificationPriority
)
from .state_store import state_store

settings = get_settings()
logger = logging.getLogger("app.background.worker")

# Sales ring timeout in seconds
SALES_RING_TIMEOUT = 30


class BackgroundWorker:
    """
    Handles async background tasks that don't block the conversation.
    """

    def __init__(self):
        self.notification_callback: Optional[Callable[[str, Notification], Awaitable[None]]] = None
        self.task_update_callback: Optional[Callable[[str, BackgroundTask], Awaitable[None]]] = None
        self._sales_manager = None

    def set_notification_callback(self, callback: Callable[[str, Notification], Awaitable[None]]):
        """Set callback for high-priority notifications."""
        self.notification_callback = callback

    def set_task_update_callback(self, callback: Callable[[str, BackgroundTask], Awaitable[None]]):
        """Set callback for task status updates."""
        self.task_update_callback = callback

    def _get_sales_manager(self):
        """Lazy load sales manager to avoid circular imports."""
        if self._sales_manager is None:
            from app.api.websocket import get_sales_manager
            self._sales_manager = get_sales_manager()
        return self._sales_manager

    async def _broadcast_task_update(self, session_id: str, task_id: str):
        """Broadcast task update via callback."""
        if self.task_update_callback:
            state = await state_store.get_state(session_id)
            if state:
                for task in state.pending_tasks:
                    if task.task_id == task_id:
                        await self.task_update_callback(session_id, task)
                        break

    async def execute_human_check(
        self,
        task_id: str,
        session_id: str,
        customer_name: Optional[str] = None,
        customer_phone: Optional[str] = None,
        reason: Optional[str] = None,
        urgency: str = "medium"
    ):
        """
        Execute human availability check as background task.

        This rings the sales dashboard and waits for a response:
        1. If sales accepts: bridge the call
        2. If sales declines or times out: schedule callback and send email
        """

        # Update task status to running
        await state_store.update_task_atomic(session_id, task_id, {
            "status": TaskStatus.RUNNING
        })
        await self._broadcast_task_update(session_id, task_id)

        # Get sales manager
        sales_mgr = self._get_sales_manager()

        # Ring sales dashboard and wait for response
        logger.info(f"[{session_id}] Ringing sales dashboard...")

        response = await sales_mgr.ring_sales(
            session_id=session_id,
            customer_name=customer_name,
            customer_phone=customer_phone,
            reason=reason,
            timeout=SALES_RING_TIMEOUT
        )

        logger.info(f"[{session_id}] Sales response: {response}")

        if response.get("accepted"):
            # Sales accepted the call!
            sales_id = response.get("sales_id", "sales_001")

            result = HumanCheckResult(
                human_available=True,
                human_agent_id=sales_id,
                human_agent_name=sales_id.replace("_", " ").title(),
                estimated_wait="connecting now"
            )

            message = (
                f"Great news! {result.human_agent_name} from our sales team is available now. "
                "I'm connecting you to them right now."
            )
            priority = NotificationPriority.INTERRUPT

        else:
            # Sales not available - schedule callback
            decline_reason = response.get("reason", "unavailable")
            callback_time = self._get_next_callback_slot()

            if decline_reason == "no_sales_online":
                reason_text = "No sales representatives are currently online"
            elif decline_reason == "timeout":
                reason_text = "Sales representatives are busy with other customers"
            elif decline_reason == "declined":
                reason_text = "Sales representatives are currently unavailable"
            else:
                reason_text = "All team members are currently helping other customers"

            result = HumanCheckResult(
                human_available=False,
                reason=reason_text,
                callback_scheduled=callback_time,
                email_sent=True
            )

            # Send callback email
            await self._send_callback_email(
                customer_name=customer_name,
                customer_phone=customer_phone,
                callback_time=callback_time,
                reason=reason
            )

            message = (
                f"I wasn't able to reach a team member right now - {reason_text.lower()}. "
                f"I've scheduled a callback for {callback_time} and sent you a confirmation email. "
                f"Someone will definitely call you then. Is there anything else I can help with in the meantime?"
            )
            priority = NotificationPriority.HIGH

        # Update task as completed
        await state_store.update_task_atomic(session_id, task_id, {
            "status": TaskStatus.COMPLETED,
            "completed_at": datetime.utcnow(),
            "result": result.model_dump(),
            "human_available": result.human_available,
            "human_agent_id": result.human_agent_id,
            "human_agent_name": result.human_agent_name,
            "callback_scheduled": result.callback_scheduled
        })
        await self._broadcast_task_update(session_id, task_id)

        # Create and send notification
        notification = Notification(
            notification_id=f"notif_{int(datetime.utcnow().timestamp() * 1000)}",
            task_id=task_id,
            message=message,
            priority=priority
        )

        await state_store.append_notification_atomic(session_id, notification)

        # Trigger callback for high priority
        if self.notification_callback and priority in [NotificationPriority.HIGH, NotificationPriority.INTERRUPT]:
            await self.notification_callback(session_id, notification)

    def _get_next_callback_slot(self) -> str:
        """Get next available callback time slot."""
        now = datetime.now()

        # Round up to next 30 minute slot + 1 hour
        minutes = 30 * ((now.minute // 30) + 1)
        if minutes >= 60:
            callback_time = now.replace(
                hour=now.hour + 2,
                minute=0,
                second=0,
                microsecond=0
            )
        else:
            callback_time = now.replace(
                hour=now.hour + 1,
                minute=minutes,
                second=0,
                microsecond=0
            )

        # Don't schedule outside business hours
        if callback_time.hour >= 17:  # After 5 PM
            callback_time = callback_time.replace(hour=9, minute=0) + timedelta(days=1)
        if callback_time.hour < 9:  # Before 9 AM
            callback_time = callback_time.replace(hour=9, minute=0)

        # Skip Sunday
        if callback_time.weekday() == 6:
            callback_time += timedelta(days=1)

        return callback_time.strftime("%I:%M %p on %A")

    async def _send_callback_email(
        self,
        customer_name: Optional[str],
        customer_phone: Optional[str],
        callback_time: str,
        reason: Optional[str]
    ):
        """
        Send callback confirmation email.

        Broadcasts to Sales Dashboard for demo, and optionally sends real email if SMTP configured.
        """
        customer_display = customer_name or customer_phone or "Customer"
        email_subject = f"Callback Request - {customer_display}"
        email_body = f"""Springfield Auto - Callback Request
====================================

Customer: {customer_name or 'Unknown'}
Phone: {customer_phone or 'Unknown'}
Scheduled Callback: {callback_time}
Reason: {reason or 'Customer requested human assistance'}

---
This is an automated notification from the voice agent system.
Please ensure this customer is contacted at the scheduled time."""

        # Always broadcast to Sales Dashboard for demo visibility
        sales_mgr = self._get_sales_manager()
        await sales_mgr.broadcast({
            "type": "email_notification",
            "email": {
                "to": getattr(settings, 'sales_email', None) or "sales@springfieldauto.com",
                "subject": email_subject,
                "body": email_body,
                "customer_name": customer_name or "Unknown",
                "customer_phone": customer_phone or "Unknown",
                "callback_time": callback_time,
                "timestamp": datetime.utcnow().isoformat()
            }
        })
        logger.info(f"[EMAIL] Broadcasted email notification to sales dashboard")

        # Also send real email if SMTP is configured
        email_host = getattr(settings, 'smtp_host', None)
        email_user = getattr(settings, 'smtp_user', None)
        email_password = getattr(settings, 'smtp_password', None)
        email_to = getattr(settings, 'sales_email', None)

        if email_host and email_user and email_password and email_to:
            try:
                msg = MIMEMultipart()
                msg['From'] = email_user
                msg['To'] = email_to
                msg['Subject'] = email_subject
                msg.attach(MIMEText(email_body, 'plain'))

                if 'gmail' in email_host.lower():
                    with smtplib.SMTP_SSL(email_host, 465) as server:
                        server.login(email_user, email_password)
                        server.send_message(msg)
                else:
                    with smtplib.SMTP(email_host, 587) as server:
                        server.starttls()
                        server.login(email_user, email_password)
                        server.send_message(msg)

                logger.info(f"[EMAIL] Real email sent to {email_to}")
            except Exception as e:
                logger.error(f"[EMAIL] Failed to send real email: {e}")


# Global instance
background_worker = BackgroundWorker()
