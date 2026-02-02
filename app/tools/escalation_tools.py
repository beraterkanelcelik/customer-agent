"""
Escalation tools for the voice agent.

These tools allow the LLM to decide when to escalate to a human agent,
removing all hardcoded phrase detection.
"""
from langchain_core.tools import tool
from pydantic import BaseModel, Field
import asyncio
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

    This will check human availability and notify the customer.
    """
    from app.background.worker import background_worker
    from app.schemas.enums import TaskType, TaskStatus
    from app.schemas.task import BackgroundTask

    logger.info(f"[ESCALATION] Requested for session {session_id}: {reason}")

    # Create task ID
    task_id = f"esc_{session_id}_{int(time.time())}"

    # Spawn background check for human availability
    if background_worker:
        asyncio.create_task(
            background_worker.execute_human_check(
                task_id=task_id,
                session_id=session_id,
                customer_name=None,
                customer_phone=None,
                reason=reason
            )
        )
        logger.info(f"[ESCALATION] Background task spawned: {task_id}")
    else:
        logger.warning("[ESCALATION] No background worker available")

    # Return structured response for service layer to parse
    return (
        f"ESCALATION_STARTED:task_id={task_id}|"
        "I'm checking if one of our team members is available right now. "
        "This will take just a moment. Is there anything else I can help you with while we wait?"
    )
