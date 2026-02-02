from langchain_core.tools import tool
from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import date, time, datetime, timedelta
from sqlalchemy import select, and_

from app.database.connection import get_db_context
from app.database.models import (
    Appointment, AppointmentTypeModel, ServiceType,
    Inventory, Customer, AvailabilitySlot
)


class CheckAvailabilityInput(BaseModel):
    """Input schema for check_availability tool."""
    appointment_type: Literal["service", "test_drive"] = Field(
        description="Type of appointment: 'service' or 'test_drive'"
    )
    preferred_date: str = Field(description="Date in YYYY-MM-DD format (e.g., '2025-02-15')")
    preferred_time: Optional[str] = Field(None, description="Time in HH:MM 24-hour format (e.g., '14:00')")


class BookAppointmentInput(BaseModel):
    """Input schema for book_appointment tool."""
    customer_id: int = Field(description="Customer's database ID from get_customer or create_customer")
    appointment_type: Literal["service", "test_drive"] = Field(
        description="Type of appointment: 'service' or 'test_drive'"
    )
    scheduled_date: str = Field(description="Date in YYYY-MM-DD format")
    scheduled_time: str = Field(description="Time in HH:MM 24-hour format")
    service_type_id: Optional[int] = Field(None, description="Service type ID (required for service appointments)")
    inventory_id: Optional[int] = Field(None, description="Vehicle inventory ID (required for test drives)")
    vehicle_id: Optional[int] = Field(None, description="Customer's vehicle ID for service")
    notes: Optional[str] = Field(None, description="Optional notes for the appointment")


class RescheduleInput(BaseModel):
    """Input schema for reschedule_appointment tool."""
    appointment_id: int = Field(description="The appointment ID to reschedule")
    new_date: str = Field(description="New date in YYYY-MM-DD format")
    new_time: str = Field(description="New time in HH:MM 24-hour format")


class CancelInput(BaseModel):
    """Input schema for cancel_appointment tool."""
    appointment_id: int = Field(description="The appointment ID to cancel")
    reason: Optional[str] = Field(None, description="Optional reason for cancellation")


class GetAppointmentsInput(BaseModel):
    """Input schema for get_customer_appointments tool."""
    customer_id: int = Field(description="The customer's database ID")


class ListInventoryInput(BaseModel):
    """Input schema for list_inventory tool."""
    make: Optional[str] = Field(None, description="Filter by manufacturer (e.g., 'Toyota')")
    max_results: int = Field(5, description="Maximum results to return (default 5)")


@tool(args_schema=CheckAvailabilityInput)
async def check_availability(
    appointment_type: Literal["service", "test_drive"],
    preferred_date: str,
    preferred_time: Optional[str] = None
) -> str:
    """Check available time slots for an appointment. Use before booking."""
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


@tool(args_schema=BookAppointmentInput)
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
    """Book an appointment. Requires customer_id, type, date, time. Call after availability is confirmed."""
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

        # Mark availability slot as booked
        # For test drives, also filter by inventory_id since there's one slot per vehicle
        slot_conditions = [
            AvailabilitySlot.slot_date == appt_date,
            AvailabilitySlot.slot_time == appt_time,
            AvailabilitySlot.appointment_type == appointment_type,
            AvailabilitySlot.is_available == True
        ]
        if inventory_id and appointment_type == "test_drive":
            slot_conditions.append(AvailabilitySlot.inventory_id == inventory_id)

        slot_stmt = select(AvailabilitySlot).where(and_(*slot_conditions))
        slot_result = await session.execute(slot_stmt)
        # Use first() instead of scalar_one_or_none() to handle edge cases
        availability_slot = slot_result.scalars().first()

        if availability_slot:
            availability_slot.is_available = False
            availability_slot.booked_appointment_id = appointment.id
            await session.commit()

            # Send WebSocket update for availability change
            try:
                from app.api.websocket import get_ws_manager
                import asyncio
                ws_manager = get_ws_manager()
                asyncio.create_task(
                    ws_manager.broadcast_availability_update(
                        slot_date=appt_date.strftime("%Y-%m-%d"),
                        slot_time=appt_time.strftime("%H:%M"),
                        appointment_type=appointment_type,
                        is_available=False
                    )
                )
            except Exception as e:
                # Don't fail booking if WebSocket update fails
                print(f"Failed to send availability update: {e}")

        # Format confirmation for display
        date_str = appt_date.strftime("%A, %B %d, %Y")
        time_str = appt_time.strftime("%I:%M %p").lstrip("0")

        # Get service type name if available
        service_name = None
        if service_type_id:
            stmt = select(ServiceType).where(ServiceType.id == service_type_id)
            result = await session.execute(stmt)
            service = result.scalar_one_or_none()
            if service:
                service_name = service.name

        # Get vehicle info if available
        vehicle_info = None
        if inventory_id:
            stmt = select(Inventory).where(Inventory.id == inventory_id)
            result = await session.execute(stmt)
            inv = result.scalar_one_or_none()
            if inv:
                vehicle_info = f"{inv.year} {inv.make} {inv.model}"

        # Store confirmation data for state update (via slot_tools pattern)
        from app.tools.slot_tools import _pending_slot_updates
        if customer_id not in _pending_slot_updates:
            # Use a special key pattern for booking confirmations
            pass  # Will be keyed by session_id in graph

        # Build human-readable response
        response = f"BOOKING_CONFIRMED: Appointment #{appointment.id} booked!\n"
        response += f"Type: {appt_type.display_name}\n"
        response += f"Date: {date_str}\n"
        response += f"Time: {time_str}\n"
        response += f"Customer: {customer.name}"

        if customer.email:
            response += f"\nConfirmation email will be sent to: {customer.email}"

        # Embed structured data for graph to parse (kept for backward compatibility)
        # The graph's _parse_tool_results handles this
        import json
        confirmation_data = {
            "appointment_id": appointment.id,
            "appointment_type": appointment_type,
            "scheduled_date": appt_date.strftime("%Y-%m-%d"),
            "scheduled_time": appt_time.strftime("%H:%M"),
            "customer_name": customer.name,
            "customer_email": customer.email,
            "service_type": service_name,
            "vehicle": vehicle_info
        }
        response += f"\n__CONFIRMATION_DATA__:{json.dumps(confirmation_data)}"

        return response


@tool(args_schema=RescheduleInput)
async def reschedule_appointment(
    appointment_id: int,
    new_date: str,
    new_time: str
) -> str:
    """Reschedule an existing appointment to a new date/time."""
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


@tool(args_schema=CancelInput)
async def cancel_appointment(
    appointment_id: int,
    reason: Optional[str] = None
) -> str:
    """Cancel an existing appointment."""
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


@tool(args_schema=GetAppointmentsInput)
async def get_customer_appointments(customer_id: int) -> str:
    """Get all upcoming appointments for a customer. Use when customer wants to reschedule or cancel."""
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


@tool(args_schema=ListInventoryInput)
async def list_inventory(
    make: Optional[str] = None,
    max_results: int = 5
) -> str:
    """List vehicles available for test drives. Use when customer asks about available cars."""
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
