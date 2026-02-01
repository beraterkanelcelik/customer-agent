from langchain_core.tools import tool
from typing import Optional
from sqlalchemy import select

from app.database.connection import get_db_context
from app.database.models import Customer, Vehicle


@tool
async def get_customer(phone: str) -> str:
    """
    Look up a customer by phone number.

    Use this to identify returning customers at the start of booking
    or when customer provides their phone number.

    Args:
        phone: Customer's phone number (any format accepted)

    Returns:
        Customer info if found, or indication of new customer.
    """
    # Normalize phone - extract digits
    digits = ''.join(filter(str.isdigit, phone))

    async with get_db_context() as session:
        # Try different matching strategies
        stmt = select(Customer).where(Customer.phone == phone)
        result = await session.execute(stmt)
        customer = result.scalar_one_or_none()

        # Try last 10 digits if no exact match
        if not customer and len(digits) >= 10:
            last_10 = digits[-10:]
            stmt = select(Customer).where(Customer.phone.contains(last_10))
            result = await session.execute(stmt)
            customer = result.scalar_one_or_none()

        if not customer:
            return f"NEW_CUSTOMER: No customer found with phone {phone}. This is a new customer - need to collect their information."

        # Build response
        response = f"CUSTOMER_FOUND:\n"
        response += f"ID: {customer.id}\n"
        response += f"Name: {customer.name or 'Not on file'}\n"
        response += f"Phone: {customer.phone}\n"
        response += f"Email: {customer.email or 'Not on file'}\n"

        if customer.vehicles:
            response += "Vehicles:\n"
            for v in customer.vehicles:
                response += f"  - {v.year or ''} {v.make} {v.model}"
                if v.license_plate:
                    response += f" (Plate: {v.license_plate})"
                response += f" [ID: {v.id}]\n"

        return response


@tool
async def create_customer(
    name: str,
    phone: str,
    email: str,
    vehicle_make: Optional[str] = None,
    vehicle_model: Optional[str] = None,
    vehicle_year: Optional[int] = None
) -> str:
    """
    Create a new customer record in the database.

    Use this after collecting all required information from a new customer.

    Args:
        name: Customer's full name
        phone: Customer's phone number
        email: Customer's email address
        vehicle_make: Optional vehicle make (e.g., "Toyota")
        vehicle_model: Optional vehicle model (e.g., "Camry")
        vehicle_year: Optional vehicle year (e.g., 2022)

    Returns:
        Confirmation with new customer ID.
    """
    async with get_db_context() as session:
        # Check for existing customer
        stmt = select(Customer).where(Customer.phone == phone)
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            return f"ALREADY_EXISTS: Customer already exists with ID {existing.id}. Use their existing record."

        # Create customer
        customer = Customer(
            name=name,
            phone=phone,
            email=email
        )
        session.add(customer)
        await session.flush()  # Get ID

        # Add vehicle if provided
        vehicle_id = None
        if vehicle_make and vehicle_model:
            vehicle = Vehicle(
                customer_id=customer.id,
                make=vehicle_make,
                model=vehicle_model,
                year=vehicle_year
            )
            session.add(vehicle)
            await session.flush()
            vehicle_id = vehicle.id

        await session.commit()

        response = f"CUSTOMER_CREATED:\n"
        response += f"Customer ID: {customer.id}\n"
        response += f"Name: {name}\n"
        response += f"Phone: {phone}\n"
        response += f"Email: {email}\n"

        if vehicle_id:
            response += f"Vehicle ID: {vehicle_id} ({vehicle_year or ''} {vehicle_make} {vehicle_model})\n"

        return response
