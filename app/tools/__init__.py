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
from .slot_tools import (
    update_booking_info,
    set_customer_identified,
    get_todays_date,
    get_pending_updates,
    clear_pending_updates
)
from .escalation_tools import request_human_agent
from .call_tools import end_call, get_pending_call_action, clear_pending_call_actions

# All tools available to the agent
ALL_TOOLS = [
    # FAQ
    search_faq,
    list_services,
    # Customer
    get_customer,
    create_customer,
    # Booking
    check_availability,
    book_appointment,
    reschedule_appointment,
    cancel_appointment,
    get_customer_appointments,
    list_inventory,
    # Slot management
    update_booking_info,
    set_customer_identified,
    get_todays_date,
    # Escalation (for sales)
    request_human_agent,
    # Call control
    end_call,
]

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
    # Slot management
    "update_booking_info",
    "set_customer_identified",
    "get_todays_date",
    "get_pending_updates",
    "clear_pending_updates",
    # Escalation
    "request_human_agent",
    # Call control
    "end_call",
    "get_pending_call_action",
    "clear_pending_call_actions",
    # All tools list
    "ALL_TOOLS",
]
