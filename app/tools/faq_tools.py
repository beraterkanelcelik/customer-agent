from langchain_core.tools import tool
from pydantic import BaseModel, Field
from typing import Optional, Literal
from sqlalchemy import select, or_

from app.database.connection import get_db_context
from app.database.models import FAQ, ServiceType


class SearchFAQInput(BaseModel):
    """Input schema for search_faq tool."""
    query: str = Field(description="The user's question or key search terms")
    category: Optional[Literal["hours", "location", "financing", "services", "general"]] = Field(
        None, description="Optional category filter"
    )


@tool(args_schema=SearchFAQInput)
async def search_faq(
    query: str,
    category: Optional[str] = None
) -> str:
    """Search the FAQ database for answers about hours, location, financing, services, or policies."""
    async with get_db_context() as session:
        stmt = select(FAQ)

        # Apply category filter if provided
        if category:
            stmt = stmt.where(FAQ.category == category.lower())

        # Keyword matching
        keywords = query.lower().split()
        conditions = []

        for keyword in keywords:
            if len(keyword) > 2:  # Skip short words
                conditions.append(FAQ.keywords.ilike(f"%{keyword}%"))
                conditions.append(FAQ.question.ilike(f"%{keyword}%"))
                conditions.append(FAQ.answer.ilike(f"%{keyword}%"))

        if conditions:
            stmt = stmt.where(or_(*conditions))

        result = await session.execute(stmt)
        faqs = result.scalars().all()

        if not faqs:
            return "NOT_FOUND: No FAQ entry matches this query. Agent should respond appropriately."

        # Return best match
        best = faqs[0]
        return f"FOUND: {best.answer}"


@tool
async def list_services() -> str:
    """List all available services with pricing and duration. Use when customer asks about services or pricing."""
    async with get_db_context() as session:
        result = await session.execute(select(ServiceType))
        services = result.scalars().all()

        if not services:
            return "ERROR: Unable to retrieve services list."

        lines = ["SERVICES_LIST:"]
        for svc in services:
            # Format price
            if svc.estimated_price_min is None or svc.estimated_price_min == 0:
                price = "Free"
            elif svc.estimated_price_min == svc.estimated_price_max:
                price = f"${svc.estimated_price_min:.0f}"
            else:
                price = f"${svc.estimated_price_min:.0f}-${svc.estimated_price_max:.0f}"

            lines.append(f"- {svc.name}: {price}, about {svc.estimated_duration_minutes} minutes")

        return "\n".join(lines)
