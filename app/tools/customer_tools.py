from langchain_core.tools import tool
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy import select

from app.database.connection import get_db_context
from app.database.models import Customer, Vehicle


class GetCustomerInput(BaseModel):
    """Input schema for get_customer tool."""
    phone: str = Field(description="Customer's phone number (digits only preferred, e.g., '5551234567')")


class CreateCustomerInput(BaseModel):
    """Input schema for create_customer tool."""
    name: str = Field(description="Customer's full name")
    phone: str = Field(description="Customer's phone number (digits only)")
    email: str = Field(description="Customer's email address")
    vehicle_make: Optional[str] = Field(None, description="Vehicle manufacturer (e.g., 'Toyota')")
    vehicle_model: Optional[str] = Field(None, description="Vehicle model (e.g., 'Camry')")
    vehicle_year: Optional[int] = Field(None, description="Vehicle year (e.g., 2022)")


@tool(args_schema=GetCustomerInput)
async def get_customer(phone: str) -> str:
    """Look up a customer by phone number. Use to identify returning customers."""
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


class CreateCustomerInputWithSession(BaseModel):
    """Input schema for create_customer tool with session_id."""
    session_id: str = Field(description="The current session ID (required)")
    name: str = Field(description="Customer's full name")
    phone: str = Field(description="Customer's phone number (digits only)")
    email: str = Field(description="Customer's email address")
    vehicle_make: Optional[str] = Field(None, description="Vehicle manufacturer (e.g., 'Toyota')")
    vehicle_model: Optional[str] = Field(None, description="Vehicle model (e.g., 'Camry')")
    vehicle_year: Optional[int] = Field(None, description="Vehicle year (e.g., 2022)")


@tool(args_schema=CreateCustomerInputWithSession)
async def create_customer(
    session_id: str,
    name: str,
    phone: str,
    email: str,
    vehicle_make: Optional[str] = None,
    vehicle_model: Optional[str] = None,
    vehicle_year: Optional[int] = None
) -> str:
    """Create a new customer record. Use after collecting name, phone, and email from a new customer."""
    from app.tools.slot_tools import _pending_slot_updates

    async with get_db_context() as session:
        # Check for existing customer
        stmt = select(Customer).where(Customer.phone == phone)
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            # Auto-set customer as identified
            if session_id not in _pending_slot_updates:
                _pending_slot_updates[session_id] = {}
            _pending_slot_updates[session_id]["_customer_identified"] = True
            _pending_slot_updates[session_id]["_customer_id"] = existing.id
            _pending_slot_updates[session_id]["_customer_name"] = existing.name
            _pending_slot_updates[session_id]["_customer_phone"] = existing.phone
            _pending_slot_updates[session_id]["_customer_email"] = existing.email
            # Also update the booking slots with customer info
            _pending_slot_updates[session_id]["customer_name"] = existing.name
            _pending_slot_updates[session_id]["customer_phone"] = existing.phone
            _pending_slot_updates[session_id]["customer_email"] = existing.email
            return f"ALREADY_EXISTS: Customer already exists with ID {existing.id}. Using their existing record. Customer is now identified."

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

        # Auto-set customer as identified in pending slot updates
        if session_id not in _pending_slot_updates:
            _pending_slot_updates[session_id] = {}
        _pending_slot_updates[session_id]["_customer_identified"] = True
        _pending_slot_updates[session_id]["_customer_id"] = customer.id
        _pending_slot_updates[session_id]["_customer_name"] = name
        _pending_slot_updates[session_id]["_customer_phone"] = phone
        _pending_slot_updates[session_id]["_customer_email"] = email
        # Also update the booking slots with customer info
        _pending_slot_updates[session_id]["customer_name"] = name
        _pending_slot_updates[session_id]["customer_phone"] = phone
        _pending_slot_updates[session_id]["customer_email"] = email

        response = f"CUSTOMER_CREATED:\n"
        response += f"Customer ID: {customer.id}\n"
        response += f"Name: {name}\n"
        response += f"Phone: {phone}\n"
        response += f"Email: {email}\n"
        response += f"Customer is now identified and ready for booking.\n"

        if vehicle_id:
            response += f"Vehicle ID: {vehicle_id} ({vehicle_year or ''} {vehicle_make} {vehicle_model})\n"

        return response
