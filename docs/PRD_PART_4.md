# Car Dealership Voice Agent - PRD Part 4 of 6
## Tools & Background Tasks

---

# SECTION 1: FAQ TOOLS

## 1.1 app/tools/faq_tools.py

```python
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
```

---

# SECTION 2: CUSTOMER TOOLS

## 2.1 app/tools/customer_tools.py

```python
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
```

---

# SECTION 3: BOOKING TOOLS

## 3.1 app/tools/booking_tools.py

```python
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
```

---

# SECTION 4: BACKGROUND TASK SYSTEM

## 4.1 app/background/state_store.py

```python
import asyncio
import json
from typing import Dict, Optional, Any
from datetime import datetime
import redis.asyncio as redis

from app.config import get_settings
from app.schemas.state import ConversationState
from app.schemas.task import BackgroundTask, Notification

settings = get_settings()


class StateStore:
    """
    Shared state store for conversation sessions.
    
    Uses Redis for production, falls back to in-memory for development.
    """
    
    def __init__(self):
        self._memory_store: Dict[str, dict] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._redis: Optional[redis.Redis] = None
        self._use_redis = "redis://" in settings.redis_url
    
    async def connect(self):
        """Initialize Redis connection."""
        if self._use_redis:
            self._redis = redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            # Test connection
            try:
                await self._redis.ping()
                print("Connected to Redis")
            except Exception as e:
                print(f"Redis connection failed, using memory: {e}")
                self._use_redis = False
    
    async def disconnect(self):
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
    
    def _get_lock(self, session_id: str) -> asyncio.Lock:
        """Get or create lock for session."""
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]
    
    async def get_state(self, session_id: str) -> Optional[ConversationState]:
        """Get conversation state for session."""
        if self._use_redis:
            data = await self._redis.get(f"session:{session_id}")
            if data:
                return ConversationState(**json.loads(data))
            return None
        else:
            async with self._get_lock(session_id):
                data = self._memory_store.get(session_id)
                if data:
                    return ConversationState(**data)
                return None
    
    async def set_state(self, session_id: str, state: ConversationState):
        """Save conversation state."""
        state.last_updated = datetime.utcnow()
        data = state.model_dump(mode="json")
        
        if self._use_redis:
            await self._redis.set(
                f"session:{session_id}",
                json.dumps(data, default=str),
                ex=settings.session_timeout_minutes * 60
            )
        else:
            async with self._get_lock(session_id):
                self._memory_store[session_id] = data
    
    async def update_state(self, session_id: str, updates: dict):
        """Partial update of state."""
        state = await self.get_state(session_id)
        if state:
            for key, value in updates.items():
                if hasattr(state, key):
                    setattr(state, key, value)
            await self.set_state(session_id, state)
    
    async def add_task(self, session_id: str, task: BackgroundTask):
        """Add a background task to session."""
        state = await self.get_state(session_id)
        if state:
            state.pending_tasks.append(task)
            await self.set_state(session_id, state)
    
    async def update_task(self, session_id: str, task_id: str, updates: dict):
        """Update a specific task."""
        state = await self.get_state(session_id)
        if state:
            for task in state.pending_tasks:
                if task.task_id == task_id:
                    for key, value in updates.items():
                        if hasattr(task, key):
                            setattr(task, key, value)
                    break
            await self.set_state(session_id, state)
    
    async def add_notification(self, session_id: str, notification: Notification):
        """Add notification to session queue."""
        state = await self.get_state(session_id)
        if state:
            state.notifications_queue.append(notification)
            await self.set_state(session_id, state)
    
    async def delete_session(self, session_id: str):
        """Delete a session."""
        if self._use_redis:
            await self._redis.delete(f"session:{session_id}")
        else:
            async with self._get_lock(session_id):
                self._memory_store.pop(session_id, None)


# Global instance
state_store = StateStore()
```

## 4.2 app/background/worker.py

```python
import asyncio
import random
from datetime import datetime, timedelta
from typing import Optional, Callable, Awaitable

from app.config import get_settings
from app.schemas.task import (
    BackgroundTask, Notification, HumanCheckResult,
    TaskStatus, TaskType, NotificationPriority
)
from .state_store import state_store

settings = get_settings()


class BackgroundWorker:
    """
    Handles async background tasks that don't block the conversation.
    """
    
    def __init__(self):
        self.notification_callback: Optional[Callable[[str, Notification], Awaitable[None]]] = None
    
    def set_notification_callback(self, callback: Callable[[str, Notification], Awaitable[None]]):
        """Set callback for high-priority notifications."""
        self.notification_callback = callback
    
    async def execute_human_check(
        self,
        task_id: str,
        session_id: str,
        customer_phone: Optional[str] = None,
        reason: Optional[str] = None,
        urgency: str = "medium"
    ):
        """
        Execute human availability check as background task.
        
        This simulates:
        1. Checking if human agents are available
        2. If yes: prepare to transfer
        3. If no: schedule callback and send email
        """
        
        # Update task status to running
        await state_store.update_task(session_id, task_id, {
            "status": TaskStatus.RUNNING
        })
        
        # Simulate checking (5-10 seconds)
        delay = random.uniform(
            settings.human_check_min_seconds,
            settings.human_check_max_seconds
        )
        await asyncio.sleep(delay)
        
        # Simulate availability (configurable chance)
        human_available = random.random() < settings.human_availability_chance
        
        if human_available:
            # Human is available!
            result = HumanCheckResult(
                human_available=True,
                human_agent_id="agent_sarah_01",
                human_agent_name="Sarah",
                estimated_wait="connecting now"
            )
            
            message = (
                "Great news! Sarah from our team is available now. "
                "I'm connecting you. Sarah, I'm transferring a customer who needs assistance."
            )
            priority = NotificationPriority.INTERRUPT
            
        else:
            # Human not available - schedule callback
            callback_time = self._get_next_callback_slot()
            
            result = HumanCheckResult(
                human_available=False,
                reason="All team members are currently helping other customers",
                callback_scheduled=callback_time,
                email_sent=True
            )
            
            # Simulate sending email
            await self._send_callback_email(customer_phone, callback_time, reason)
            
            message = (
                f"I wasn't able to reach a team member right now - they're all helping other customers. "
                f"I've scheduled a callback for {callback_time} and sent you a confirmation email. "
                f"Someone will definitely call you then. Is there anything else I can help with in the meantime?"
            )
            priority = NotificationPriority.HIGH
        
        # Update task as completed
        await state_store.update_task(session_id, task_id, {
            "status": TaskStatus.COMPLETED,
            "completed_at": datetime.utcnow(),
            "result": result.model_dump(),
            "human_available": result.human_available,
            "human_agent_id": result.human_agent_id,
            "human_agent_name": result.human_agent_name,
            "callback_scheduled": result.callback_scheduled
        })
        
        # Create and send notification
        notification = Notification(
            notification_id=f"notif_{int(datetime.utcnow().timestamp() * 1000)}",
            task_id=task_id,
            message=message,
            priority=priority
        )
        
        await state_store.add_notification(session_id, notification)
        
        # Trigger callback for high priority
        if self.notification_callback and priority in [NotificationPriority.HIGH, NotificationPriority.INTERRUPT]:
            await self.notification_callback(session_id, notification)
    
    def _get_next_callback_slot(self) -> str:
        """Get next available callback time slot."""
        now = datetime.now()
        
        # Round up to next 30 minute slot + 1 hour
        minutes = 30 * ((now.minute // 30) + 1)
        if minutes >= 60:
            callback_time = now.replace(
                hour=now.hour + 2,
                minute=0,
                second=0,
                microsecond=0
            )
        else:
            callback_time = now.replace(
                hour=now.hour + 1,
                minute=minutes,
                second=0,
                microsecond=0
            )
        
        # Don't schedule outside business hours
        if callback_time.hour >= 17:  # After 5 PM
            callback_time = callback_time.replace(hour=9, minute=0) + timedelta(days=1)
        if callback_time.hour < 9:  # Before 9 AM
            callback_time = callback_time.replace(hour=9, minute=0)
        
        # Skip Sunday
        if callback_time.weekday() == 6:
            callback_time += timedelta(days=1)
        
        return callback_time.strftime("%I:%M %p on %A")
    
    async def _send_callback_email(
        self,
        phone: Optional[str],
        callback_time: str,
        reason: Optional[str]
    ):
        """Simulate sending callback confirmation email."""
        # In production, this would integrate with email service
        await asyncio.sleep(0.5)  # Simulate API call
        print(f"[EMAIL] Callback scheduled for {phone or 'customer'} at {callback_time}")
        print(f"[EMAIL] Reason: {reason or 'Customer requested human assistance'}")


# Global instance
background_worker = BackgroundWorker()
```

## 4.3 app/background/__init__.py

```python
from .state_store import state_store, StateStore
from .worker import background_worker, BackgroundWorker

__all__ = [
    "state_store",
    "StateStore", 
    "background_worker",
    "BackgroundWorker"
]
```

---

# SECTION 5: TOOLS PACKAGE

## 5.1 app/tools/__init__.py

```python
from .faq_tools import search_faq, list_services
from .customer_tools import get_customer, create_customer
from .booking_tools import (
    check_availability,
    book_appointment,
    reschedule_appointment,
    cancel_appointment,
    get_customer_appointments,
    list_inventory
)

__all__ = [
    # FAQ
    "search_faq",
    "list_services",
    # Customer
    "get_customer",
    "create_customer",
    # Booking
    "check_availability",
    "book_appointment",
    "reschedule_appointment",
    "cancel_appointment",
    "get_customer_appointments",
    "list_inventory",
]
```

---

# SECTION 6: CONVERSATION SERVICE

## 6.1 app/services/conversation.py

```python
from typing import Optional
from datetime import datetime
from langchain_core.messages import HumanMessage, AIMessage

from app.schemas.state import ConversationState
from app.schemas.api import ChatResponse
from app.background.state_store import state_store
from app.agents.graph import process_message


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
        """
        # Get or create session
        state = await state_store.get_state(session_id)
        if not state:
            state = await self.create_session(session_id)
        
        # Process through LangGraph
        updated_state = await process_message(
            session_id=session_id,
            user_message=user_message,
            current_state=state
        )
        
        # Save updated state
        await state_store.set_state(session_id, updated_state)
        
        # Get response (last AI message)
        response_text = ""
        for msg in reversed(updated_state.messages):
            if isinstance(msg, AIMessage):
                response_text = msg.content
                break
        
        return ChatResponse(
            session_id=session_id,
            response=response_text,
            agent_type=updated_state.current_agent.value if updated_state.current_agent else "router",
            intent=updated_state.detected_intent.value if updated_state.detected_intent else None,
            confidence=updated_state.confidence,
            customer=updated_state.customer,
            booking_slots=updated_state.booking_slots.model_dump() if updated_state.booking_slots else None,
            pending_tasks=updated_state.pending_tasks
        )
    
    async def end_session(self, session_id: str):
        """End and cleanup a session."""
        await state_store.delete_session(session_id)


# Global instance
conversation_service = ConversationService()
```

---

**END OF PART 4**

Say "continue" to get Part 5: Voice Worker (STT/TTS/LiveKit)
