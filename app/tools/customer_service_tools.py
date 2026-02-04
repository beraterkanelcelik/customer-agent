"""
Customer service escalation tools for the voice agent.

These tools handle escalation to customer service via Twilio phone calls,
separate from sales escalation which goes through the dashboard.
"""
from langchain_core.tools import tool
from pydantic import BaseModel, Field
import asyncio
import time
import logging

logger = logging.getLogger("app.tools.customer_service")


class RequestCustomerServiceInput(BaseModel):
    """Input schema for request_customer_service_agent tool."""
    session_id: str = Field(description="The current session ID")
    reason: str = Field(description="Why the customer needs customer service help")


@tool(args_schema=RequestCustomerServiceInput)
async def request_customer_service_agent(session_id: str, reason: str) -> str:
    """
    Request to transfer the customer to a customer service agent via phone.

    Call this tool when the customer needs help with:
    - Warranty claims or issues
    - Service complaints or problems
    - Billing disputes or questions
    - General support requests that aren't sales-related
    - Post-purchase issues

    This will initiate a phone call to customer service and bridge them in.
    """
    from app.background.worker import background_worker

    logger.info(f"[CUSTOMER SERVICE] Requested for session {session_id}: {reason}")

    # Create task ID
    task_id = f"cs_{session_id}_{int(time.time())}"

    # Spawn background task to handle Twilio call
    if background_worker:
        asyncio.create_task(
            background_worker.execute_customer_service_check(
                task_id=task_id,
                session_id=session_id,
                customer_name=None,  # Will be populated from state if available
                reason=reason
            )
        )
        logger.info(f"[CUSTOMER SERVICE] Background task spawned: {task_id}")
    else:
        logger.warning("[CUSTOMER SERVICE] No background worker available")

    # Return structured response only - agent generates spoken message
    return f"CUSTOMER_SERVICE_STARTED:task_id={task_id}|Call initiated to customer service"
