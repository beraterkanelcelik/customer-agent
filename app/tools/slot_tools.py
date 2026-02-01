"""
Slot extraction tools for the booking agent.

These tools allow the LLM to store information it extracts from
the conversation, rather than relying on regex patterns.
"""
from langchain_core.tools import tool
from typing import Optional
from datetime import date, timedelta
import re

# Temporary storage for slot updates during agent execution
# Keyed by session_id
_pending_slot_updates: dict = {}


def normalize_phone_number(phone: str) -> str:
    """
    Normalize phone number from various formats including spoken words.

    Handles:
    - "one five five one three three two one two three" -> "1551332123"
    - "155-133-2123" -> "1551332123"
    - "155 133 2123" -> "1551332123"
    - Mixed formats
    """
    if not phone:
        return ""

    # Word to digit mapping
    word_to_digit = {
        'zero': '0', 'one': '1', 'two': '2', 'three': '3', 'four': '4',
        'five': '5', 'six': '6', 'seven': '7', 'eight': '8', 'nine': '9',
        'oh': '0', 'o': '0',  # Common alternatives for zero
    }

    phone_lower = phone.lower()

    # Replace word numbers with digits
    for word, digit in word_to_digit.items():
        phone_lower = phone_lower.replace(word, digit)

    # Extract only digits
    digits = ''.join(filter(str.isdigit, phone_lower))

    return digits


def normalize_email(email: str) -> str:
    """
    Normalize email from spoken format.

    Handles:
    - "john at gmail dot com" -> "john@gmail.com"
    - "john@gmail.com" -> "john@gmail.com"
    - "johngmail.com" -> "john@gmail.com" (missing @)
    - "elcelikberaterkhan.com" -> might be "elcelik@beraterkan.com" or similar
    """
    if not email:
        return ""

    email = email.lower().strip()

    # Replace spoken formats
    email = email.replace(" at ", "@")
    email = email.replace(" dot ", ".")
    email = email.replace("dot com", ".com")
    email = email.replace("dotcom", ".com")

    # Remove extra spaces
    email = email.replace(" ", "")

    # Handle common domain misspellings from STT
    email = email.replace("gmailcom", "gmail.com")
    email = email.replace("yahoocom", "yahoo.com")
    email = email.replace("hotmailcom", "hotmail.com")
    email = email.replace("outlookcom", "outlook.com")

    # If no @ but contains a known domain, try to insert @
    if "@" not in email:
        known_domains = ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com"]
        for domain in known_domains:
            if email.endswith(domain):
                # Insert @ before the domain
                email = email[:-len(domain)] + "@" + domain
                break

    # Handle cases like "elcelikberaterkan.com" where domain might be unclear
    # If it ends with .com but no @ and no known domain, try to find a reasonable split
    if "@" not in email and email.endswith(".com"):
        # This is a heuristic - look for common patterns
        # Just return as-is and let validation fail if invalid
        pass

    return email


def get_pending_updates(session_id: str) -> dict:
    """Get and clear pending slot updates for a session."""
    updates = _pending_slot_updates.pop(session_id, {})
    return updates


def clear_pending_updates(session_id: str):
    """Clear pending updates without returning them."""
    _pending_slot_updates.pop(session_id, None)


@tool
def update_booking_info(
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
    """
    Save booking information extracted from the conversation.

    Call this tool whenever you identify booking-relevant information
    from what the user said. You can call it multiple times as you
    learn more information.

    IMPORTANT: Only include fields that you are confident about.
    Do NOT guess or make up values.

    Args:
        session_id: The current session ID (always required)
        appointment_type: "service" or "test_drive" if user specified
        service_type: Type of service (e.g., "oil change", "brake service")
        vehicle_interest: Vehicle for test drive (e.g., "Volkswagen Golf 7")
        preferred_date: Date in YYYY-MM-DD format (convert relative dates like "tomorrow")
        preferred_time: Time in HH:MM format (24-hour, e.g., "14:00" for 2 PM)
        customer_name: Customer's full name
        customer_phone: Customer's phone number (digits only, e.g., "5551234567")
        customer_email: Customer's email address

    Returns:
        Confirmation of what was saved.
    """
    if session_id not in _pending_slot_updates:
        _pending_slot_updates[session_id] = {}

    updates = _pending_slot_updates[session_id]
    saved = []

    # Process and validate each field
    if appointment_type and appointment_type.lower() in ["service", "test_drive"]:
        updates["appointment_type"] = appointment_type.lower()
        saved.append(f"appointment_type: {appointment_type}")

    if service_type:
        updates["service_type"] = service_type
        saved.append(f"service_type: {service_type}")

    if vehicle_interest:
        updates["vehicle_interest"] = vehicle_interest
        saved.append(f"vehicle_interest: {vehicle_interest}")

    if preferred_date:
        # Validate date format or convert
        updates["preferred_date"] = preferred_date
        saved.append(f"preferred_date: {preferred_date}")

    if preferred_time:
        # Normalize time format
        updates["preferred_time"] = preferred_time
        saved.append(f"preferred_time: {preferred_time}")

    if customer_name:
        updates["customer_name"] = customer_name
        saved.append(f"customer_name: {customer_name}")

    if customer_phone:
        # Normalize phone number (handles spoken words like "one five five")
        digits = normalize_phone_number(customer_phone)
        # Accept phone numbers with at least 7 digits (some regions have shorter numbers)
        if len(digits) >= 7:
            updates["customer_phone"] = digits
            saved.append(f"customer_phone: {digits}")

    if customer_email:
        # Normalize email (handles spoken format like "at gmail dot com")
        normalized_email = normalize_email(customer_email)
        # Basic validation - just check for @ and .
        if '@' in normalized_email and '.' in normalized_email:
            updates["customer_email"] = normalized_email
            saved.append(f"customer_email: {normalized_email}")

    if saved:
        return f"SAVED: {', '.join(saved)}"
    else:
        return "NO_CHANGES: No valid information to save."


@tool
def set_customer_identified(
    session_id: str,
    customer_id: int,
    customer_name: str
) -> str:
    """
    Mark that a customer has been identified in the system.

    Call this after successfully looking up a customer with get_customer
    and receiving a CUSTOMER_FOUND response.

    Args:
        session_id: The current session ID
        customer_id: The customer's database ID
        customer_name: The customer's name

    Returns:
        Confirmation.
    """
    if session_id not in _pending_slot_updates:
        _pending_slot_updates[session_id] = {}

    _pending_slot_updates[session_id]["_customer_identified"] = True
    _pending_slot_updates[session_id]["_customer_id"] = customer_id
    _pending_slot_updates[session_id]["_customer_name"] = customer_name

    return f"CUSTOMER_SET: Customer {customer_name} (ID: {customer_id}) is now the active customer for this booking."


@tool
def get_todays_date() -> str:
    """
    Get today's date and the next few days for reference.

    Use this when you need to convert relative dates like
    "tomorrow", "next Monday", etc. to actual dates.

    Returns:
        Today's date and upcoming days.
    """
    today = date.today()
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    result = f"TODAY: {today.strftime('%Y-%m-%d')} ({days[today.weekday()]})\n"
    result += "UPCOMING:\n"

    for i in range(1, 8):
        d = today + timedelta(days=i)
        label = "Tomorrow" if i == 1 else days[d.weekday()]
        result += f"  {label}: {d.strftime('%Y-%m-%d')}\n"

    return result
