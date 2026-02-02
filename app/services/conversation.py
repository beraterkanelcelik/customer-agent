from typing import Optional
from datetime import datetime
from langchain_core.messages import HumanMessage, AIMessage
import logging

from app.schemas.state import ConversationState
from app.schemas.api import ChatResponse
from app.background.state_store import state_store, MAX_RETRIES
from app.agents.graph import process_message

logger = logging.getLogger("app.services.conversation")


class OptimisticLockError(Exception):
    """Raised when optimistic locking fails after max retries."""
    pass


class ConversationService:
    """
    High-level service for managing conversations.
    """

    async def create_session(self, session_id: str, customer_phone: Optional[str] = None) -> ConversationState:
        """Create a new conversation session."""
        state = ConversationState(session_id=session_id)

        if customer_phone:
            state.customer.phone = customer_phone

        await state_store.set_state(session_id, state)
        return state

    async def get_session(self, session_id: str) -> Optional[ConversationState]:
        """Get existing session."""
        return await state_store.get_state(session_id)

    async def process_message(self, session_id: str, user_message: str) -> ChatResponse:
        """
        Process a user message and return response.

        Uses optimistic locking with retry to handle race conditions.
        """
        logger.info(f"[{session_id}] ====== PROCESSING MESSAGE ======")
        logger.info(f"[{session_id}] User message: '{user_message}'")

        retries = 0

        while retries < MAX_RETRIES:
            # Get state with version for optimistic locking
            state, version = await state_store.get_state_with_version(session_id)

            if not state:
                state = await self.create_session(session_id)
                version = state.version
                logger.info(f"[{session_id}] Created new session with version {version}")
            else:
                # Sync any atomic updates from background tasks
                state = await state_store.sync_atomic_updates_to_state(session_id)
                version = state.version
                logger.info(f"[{session_id}] Loaded session with {len(state.messages)} messages, version {version}")
                for i, msg in enumerate(state.messages[:5]):  # Only log first 5
                    msg_type = type(msg).__name__
                    content = msg.content[:50] if hasattr(msg, 'content') else str(msg)[:50]
                    logger.info(f"[{session_id}]   msg[{i}] {msg_type}: {content}...")

            # Process through LangGraph
            updated_state = await process_message(
                session_id=session_id,
                user_message=user_message,
                current_state=state
            )

            logger.info(f"[{session_id}] After processing: {len(updated_state.messages)} messages")

            # Try to save with optimistic locking
            success = await state_store.set_state_if_version(session_id, updated_state, version)

            if success:
                break
            else:
                retries += 1
                logger.warning(f"[{session_id}] Version conflict, retry {retries}/{MAX_RETRIES}")

                if retries >= MAX_RETRIES:
                    logger.error(f"[{session_id}] Max retries exceeded, falling back to force save")
                    # Force save as last resort
                    await state_store.set_state(session_id, updated_state)
                    break

        # Get response (last AI message)
        response_text = ""
        for msg in reversed(updated_state.messages):
            if isinstance(msg, AIMessage):
                response_text = msg.content
                break

        # Handle both enum and string values (due to use_enum_values=True in config)
        agent_type = updated_state.current_agent
        if hasattr(agent_type, 'value'):
            agent_type = agent_type.value
        elif not agent_type:
            agent_type = "unified"

        intent = updated_state.detected_intent
        if hasattr(intent, 'value'):
            intent = intent.value

        # Handle human_agent_status enum
        human_agent_status = updated_state.human_agent_status
        if hasattr(human_agent_status, 'value'):
            human_agent_status = human_agent_status.value

        return ChatResponse(
            session_id=session_id,
            response=response_text,
            agent_type=agent_type,
            intent=intent,
            confidence=updated_state.confidence,
            customer=updated_state.customer,
            booking_slots=updated_state.booking_slots.model_dump() if updated_state.booking_slots else None,
            confirmed_appointment=updated_state.confirmed_appointment.model_dump() if updated_state.confirmed_appointment else None,
            pending_tasks=updated_state.pending_tasks,
            escalation_in_progress=updated_state.escalation_in_progress,
            human_agent_status=human_agent_status
        )

    async def end_session(self, session_id: str):
        """End and cleanup a session."""
        await state_store.delete_session(session_id)


# Global instance
conversation_service = ConversationService()
