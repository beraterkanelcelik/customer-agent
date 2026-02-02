"""
Unified Agent - Single agent with all capabilities.

This agent handles everything: FAQ, booking, escalation, greetings, goodbyes.
No routing needed - the LLM decides what to do based on context.

Advantages over multi-agent architecture:
- No routing issues (can't lose context mid-booking)
- Simpler state management
- More natural conversation flow
- LLM can handle mixed intents (e.g., "thanks, my name is John")
"""
import json
import logging
import asyncio
import time
from typing import Tuple, Dict, Any, List, Optional
from datetime import date, timedelta

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage, ToolMessage

from app.config import get_settings
from app.schemas.state import ConversationState, BookingSlots
from app.schemas.enums import AppointmentType, TaskType, TaskStatus
from app.schemas.task import BackgroundTask

# Import all tools
from app.tools.faq_tools import search_faq, list_services
from app.tools.booking_tools import (
    check_availability, book_appointment,
    reschedule_appointment, cancel_appointment,
    get_customer_appointments, list_inventory
)
from app.tools.customer_tools import get_customer, create_customer
from app.tools.slot_tools import (
    update_booking_info, set_customer_identified, get_todays_date,
    get_pending_updates
)
from app.tools.call_tools import end_call

settings = get_settings()
logger = logging.getLogger("app.agents.unified")


UNIFIED_SYSTEM_PROMPT = """You are a friendly voice assistant for Springfield Auto dealership.

## CURRENT CONTEXT
{context}

## VOICE/STT AWARENESS - CRITICAL

### Phone Numbers (Automatic Normalization)
Input comes from speech-to-text which may be messy. The tool handles this automatically:
- "five five five one two three four five six seven" → 5551234567
- "0 1 2 - 3 4 5 - 6 7 8 9" → 0123456789
- Mixed: "my number is five 5 five, one two three, 4567" → 5551234567

Just pass whatever the user says to update_booking_info - it will normalize spoken words to digits.
ALWAYS confirm the normalized number: "I have (555) 123-4567. Is that correct?"
If unclear or incomplete, ask them to repeat digit by digit.

### Emails (YOU must normalize)
Speech-to-text garbles emails - reconstruct intelligently:
- "at/add/et" → "@"
- "dot" → "."
- "gmail/g mail/gee mail" → "gmail"
Examples: "john add gmail dot com" → john@gmail.com

ALWAYS confirm: "Your email is john@gmail.com, correct?"

## TOOL CALLING - CRITICAL CAPABILITY

**You can output BOTH text AND tool calls in a single response.**

Your response has two parts that work together:
1. **content**: Text message (what you say to the user)
2. **tool_calls**: Actions to execute (checking availability, booking, etc.)

You MUST use both simultaneously when needed. For example, when a user asks about availability:
- Your content: "Let me check that for you."
- Your tool_calls: [check_availability with the date/time]

Both happen in ONE response. The system will:
1. Execute your tool calls
2. Show you the results
3. You then provide the final answer

**CORRECT behavior** (single response with text + tool):
- User: "What cars do you have?"
  → content: "Let me see what's available."
  → tool_calls: list_inventory

- User: "Is tomorrow at 2pm available?"
  → content: "Let me check that time."
  → tool_calls: check_availability(date=tomorrow, time=14:00)

- User: "Book it for 10am"
  → content: "Let me get that scheduled."
  → tool_calls: book_appointment(...)

**WRONG behavior** (DO NOT do this):
- Responding with ONLY text like "Let me check..." without actually calling the tool
- Waiting for the user to ask again before calling the tool
- Saying you will do something but not including the tool call

**IMPORTANT**: When you need information (availability, inventory, customer lookup), you MUST include the tool call in your response. Never just say "let me check" without the actual tool call.

## YOUR CAPABILITIES

### 1. Answer Questions (FAQ)
- Use search_faq for hours, location, financing, policies
- Use list_services for service pricing and duration

### 2. Book Appointments - FOLLOW THESE STEPS IN ORDER

**BOOKING RULES (MANDATORY ORDER - DO NOT SKIP STEPS):**

1. **CUSTOMER FIRST**: Before collecting ANY booking details, get customer info:
   - Ask for their NAME first
   - Then ask for their PHONE number
   - Then ask for their EMAIL
   - ONLY proceed to step 2 after you have all three!

2. **CREATE CUSTOMER - CRITICAL**: After collecting name + phone + email:
   - IMMEDIATELY call create_customer to save them
   - This gives you customer_id REQUIRED for booking
   - Without this step, book_appointment will FAIL!

3. **APPOINTMENT TYPE**: Ask if they want a service appointment or test drive

4. **DETAILS**: Based on type:
   - Service: Ask what service they need (oil change, brakes, etc.)
   - Test Drive: Call list_inventory FIRST, then ask what vehicle interests them

5. **DATE/TIME**:
   - Ask for their preferred DATE first
   - Call check_availability to verify the slot is open
   - Then confirm the time with the customer

6. **CONFIRM**: Read back ALL collected details:
   - "Let me confirm: [Name], I have you down for a [type] on [date] at [time]. Is that correct?"
   - Wait for explicit "yes" or confirmation

7. **BOOK**: Only after they confirm, call book_appointment with customer_id

**IMPORTANT**: If customer tries to give booking details before you have their info,
politely redirect: "I'd be happy to help with that! First, may I have your name?"

### 3. Manage Appointments
- Reschedule or cancel existing appointments
- Need customer phone to look up their appointments

### 4. Human Escalation
- If customer wants to speak with a human or is frustrated
- Say you'll check availability (background task will handle it)

### 5. Greetings & Goodbyes
- Greet warmly, offer help
- When customer says goodbye (bye, goodbye, that's all, etc.):
  1. Check if they have any pending needs
  2. If no pending needs, ALWAYS call the end_call tool to properly close the call
  3. Example: User says "bye" -> call end_call with a friendly farewell

## VOICE INTERFACE RULES
- Keep responses SHORT (1-2 sentences) - this is voice, not text
- Ask ONE question at a time
- Don't repeat information already collected
- Be warm and professional

## WHEN TO END CALLS (IMPORTANT)
You MUST call the end_call tool when:
- Customer says "goodbye", "bye", "that's all", "I'm done", etc. (AND has no pending needs)
- Booking is complete AND customer confirms they're done
- Customer says "thanks, bye" or similar closing phrases

When calling end_call:
1. Your response should be EMPTY or very minimal (like "Goodbye!")
2. The farewell_message in end_call should contain the full goodbye message
3. The voice system will speak the farewell_message AFTER your response

Example when user says "bye":
- Response: "" (empty - let end_call handle the farewell)
- end_call(farewell_message="Thank you for calling Springfield Auto! Have a great day!")

DO NOT just say goodbye - you MUST call end_call to properly close the connection.
Never end mid-conversation or with unanswered questions.

## IMPORTANT
- If booking is in progress, stay focused on completing it
- You can handle mixed messages like "thanks, my name is John" - extract the name
- If something is unclear, politely ask for clarification"""


def get_date_context() -> str:
    """Get current date context for the agent."""
    today = date.today()
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    lines = [f"TODAY: {today.strftime('%Y-%m-%d')} ({days[today.weekday()]})"]

    # Add next 7 days for reference
    upcoming = []
    for i in range(1, 8):
        d = today + timedelta(days=i)
        label = "Tomorrow" if i == 1 else days[d.weekday()]
        upcoming.append(f"{label}={d.strftime('%Y-%m-%d')}")

    lines.append(f"UPCOMING: {', '.join(upcoming)}")
    return "\n".join(lines)


def build_context(state: ConversationState) -> str:
    """Build context string showing current booking/customer status for the LLM."""
    lines = []

    # Date context (always included)
    lines.append(get_date_context())
    lines.append("")

    # Customer status
    if state.customer.is_identified:
        lines.append(f"CUSTOMER: {state.customer.name} (ID: {state.customer.customer_id}) - VERIFIED")
    else:
        lines.append("CUSTOMER: Not yet identified")

    # Booking status
    slots = state.booking_slots
    if slots.appointment_type or any([
        slots.service_type, slots.vehicle_interest, slots.preferred_date,
        slots.preferred_time, slots.customer_name, slots.customer_phone
    ]):
        lines.append("")
        lines.append("BOOKING IN PROGRESS:")

        if slots.appointment_type:
            appt_type = slots.appointment_type.value if hasattr(slots.appointment_type, 'value') else slots.appointment_type
            lines.append(f"  Type: {appt_type.upper()}")
        else:
            lines.append("  Type: NOT SET")

        if slots.vehicle_interest:
            lines.append(f"  Vehicle: {slots.vehicle_interest}")
        if slots.service_type:
            lines.append(f"  Service: {slots.service_type}")

        lines.append(f"  Date: {slots.preferred_date or 'NOT SET'}")
        lines.append(f"  Time: {slots.preferred_time or 'NOT SET'}")
        lines.append(f"  Name: {slots.customer_name or 'NOT SET'}")
        lines.append(f"  Phone: {slots.customer_phone or 'NOT SET'}")
        lines.append(f"  Email: {slots.customer_email or 'NOT SET'}")

        # What's still needed
        missing = slots.get_missing_slots(is_new_customer=not state.customer.is_identified)
        if missing:
            lines.append(f"  STILL NEEDED: {', '.join(missing)}")
        else:
            lines.append("  ALL INFO COLLECTED - Ready to book!")
    else:
        lines.append("")
        lines.append("BOOKING: No booking in progress")

    # Escalation status
    if state.escalation_in_progress:
        status = state.human_agent_status.value if state.human_agent_status else "checking"
        lines.append("")
        lines.append(f"ESCALATION: In progress ({status})")

    return "\n".join(lines)


class UnifiedAgent:
    """
    Single agent that handles all customer interactions.

    No routing, no handoffs - just one capable agent with all tools.
    """

    def __init__(self, background_worker=None):
        self.llm = ChatOpenAI(
            model=settings.openai_model,
            temperature=0.3,
            api_key=settings.openai_api_key
        )
        self.background_worker = background_worker

        # All tools available to the agent
        self.tools = [
            # FAQ tools
            search_faq,
            list_services,
            # Booking tools
            check_availability,
            book_appointment,
            reschedule_appointment,
            cancel_appointment,
            get_customer_appointments,
            list_inventory,
            # Customer tools
            get_customer,
            create_customer,
            # Slot management tools
            update_booking_info,
            set_customer_identified,
            get_todays_date,
            # Call control
            end_call,
        ]

        # Bind tools to LLM
        self.llm_with_tools = self.llm.bind_tools(self.tools)

    def set_background_worker(self, worker):
        """Set the background worker for escalation tasks."""
        self.background_worker = worker

    async def handle(
        self,
        user_message: str,
        state: ConversationState,
        chat_history: List[BaseMessage] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Process user message and return response with state updates.

        Args:
            user_message: The user's message
            state: Current conversation state
            chat_history: Previous messages (optional)

        Returns:
            Tuple of (response_text, state_updates_dict)
        """
        logger.info(f"[UNIFIED] Processing: '{user_message}'")
        logger.info(f"[UNIFIED] Chat history has {len(chat_history) if chat_history else 0} messages")

        # Build context (booking status, customer info, escalation status)
        context = build_context(state)

        system_prompt = UNIFIED_SYSTEM_PROMPT.format(context=context)

        # Classify intent for state tracking
        detected_intent, confidence = self._classify_intent(user_message, state)
        logger.info(f"[UNIFIED] Classified intent: {detected_intent} ({confidence:.0%})")

        # Check if this looks like an escalation request
        is_escalation = self._detect_escalation(user_message)

        # Build messages for LLM - include full chat history for continuity
        messages = [SystemMessage(content=system_prompt)]

        # Add chat history (previous messages) for conversation continuity
        if chat_history:
            # Keep last 10 exchanges (20 messages) to avoid context overflow
            recent_history = chat_history[-20:] if len(chat_history) > 20 else chat_history
            for msg in recent_history:
                if isinstance(msg, HumanMessage):
                    messages.append(HumanMessage(content=msg.content))
                elif isinstance(msg, AIMessage) and msg.content:
                    messages.append(AIMessage(content=msg.content))

        # Add current user message
        messages.append(HumanMessage(content=user_message))

        logger.info(f"[UNIFIED] Sending {len(messages)} messages to LLM")

        # State updates to return
        state_updates = {
            "detected_intent": detected_intent,
            "confidence": confidence
        }

        # Handle escalation specially (spawns background task)
        if is_escalation and not state.escalation_in_progress:
            response, task = await self._handle_escalation(user_message, state)
            state_updates["escalation_in_progress"] = True
            state_updates["pending_tasks"] = state.pending_tasks + [task]
            state_updates["waiting_for_background"] = True
            return response, state_updates

        # Process with tools - let LLM handle everything
        response = None
        max_iterations = 5

        for iteration in range(max_iterations):
            ai_response = await self.llm_with_tools.ainvoke(messages)
            logger.info(f"[UNIFIED] LLM response (iter {iteration})")

            # Check for tool calls
            if hasattr(ai_response, 'tool_calls') and ai_response.tool_calls:
                logger.info(f"[UNIFIED] Tool calls: {[tc['name'] for tc in ai_response.tool_calls]}")

                messages.append(ai_response)

                for tool_call in ai_response.tool_calls:
                    tool_name = tool_call['name']
                    tool_args = tool_call['args']
                    tool_id = tool_call['id']

                    tool_result = await self._execute_tool(tool_name, tool_args, state)

                    messages.append(ToolMessage(
                        content=str(tool_result),
                        tool_call_id=tool_id
                    ))

                continue

            # No tool calls - this is the final response
            response = ai_response.content
            if not response:
                logger.warning("[UNIFIED] LLM returned empty response")
                response = "I'm here to help. What would you like to do?"
            logger.info(f"[UNIFIED] Final response: '{response[:100]}...'")
            break

        # If we exhausted iterations without a response
        if response is None:
            logger.error("[UNIFIED] Failed to get response after max iterations")
            response = "I apologize, I'm having trouble processing that. Could you please try again?"

        # Apply slot updates from tools
        updated_slots, raw_updates = self._apply_slot_updates(state)
        state_updates["booking_slots"] = updated_slots

        # Check for customer identification
        if raw_updates.get("_customer_identified"):
            from app.schemas.customer import CustomerContext
            state_updates["customer"] = CustomerContext(
                customer_id=raw_updates.get("_customer_id"),
                name=raw_updates.get("_customer_name"),
                phone=raw_updates.get("_customer_phone") or updated_slots.customer_phone,
                email=raw_updates.get("_customer_email") or updated_slots.customer_email,
                is_identified=True
            )

        # Check for confirmed appointment
        if raw_updates.get("_confirmed_appointment"):
            from app.schemas.state import ConfirmedAppointment
            conf_data = raw_updates["_confirmed_appointment"]
            state_updates["confirmed_appointment"] = ConfirmedAppointment(
                appointment_id=conf_data.get("appointment_id"),
                appointment_type=conf_data.get("appointment_type"),
                scheduled_date=conf_data.get("scheduled_date"),
                scheduled_time=conf_data.get("scheduled_time"),
                customer_name=conf_data.get("customer_name"),
                service_type=conf_data.get("service_type"),
                vehicle=conf_data.get("vehicle"),
                confirmation_email=conf_data.get("customer_email")
            )

        return response, state_updates

    def _detect_escalation(self, message: str) -> bool:
        """Detect if user wants to speak with a human."""
        msg_lower = message.lower()
        escalation_phrases = [
            "speak to a human", "talk to a person", "real person",
            "speak to someone", "talk to someone", "human agent",
            "manager", "supervisor", "representative",
            "speak to a rep", "talk to a rep"
        ]
        return any(phrase in msg_lower for phrase in escalation_phrases)

    def _classify_intent(self, message: str, state: ConversationState) -> Tuple[Optional[str], float]:
        """
        Classify user intent based on keywords and context.

        Returns:
            Tuple of (intent_type, confidence)
        """
        from app.schemas.enums import IntentType

        msg_lower = message.lower()

        # Escalation keywords - highest priority
        escalation_keywords = ["human", "person", "manager", "supervisor", "representative", "speak to", "talk to"]
        if any(kw in msg_lower for kw in escalation_keywords):
            return IntentType.ESCALATION.value, 0.95

        # Greeting keywords
        greeting_keywords = ["hello", "hi ", "hey", "good morning", "good afternoon", "good evening", "howdy"]
        if any(kw in msg_lower or msg_lower.startswith(kw.strip()) for kw in greeting_keywords):
            # Check if it's a pure greeting (short message)
            if len(msg_lower.split()) <= 5:
                return IntentType.GREETING.value, 0.9

        # Goodbye keywords
        goodbye_keywords = ["goodbye", "bye", "see you", "take care", "have a good", "thanks for", "that's all"]
        if any(kw in msg_lower for kw in goodbye_keywords):
            return IntentType.GOODBYE.value, 0.85

        # Booking/scheduling keywords
        booking_keywords = ["book", "schedule", "appointment", "reserve", "set up", "make an"]
        if any(kw in msg_lower for kw in booking_keywords):
            # Determine if service or test drive
            if "test drive" in msg_lower or "test-drive" in msg_lower:
                return IntentType.BOOK_TEST_DRIVE.value, 0.9
            elif "service" in msg_lower or "oil" in msg_lower or "brake" in msg_lower or "tire" in msg_lower:
                return IntentType.BOOK_SERVICE.value, 0.9
            else:
                # Generic booking intent
                return IntentType.BOOK_SERVICE.value, 0.75

        # Reschedule keywords
        reschedule_keywords = ["reschedule", "change my appointment", "move my appointment", "different time", "different date"]
        if any(kw in msg_lower for kw in reschedule_keywords):
            return IntentType.RESCHEDULE.value, 0.9

        # Cancel keywords
        cancel_keywords = ["cancel", "cancellation", "don't need", "won't be able"]
        if any(kw in msg_lower for kw in cancel_keywords):
            return IntentType.CANCEL.value, 0.9

        # FAQ keywords
        faq_keywords = ["hours", "open", "close", "location", "where", "address", "price", "cost",
                       "how much", "financing", "loan", "payment", "service", "services", "offer"]
        if any(kw in msg_lower for kw in faq_keywords):
            return IntentType.FAQ.value, 0.8

        # Context-based: if booking is in progress (any slot filled), maintain booking intent
        slots = state.booking_slots
        has_any_booking_slot = any([
            slots.appointment_type,
            slots.customer_name,
            slots.customer_phone,
            slots.customer_email,
            slots.service_type,
            slots.vehicle_interest,
            slots.preferred_date,
            slots.preferred_time
        ])

        if has_any_booking_slot:
            # Get the appointment type for more specific intent
            appt_type = slots.appointment_type
            if appt_type:
                appt_val = appt_type.value if hasattr(appt_type, 'value') else appt_type
                if appt_val == "test_drive":
                    return IntentType.BOOK_TEST_DRIVE.value, 0.7
                else:
                    return IntentType.BOOK_SERVICE.value, 0.7
            # Booking in progress but no type yet - still booking intent
            return IntentType.BOOK_SERVICE.value, 0.6

        # Default to general
        return IntentType.GENERAL.value, 0.5

    async def _handle_escalation(
        self,
        user_message: str,
        state: ConversationState
    ) -> Tuple[str, BackgroundTask]:
        """Handle escalation request with background task."""

        response = "Absolutely, let me check if one of our team members is available right now. This might take just a moment. While I'm checking, is there anything else I can help you with?"

        # Create background task
        task_id = f"esc_{state.session_id}_{int(time.time())}"
        task = BackgroundTask(
            task_id=task_id,
            task_type=TaskType.HUMAN_ESCALATION,
            status=TaskStatus.PENDING
        )

        # Spawn background check
        if self.background_worker:
            asyncio.create_task(
                self.background_worker.execute_human_check(
                    task_id=task_id,
                    session_id=state.session_id,
                    customer_name=state.customer.name,
                    customer_phone=state.customer.phone,
                    reason=user_message
                )
            )

        return response, task

    async def _execute_tool(self, tool_name: str, tool_args: dict, state: ConversationState) -> str:
        """Execute a tool by name and return the result."""
        logger.info(f"[UNIFIED] Executing tool: {tool_name} with args: {tool_args}")

        tool_map = {tool.name: tool for tool in self.tools}

        if tool_name not in tool_map:
            return f"Unknown tool: {tool_name}"

        tool = tool_map[tool_name]

        try:
            # Add session_id if the tool needs it
            if hasattr(tool, 'args_schema') and 'session_id' in tool.args_schema.model_fields:
                tool_args['session_id'] = state.session_id

            result = await tool.ainvoke(tool_args)
            logger.info(f"[UNIFIED] Tool result: {str(result)[:200]}")

            # Handle booking confirmation data
            result_str = str(result)
            if "BOOKING_CONFIRMED" in result_str and "__CONFIRMATION_DATA__:" in result_str:
                try:
                    marker = "__CONFIRMATION_DATA__:"
                    json_start = result_str.index(marker) + len(marker)
                    json_str = result_str[json_start:].strip()
                    confirmation_data = json.loads(json_str)

                    from app.tools.slot_tools import _pending_slot_updates
                    if state.session_id not in _pending_slot_updates:
                        _pending_slot_updates[state.session_id] = {}
                    _pending_slot_updates[state.session_id]["_confirmed_appointment"] = confirmation_data

                    result_str = result_str[:result_str.index(marker)].strip()
                except Exception as parse_err:
                    logger.warning(f"[UNIFIED] Failed to parse confirmation: {parse_err}")

            return result_str

        except Exception as e:
            logger.error(f"[UNIFIED] Tool error: {e}")
            return f"Tool error: {str(e)}"

    def _apply_slot_updates(self, state: ConversationState) -> Tuple[BookingSlots, dict]:
        """Apply pending slot updates from tool calls."""
        slots = state.booking_slots.model_copy()

        updates = get_pending_updates(state.session_id)

        if not updates:
            return slots, {}

        logger.info(f"[UNIFIED] Applying slot updates: {updates}")

        if "appointment_type" in updates:
            appt_type = updates["appointment_type"]
            if appt_type == "service":
                slots.appointment_type = AppointmentType.SERVICE
            elif appt_type == "test_drive":
                slots.appointment_type = AppointmentType.TEST_DRIVE

        if "service_type" in updates:
            slots.service_type = updates["service_type"]

        if "vehicle_interest" in updates:
            slots.vehicle_interest = updates["vehicle_interest"]

        if "preferred_date" in updates:
            slots.preferred_date = updates["preferred_date"]

        if "preferred_time" in updates:
            slots.preferred_time = updates["preferred_time"]

        if "customer_name" in updates:
            slots.customer_name = updates["customer_name"]

        if "customer_phone" in updates:
            slots.customer_phone = updates["customer_phone"]

        if "customer_email" in updates:
            slots.customer_email = updates["customer_email"]

        return slots, updates
