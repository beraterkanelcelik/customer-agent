from langchain_core.tools import tool
from typing import Optional
from sqlalchemy import select, or_

from app.database.connection import get_db_context
from app.database.models import FAQ, ServiceType


@tool
async def search_faq(
    query: str,
    category: Optional[str] = None
) -> str:
    """
    Search the FAQ database for relevant answers.

    Use this tool when the user asks questions about:
    - Opening hours and location
    - Financing options and requirements
    - Available services and pricing
    - Policies (returns, warranties, loaners)

    Args:
        query: The user's question or key terms
        category: Optional filter - hours, location, financing, services, general

    Returns:
        The most relevant answer or indication that info wasn't found.
    """
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
            return "NOT_FOUND: I don't have specific information about that. Would you like me to connect you with a team member?"

        # Return best match
        best = faqs[0]
        return f"FOUND: {best.answer}"


@tool
async def list_services() -> str:
    """
    List all available services with estimated pricing.

    Use this when customer asks what services are available,
    wants to know pricing, or is deciding what service to book.

    Returns:
        Formatted list of all services with duration and price.
    """
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
