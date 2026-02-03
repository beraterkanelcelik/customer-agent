"""
Escalation tools for the voice agent.

These tools allow the LLM to decide when to escalate to a human agent,
removing all hardcoded phrase detection.
"""
from langchain_core.tools import tool
from pydantic import BaseModel, Field
import time
import logging

logger = logging.getLogger("app.tools.escalation")


class RequestHumanInput(BaseModel):
    """Input schema for request_human_agent tool."""
    session_id: str = Field(description="The current session ID")
    reason: str = Field(description="Why the customer wants to speak with a human")


@tool(args_schema=RequestHumanInput)
async def request_human_agent(session_id: str, reason: str) -> str:
    """
    Request to transfer the customer to a human agent.

    Call this tool when:
    - Customer explicitly asks to speak with a human, person, manager, or representative
    - Customer expresses frustration or the request cannot be handled
    - Customer uses phrases like "give me a human", "transfer me", "real person"
    - Customer asks for someone specific (manager, supervisor, sales rep)

    This will initiate a phone call to the customer service number.
    The customer stays with the AI while the call is being placed.
    """
    logger.info(f"[ESCALATION] Requested for session {session_id}: {reason}")

    # Create task ID for tracking
    task_id = f"esc_{session_id}_{int(time.time())}"

    # No background worker needed - Twilio voice service handles the actual phone call
    # The voice service will see needs_escalation=True and start calling CUSTOMER_SERVICE_PHONE
    logger.info(f"[ESCALATION] Task ID: {task_id} - Twilio voice service will handle the call")

    # Return structured response - voice service will initiate phone call
    return (
        f"ESCALATION_STARTED:task_id={task_id}|"
        "I'm calling one of our team members right now. "
        "You can keep talking to me while I try to reach them."
    )
