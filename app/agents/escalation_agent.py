from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
import asyncio
import time
from typing import Tuple

from app.config import get_settings
from app.schemas.state import ConversationState
from app.schemas.task import BackgroundTask
from app.schemas.enums import TaskType, TaskStatus, HumanAgentStatus

settings = get_settings()


ESCALATION_SYSTEM_PROMPT = """You are handling a customer escalation request for Springfield Auto dealership.

The customer wants to speak with a human team member.

Your job:
1. Acknowledge their request warmly
2. Let them know you're checking availability
3. Assure them they can continue asking questions while you check

Keep response SHORT and reassuring. Example:
"Absolutely, let me check if one of our team members is available right now. This might take just a moment. While I'm checking, is there anything else I can help you with?"
"""


class EscalationAgent:
    """Handles human escalation requests with async background check."""

    def __init__(self, background_worker=None):
        self.llm = ChatOpenAI(
            model=settings.openai_model,
            temperature=0.3,
            api_key=settings.openai_api_key
        )
        self.background_worker = background_worker

    def set_background_worker(self, worker):
        """Set the background worker reference."""
        self.background_worker = worker

    async def handle(
        self,
        user_message: str,
        state: ConversationState
    ) -> Tuple[str, BackgroundTask]:
        """
        Handle escalation request.

        Returns:
            Tuple of (response_text, background_task)
        """

        # Generate response
        messages = [
            SystemMessage(content=ESCALATION_SYSTEM_PROMPT),
            HumanMessage(content=f"Customer said: {user_message}")
        ]

        response = await self.llm.ainvoke(messages)
        response_text = response.content

        # Create background task
        task_id = f"esc_{state.session_id}_{int(time.time())}"
        task = BackgroundTask(
            task_id=task_id,
            task_type=TaskType.HUMAN_ESCALATION,
            status=TaskStatus.PENDING
        )

        # Spawn background check (non-blocking)
        if self.background_worker:
            asyncio.create_task(
                self.background_worker.execute_human_check(
                    task_id=task_id,
                    session_id=state.session_id,
                    customer_name=state.customer.name,
                    customer_phone=state.customer.phone,
                    reason=user_message
                )
            )

        return response_text, task
