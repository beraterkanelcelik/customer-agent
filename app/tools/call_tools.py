"""
Call management tools for the voice agent.

These tools allow the agent to control the call flow,
including gracefully ending calls.
"""
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from typing import Optional

# Temporary storage for call actions during agent execution
# Keyed by session_id
_pending_call_actions: dict = {}


def get_pending_call_action(session_id: str) -> Optional[dict]:
    """Get and clear pending call action for a session."""
    return _pending_call_actions.pop(session_id, None)


def clear_pending_call_actions(session_id: str):
    """Clear pending call actions without returning them."""
    _pending_call_actions.pop(session_id, None)


class EndCallInput(BaseModel):
    """Input schema for end_call tool."""
    session_id: str = Field(description="The current session ID")
    farewell_message: str = Field(
        description="The farewell message to speak before ending the call. Required - generate a warm goodbye."
    )


@tool(args_schema=EndCallInput)
def end_call(
    session_id: str,
    farewell_message: str
) -> str:
    """End the voice call gracefully. Use when booking is complete or customer says goodbye."""
    _pending_call_actions[session_id] = {
        "action": "end_call",
        "farewell_message": farewell_message
    }

    return f"CALL_ENDING: Will speak farewell and disconnect. Message: '{farewell_message}'"
