from langchain_core.tools import tool
from typing import Optional, Literal
from datetime import date, time, datetime, timedelta
from sqlalchemy import select, and_

from app.database.connection import get_db_context
from app.database.models import (
    Appointment, AppointmentTypeModel, ServiceType,
    Inventory, Customer
)


@tool
async def check_availability(
    appointment_type: Literal["service", "test_drive"],
    preferred_date: str,
    preferred_time: Optional[str] = None
) -> str:
    """
    Check available time slots for an appointment.

    Use this before booking to find available times.

    Args:
        appointment_type: Either "service" or "test_drive"
        preferred_date: Date in YYYY-MM-DD format
        preferred_time: Optional time in HH:MM format (24-hour)

    Returns:
        Available time slots or suggestion for next available date.
    """
    # Parse date
    try:
        check_date = datetime.strptime(preferred_date, "%Y-%m-%d").date()
    except ValueError:
        return "ERROR: Invalid date format. Use YYYY-MM-DD (e.g., 2025-02-15)."

    # Validate date range
    today = date.today()
    if check_date < today:
        return "ERROR: Cannot book appointments in the past."
    if check_date > today + timedelta(days=30):
        return "ERROR: Cannot book more than 30 days in advance."

    # Check day of week (closed Sunday)
    if check_date.weekday() == 6:
        next_monday = check_date + timedelta(days=1)
        return f"CLOSED: We are closed on Sundays. Next available is Monday {next_monday.strftime('%Y-%m-%d')}."

    # Get existing appointments for this date
    async with get_db_context() as session:
        stmt = select(Appointment).where(
            and_(
                Appointment.scheduled_date == check_date,
                Appointment.status.in_(["scheduled", "confirmed"])
            )
        )
        result = await session.execute(stmt)
        existing = result.scalars().all()
        booked_times = {(a.scheduled_time.hour, a.scheduled_time.minute) for a in existing}

    # Generate available slots
    # Weekdays: 9 AM - 5 PM, Saturday: 9 AM - 4 PM
    end_hour = 16 if check_date.weekday() == 5 else 17
    available = []

    for hour in range(9, end_hour):
        if hour == 12:  # Lunch hour
            continue
        for minute in [0, 30]:
            if (hour, minute) not in booked_times:
                t = time(hour, minute)
                available.append(t.strftime("%I:%M %p").lstrip("0"))

    if not available:
        # Find next available date
        next_date = check_date + timedelta(days=1)
        while next_date.weekday() == 6:  # Skip Sundays
            next_date += timedelta(days=1)
        return f"FULL: No availability on {preferred_date}. Try {next_date.strftime('%Y-%m-%d')} instead."

    # Check specific time if requested
    if preferred_time:
        try:
            req_time = datetime.strptime(preferred_time, "%H:%M").time()
            req_display = req_time.strftime("%I:%M %p").lstrip("0")

            if req_display in available:
                return f"AVAILABLE: {req_display} on {check_date.strftime('%A, %B %d')} is available!"
            else:
                return f"UNAVAILABLE: {req_display} is not available. Available times: {', '.join(available[:5])}"
        except ValueError:
            pass

    # Return available slots
    date_display = check_date.strftime("%A, %B %d")
    slots_display = ", ".join(available[:6])
    more = f" (and {len(available) - 6} more)" if len(available) > 6 else ""

    return f"SLOTS: On {date_display}, available times are: {slots_display}{more}"


@tool
async def book_appointment(
    customer_id: int,
    appointment_type: Literal["service", "test_drive"],
    scheduled_date: str,
    scheduled_time: str,
    service_type_id: Optional[int] = None,
    inventory_id: Optional[int] = None,
    vehicle_id: Optional[int] = None,
    notes: Optional[str] = None
) -> str:
    """
    Book an appointment for a customer.

    Call this after:
    1. Customer is identified (have customer_id)
    2. Availability confirmed
    3. All required info collected

    Args:
        customer_id: Customer's database ID
        appointment_type: "service" or "test_drive"
        scheduled_date: Date in YYYY-MM-DD format
        scheduled_time: Time in HH:MM format (24-hour)
        service_type_id: Required for service - the service type ID
        inventory_id: Required for test_drive - vehicle to test
        vehicle_id: Optional - customer's vehicle ID for service
        notes: Optional notes

    Returns:
        Booking confirmation or error.
    """
    # Parse datetime
    try:
        appt_date = datetime.strptime(scheduled_date, "%Y-%m-%d").date()
        appt_time = datetime.strptime(scheduled_time, "%H:%M").time()
    except ValueError:
        return "ERROR: Invalid date or time format."

    async with get_db_context() as session:
        # Get appointment type record
        stmt = select(AppointmentTypeModel).where(AppointmentTypeModel.name == appointment_type)
        result = await session.execute(stmt)
        appt_type = result.scalar_one_or_none()

        if not appt_type:
            return "ERROR: Invalid appointment type."

        # Verify customer exists
        stmt = select(Customer).where(Customer.id == customer_id)
        result = await session.execute(stmt)
        customer = result.scalar_one_or_none()

        if not customer:
            return f"ERROR: Customer ID {customer_id} not found."

        # Determine duration
        duration = appt_type.duration_minutes
        if service_type_id:
            stmt = select(ServiceType).where(ServiceType.id == service_type_id)
            result = await session.execute(stmt)
            service = result.scalar_one_or_none()
            if service:
                duration = service.estimated_duration_minutes

        # Create appointment
        appointment = Appointment(
            customer_id=customer_id,
            appointment_type_id=appt_type.id,
            vehicle_id=vehicle_id,
            inventory_id=inventory_id,
            service_type_id=service_type_id,
            scheduled_date=appt_date,
            scheduled_time=appt_time,
            duration_minutes=duration,
            status="scheduled",
            notes=notes
        )

        session.add(appointment)
        await session.commit()
        await session.refresh(appointment)

        # Format confirmation
        date_str = appt_date.strftime("%A, %B %d, %Y")
        time_str = appt_time.strftime("%I:%M %p").lstrip("0")

        response = "BOOKING_CONFIRMED:\n"
        response += f"Confirmation #: {appointment.id}\n"
        response += f"Type: {appt_type.display_name}\n"
        response += f"Date: {date_str}\n"
        response += f"Time: {time_str}\n"
        response += f"Customer: {customer.name}\n"

        if customer.email:
            response += f"Confirmation email will be sent to: {customer.email}\n"

        return response


@tool
async def reschedule_appointment(
    appointment_id: int,
    new_date: str,
    new_time: str
) -> str:
    """
    Reschedule an existing appointment to a new date/time.

    Args:
        appointment_id: The appointment ID to reschedule
        new_date: New date in YYYY-MM-DD format
        new_time: New time in HH:MM format (24-hour)

    Returns:
        Confirmation of reschedule or error.
    """
    try:
        appt_date = datetime.strptime(new_date, "%Y-%m-%d").date()
        appt_time = datetime.strptime(new_time, "%H:%M").time()
    except ValueError:
        return "ERROR: Invalid date or time format."

    async with get_db_context() as session:
        stmt = select(Appointment).where(Appointment.id == appointment_id)
        result = await session.execute(stmt)
        appointment = result.scalar_one_or_none()

        if not appointment:
            return f"ERROR: Appointment #{appointment_id} not found."

        if appointment.status == "cancelled":
            return "ERROR: Cannot reschedule a cancelled appointment."

        # Store old values
        old_date = appointment.scheduled_date.strftime("%A, %B %d")
        old_time = appointment.scheduled_time.strftime("%I:%M %p").lstrip("0")

        # Update
        appointment.scheduled_date = appt_date
        appointment.scheduled_time = appt_time

        await session.commit()

        new_date_str = appt_date.strftime("%A, %B %d")
        new_time_str = appt_time.strftime("%I:%M %p").lstrip("0")

        return f"RESCHEDULED: Appointment #{appointment_id} moved from {old_date} at {old_time} to {new_date_str} at {new_time_str}."


@tool
async def cancel_appointment(
    appointment_id: int,
    reason: Optional[str] = None
) -> str:
    """
    Cancel an existing appointment.

    Args:
        appointment_id: The appointment ID to cancel
        reason: Optional reason for cancellation

    Returns:
        Cancellation confirmation.
    """
    async with get_db_context() as session:
        stmt = select(Appointment).where(Appointment.id == appointment_id)
        result = await session.execute(stmt)
        appointment = result.scalar_one_or_none()

        if not appointment:
            return f"ERROR: Appointment #{appointment_id} not found."

        if appointment.status == "cancelled":
            return "ALREADY_CANCELLED: This appointment is already cancelled."

        appointment.status = "cancelled"
        if reason:
            appointment.notes = f"Cancelled: {reason}"

        await session.commit()

        return f"CANCELLED: Appointment #{appointment_id} has been cancelled."


@tool
async def get_customer_appointments(customer_id: int) -> str:
    """
    Get all upcoming appointments for a customer.

    Use this when customer wants to reschedule but doesn't
    know their appointment details.

    Args:
        customer_id: The customer's database ID

    Returns:
        List of appointments or indication none found.
    """
    async with get_db_context() as session:
        stmt = select(Appointment).where(
            and_(
                Appointment.customer_id == customer_id,
                Appointment.status.in_(["scheduled", "confirmed"]),
                Appointment.scheduled_date >= date.today()
            )
        ).order_by(Appointment.scheduled_date, Appointment.scheduled_time)

        result = await session.execute(stmt)
        appointments = result.scalars().all()

        if not appointments:
            return "NO_APPOINTMENTS: No upcoming appointments found for this customer."

        lines = ["APPOINTMENTS:"]
        for appt in appointments:
            date_str = appt.scheduled_date.strftime("%A, %B %d")
            time_str = appt.scheduled_time.strftime("%I:%M %p").lstrip("0")
            lines.append(f"- #{appt.id}: {date_str} at {time_str} ({appt.status})")

        return "\n".join(lines)


@tool
async def list_inventory(
    make: Optional[str] = None,
    max_results: int = 5
) -> str:
    """
    List vehicles available for test drives.

    Use when customer wants to see what cars are available
    or is interested in test driving.

    Args:
        make: Optional filter by manufacturer (e.g., "Toyota")
        max_results: Maximum results to return (default 5)

    Returns:
        List of available vehicles.
    """
    async with get_db_context() as session:
        stmt = select(Inventory).where(Inventory.is_available == True)

        if make:
            stmt = stmt.where(Inventory.make.ilike(f"%{make}%"))

        stmt = stmt.limit(max_results)

        result = await session.execute(stmt)
        vehicles = result.scalars().all()

        if not vehicles:
            filter_msg = f" matching '{make}'" if make else ""
            return f"NO_VEHICLES: No vehicles{filter_msg} currently available for test drive."

        lines = ["INVENTORY:"]
        for v in vehicles:
            price = f"${v.price:,.0f}" if v.price else "Contact for price"
            condition = "New" if v.is_new else "Pre-owned"
            lines.append(f"- {v.year} {v.make} {v.model} ({v.color}) - {price} [{condition}] Stock #{v.stock_number}, ID: {v.id}")

        return "\n".join(lines)
