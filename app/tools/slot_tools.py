"""
Slot extraction tools for the booking agent.

These tools allow the LLM to store information it extracts from
the conversation, rather than relying on regex patterns.

Design:
- Tools return structured responses (SAVED:, PHONE_INCOMPLETE:, etc.)
- A global dict (_pending_slot_updates) stores updates by session_id
- The graph's postprocess node reads and clears these updates
- This pattern allows atomic slot updates without passing state through tools

NOTE: These tools now handle STT normalization automatically.
Phone numbers with spoken words ("five five five") are converted to digits.
"""
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from typing import Optional, Literal, Tuple
from datetime import date, timedelta
import re
import logging

logger = logging.getLogger("app.tools.slot_tools")

# Temporary storage for slot updates during agent execution
# Keyed by session_id
_pending_slot_updates: dict = {}


def normalize_spoken_phone(phone_input: str) -> Tuple[str, bool, str]:
    """
    Convert spoken phone numbers to digits.

    Handles STT transcriptions like:
    - "five five five one two three four five six seven"
    - "0 1 2 - 3 4 5 - 6 7 8 9"
    - Mixed: "my number is five 5 five, one two three, 4567"

    Returns:
        Tuple of (normalized_digits, is_valid, message)
        - normalized_digits: The phone number with only digits
        - is_valid: True if at least 10 digits
        - message: Helpful message for the agent
    """
    # Map of spoken words to digits (including common STT mishearings)
    word_to_digit = {
        'zero': '0', 'oh': '0', 'o': '0',
        'one': '1', 'won': '1',
        'two': '2', 'to': '2', 'too': '2', 'tu': '2',
        'three': '3', 'tree': '3', 'free': '3',
        'four': '4', 'for': '4', 'fore': '4',
        'five': '5', 'fife': '5',
        'six': '6', 'sicks': '6', 'sex': '6',
        'seven': '7',
        'eight': '8', 'ate': '8',
        'nine': '9', 'niner': '9', 'nein': '9',
    }

    # Work with lowercase, preserve original for logging
    original = phone_input
    phone_lower = phone_input.lower()

    # Replace word patterns with digits
    # Sort by length (longest first) to handle "seven" before "even" substring issues
    for word in sorted(word_to_digit.keys(), key=len, reverse=True):
        phone_lower = phone_lower.replace(word, word_to_digit[word])

    # Extract only digits
    digits = ''.join(c for c in phone_lower if c.isdigit())

    logger.info(f"[PHONE_NORMALIZE] Input: '{original}' -> Digits: '{digits}' (length: {len(digits)})")

    # Validate and return helpful message
    if len(digits) >= 10:
        # Format for readability
        if len(digits) == 10:
            formatted = f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
        elif len(digits) == 11 and digits[0] == '1':
            # US format with country code
            formatted = f"+1 ({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
        else:
            formatted = digits
        return digits, True, f"Phone number recognized: {formatted}"
    elif len(digits) >= 7:
        # Partial number - might be missing area code
        return digits, False, f"Got {len(digits)} digits ({digits}). Need at least 10 digits for a full phone number. Ask for area code."
    elif len(digits) > 0:
        # Very incomplete
        return digits, False, f"Only got {len(digits)} digits ({digits}). Ask customer to repeat their full phone number clearly."
    else:
        # No digits found
        return "", False, "Could not extract phone digits. Ask customer to say their phone number digit by digit."


async def _broadcast_slot_update(session_id: str, slot_name: str, slot_value: str, all_slots: dict):
    """Push immediate WebSocket update when a slot is filled."""
    try:
        from app.api.websocket import get_ws_manager
        ws_manager = get_ws_manager()
        if ws_manager:
            await ws_manager.send_message(session_id, {
                "type": "booking_slot_update",
                "slot_name": slot_name,
                "slot_value": slot_value,
                "all_slots": all_slots
            })
            logger.info(f"[WS] Broadcast slot update: {slot_name}={slot_value}")
    except Exception as e:
        # Don't fail if WS not available
        logger.debug(f"[WS] Could not broadcast slot update: {e}")


class BookingInfoInput(BaseModel):
    """Input schema for update_booking_info tool."""
    session_id: str = Field(description="The current session ID (always required)")
    appointment_type: Optional[Literal["service", "test_drive"]] = Field(
        None, description="Type of appointment: 'service' or 'test_drive'"
    )
    service_type: Optional[str] = Field(
        None, description="Type of service (e.g., 'oil change', 'brake service')"
    )
    vehicle_interest: Optional[str] = Field(
        None, description="Vehicle for test drive (e.g., 'Toyota Camry')"
    )
    preferred_date: Optional[str] = Field(
        None, description="Date in YYYY-MM-DD format (e.g., '2025-02-15')"
    )
    preferred_time: Optional[str] = Field(
        None, description="Time in HH:MM 24-hour format (e.g., '14:00' for 2 PM)"
    )
    customer_name: Optional[str] = Field(
        None, description="Customer's full name"
    )
    customer_phone: Optional[str] = Field(
        None, description="Phone number - digits only, at least 10 digits (e.g., '5551234567')"
    )
    customer_email: Optional[str] = Field(
        None, description="Email address with @ and . (e.g., 'john@gmail.com')"
    )


def get_pending_updates(session_id: str) -> dict:
    """Get and clear pending slot updates for a session."""
    updates = _pending_slot_updates.pop(session_id, {})
    return updates


def clear_pending_updates(session_id: str):
    """Clear pending updates without returning them."""
    _pending_slot_updates.pop(session_id, None)


@tool(args_schema=BookingInfoInput)
async def update_booking_info(
    session_id: str,
    appointment_type: Optional[str] = None,
    service_type: Optional[str] = None,
    vehicle_interest: Optional[str] = None,
    preferred_date: Optional[str] = None,
    preferred_time: Optional[str] = None,
    customer_name: Optional[str] = None,
    customer_phone: Optional[str] = None,
    customer_email: Optional[str] = None
) -> str:
    """Save booking information extracted from the conversation. Call immediately when user provides any booking info.
    Phone numbers are automatically normalized from spoken words (e.g., 'five five five' -> '555')."""
    if session_id not in _pending_slot_updates:
        _pending_slot_updates[session_id] = {}

    updates = _pending_slot_updates[session_id]
    saved = []
    warnings = []

    # Process and validate each field
    if appointment_type and appointment_type.lower() in ["service", "test_drive"]:
        updates["appointment_type"] = appointment_type.lower()
        saved.append(f"appointment_type: {appointment_type}")
        await _broadcast_slot_update(session_id, "appointment_type", appointment_type.lower(), updates)

    if service_type:
        updates["service_type"] = service_type
        saved.append(f"service_type: {service_type}")
        await _broadcast_slot_update(session_id, "service_type", service_type, updates)

    if vehicle_interest:
        updates["vehicle_interest"] = vehicle_interest
        saved.append(f"vehicle_interest: {vehicle_interest}")
        await _broadcast_slot_update(session_id, "vehicle_interest", vehicle_interest, updates)

    if preferred_date:
        # Validate date format or convert
        updates["preferred_date"] = preferred_date
        saved.append(f"preferred_date: {preferred_date}")
        await _broadcast_slot_update(session_id, "preferred_date", preferred_date, updates)

    if preferred_time:
        # Normalize time format
        updates["preferred_time"] = preferred_time
        saved.append(f"preferred_time: {preferred_time}")
        await _broadcast_slot_update(session_id, "preferred_time", preferred_time, updates)

    if customer_name:
        updates["customer_name"] = customer_name
        saved.append(f"customer_name: {customer_name}")
        await _broadcast_slot_update(session_id, "customer_name", customer_name, updates)

    if customer_phone:
        # Use STT-aware phone normalization
        digits, is_valid, message = normalize_spoken_phone(customer_phone)

        if is_valid:
            updates["customer_phone"] = digits
            # Format for display
            if len(digits) == 10:
                formatted = f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
            else:
                formatted = digits
            saved.append(f"customer_phone: {formatted}")
            await _broadcast_slot_update(session_id, "customer_phone", digits, updates)
            # Always remind to confirm
            warnings.append(f"CONFIRM_PHONE: {formatted}")
        else:
            # Return message so agent knows to ask for clarification
            return f"PHONE_INCOMPLETE: {message}"

    if customer_email:
        # Validate email format - LLM should have already normalized (@ and . present)
        email = customer_email.lower().strip()
        # Basic validation - check for @ and .
        if '@' in email and '.' in email:
            updates["customer_email"] = email
            saved.append(f"customer_email: {email}")
            await _broadcast_slot_update(session_id, "customer_email", email, updates)
        else:
            # Return validation error so LLM knows to ask user to repeat
            return f"VALIDATION_ERROR: Email '{customer_email}' is not valid (needs @ and .). Ask user to repeat clearly."

    if saved:
        result = f"SAVED: {', '.join(saved)}"
        if warnings:
            result += f"\n{' | '.join(warnings)}"
        return result
    else:
        return "NO_CHANGES: No valid information to save."


class SetCustomerInput(BaseModel):
    """Input schema for set_customer_identified tool."""
    session_id: str = Field(description="The current session ID")
    customer_id: int = Field(description="The customer's database ID from get_customer")
    customer_name: str = Field(description="The customer's name")


@tool(args_schema=SetCustomerInput)
def set_customer_identified(
    session_id: str,
    customer_id: int,
    customer_name: str
) -> str:
    """Mark customer as identified after get_customer returns CUSTOMER_FOUND."""
    if session_id not in _pending_slot_updates:
        _pending_slot_updates[session_id] = {}

    _pending_slot_updates[session_id]["_customer_identified"] = True
    _pending_slot_updates[session_id]["_customer_id"] = customer_id
    _pending_slot_updates[session_id]["_customer_name"] = customer_name

    return f"CUSTOMER_SET: Customer {customer_name} (ID: {customer_id}) is now the active customer for this booking."


@tool
def get_todays_date() -> str:
    """Get today's date and upcoming days. Use to convert 'tomorrow', 'next Monday' to YYYY-MM-DD format."""
    today = date.today()
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    result = f"TODAY: {today.strftime('%Y-%m-%d')} ({days[today.weekday()]})\n"
    result += "UPCOMING:\n"

    for i in range(1, 8):
        d = today + timedelta(days=i)
        label = "Tomorrow" if i == 1 else days[d.weekday()]
        result += f"  {label}: {d.strftime('%Y-%m-%d')}\n"

    return result
