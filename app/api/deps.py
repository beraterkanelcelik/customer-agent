from typing import AsyncGenerator
from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.connection import get_db
from app.background.state_store import state_store
from app.services.conversation import conversation_service


async def get_database() -> AsyncGenerator[AsyncSession, None]:
    """Database session dependency."""
    async for session in get_db():
        yield session


async def get_conversation_service():
    """Conversation service dependency."""
    return conversation_service


async def get_state_store():
    """State store dependency."""
    return state_store
