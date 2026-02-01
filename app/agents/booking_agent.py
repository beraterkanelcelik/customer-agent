"""
Booking Agent - Clean LLM-driven appointment booking.

This agent uses direct LLM calls with tool binding (no AgentExecutor).
The LLM receives full context and decides everything - no fallback logic.

Based on best practices from:
- LangGraph memory management (message trimming)
- LiveKit multi-agent patterns (context injection, clean prompts)
"""
import json
import logging
from typing import Tuple, Dict, Any, List, Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate

from app.config import get_settings
from app.schemas.state import ConversationState, BookingSlots
from app.schemas.enums import AppointmentType

# Import all tools
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

settings = get_settings()
logger = logging.getLogger("app.agents.booking")


BOOKING_SYSTEM_PROMPT = """You are a friendly voice booking assistant for Springfield Auto dealership.

## CURRENT BOOKING CONTEXT
{booking_context}

## CUSTOMER STATUS
{customer_status}

## CONVERSATION SUMMARY
{conversation_summary}

## YOUR TASK
Help the customer complete their booking. You have access to tools to save information and make bookings.

## IMPORTANT RULES
1. **Use the context above** - Don't ask for information that's already collected
2. **One question at a time** - This is voice, keep responses to 1-2 sentences
3. **Save information immediately** - When user provides ANY info, call update_booking_info
4. **Follow the natural flow**:
   - For test drives: vehicle → date → time → customer info → confirm
   - For service: service type → date → time → customer info → confirm

## VOICE INPUT PATTERNS
Users speak, so expect:
- "one five five" = "155" (phone numbers)
- "john at gmail dot com" = "john@gmail.com"
- "tomorrow at 2" = date and time

## WHAT TO DO NOW
Based on the booking context above, determine what information is still needed and ask for the NEXT piece only.
If all info is collected, confirm and book the appointment.

Remember: You're having a natural voice conversation. Be helpful and concise."""


class BookingAgent:
    """
    Handles appointment booking using direct LLM calls with tool binding.

    Key design decisions:
    - No AgentExecutor (too complex, fails with generic errors)
    - Direct tool binding to ChatOpenAI
    - Full context injection via system prompt
    - Message trimming to prevent context overflow
    - NO fallback logic - LLM handles everything
    """

    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.openai_model,
            temperature=0.3,
            api_key=settings.openai_api_key
        )

        # All available tools
        self.tools = [
            update_booking_info,
            set_customer_identified,
            get_todays_date,
            get_customer,
            create_customer,
            check_availability,
            book_appointment,
            reschedule_appointment,
            cancel_appointment,
            get_customer_appointments,
            list_inventory,
        ]

        # Bind tools to LLM
        self.llm_with_tools = self.llm.bind_tools(self.tools)

    def _build_booking_context(self, slots: BookingSlots, state: ConversationState) -> str:
        """Build a clear, structured summary of current booking state."""
        lines = []

        # Appointment type
        if slots.appointment_type:
            appt_type = slots.appointment_type.value if hasattr(slots.appointment_type, 'value') else slots.appointment_type
            lines.append(f"Appointment Type: {appt_type.upper()}")
        else:
            lines.append("Appointment Type: NOT SET (need to determine)")

        # Type-specific info
        if slots.vehicle_interest:
            lines.append(f"Vehicle: {slots.vehicle_interest}")
        if slots.service_type:
            lines.append(f"Service: {slots.service_type}")

        # Scheduling
        if slots.preferred_date:
            lines.append(f"Date: {slots.preferred_date}")
        else:
            lines.append("Date: NOT SET")

        if slots.preferred_time:
            lines.append(f"Time: {slots.preferred_time}")
        else:
            lines.append("Time: NOT SET")

        # Customer info
        lines.append("")
        lines.append("Customer Information:")
        if slots.customer_name:
            lines.append(f"  Name: {slots.customer_name}")
        else:
            lines.append("  Name: NOT SET")
        if slots.customer_phone:
            lines.append(f"  Phone: {slots.customer_phone}")
        else:
            lines.append("  Phone: NOT SET")
        if slots.customer_email:
            lines.append(f"  Email: {slots.customer_email}")
        else:
            lines.append("  Email: NOT SET")

        # What's missing
        missing = slots.get_missing_slots(is_new_customer=not state.customer.is_identified)
        if missing:
            lines.append("")
            lines.append(f"STILL NEEDED: {', '.join(missing)}")
        else:
            lines.append("")
            lines.append("ALL INFORMATION COLLECTED - Ready to book!")

        return "\n".join(lines)

    def _build_customer_status(self, state: ConversationState) -> str:
        """Build customer identification status."""
        if state.customer.is_identified:
            return f"RETURNING CUSTOMER: {state.customer.name} (ID: {state.customer.customer_id})"
        else:
            return "NEW CUSTOMER - Need to collect name, phone, and email"

    def _build_conversation_summary(self, chat_history: List[BaseMessage]) -> str:
        """Build a concise summary of the conversation so far."""
        if not chat_history:
            return "This is the start of the conversation."

        # Take last 6 meaningful exchanges
        summary_lines = []
        count = 0
        for msg in reversed(chat_history):
            if count >= 6:
                break
            if isinstance(msg, HumanMessage):
                summary_lines.insert(0, f"Customer: {msg.content}")
                count += 1
            elif isinstance(msg, AIMessage) and msg.content:
                # Skip empty or error-like responses
                content = msg.content
                if self._is_useful_message(content):
                    summary_lines.insert(0, f"Agent: {content}")
                    count += 1

        if summary_lines:
            return "\n".join(summary_lines)
        return "Conversation just started."

    def _is_useful_message(self, content: str) -> bool:
        """Check if a message is useful (not an error/confusion message)."""
        if not content:
            return False

        unhelpful_phrases = [
            "issue with your message", "please repeat", "didn't catch",
            "error in your message", "please clarify", "try again",
            "couldn't understand", "not sure what"
        ]
        content_lower = content.lower()
        return not any(phrase in content_lower for phrase in unhelpful_phrases)

    def _trim_messages(self, messages: List[BaseMessage], max_messages: int = 10) -> List[BaseMessage]:
        """
        Trim message history to prevent context overflow.

        Based on LangGraph best practice: keep recent messages, filter unhelpful ones.
        """
        if len(messages) <= max_messages:
            filtered = [m for m in messages if self._should_keep_message(m)]
            return filtered[-max_messages:]

        # Keep last N messages, filtering unhelpful ones
        filtered = []
        for msg in reversed(messages):
            if len(filtered) >= max_messages:
                break
            if self._should_keep_message(msg):
                filtered.insert(0, msg)

        return filtered

    def _should_keep_message(self, msg: BaseMessage) -> bool:
        """Determine if a message should be kept in history."""
        # Always keep human messages
        if isinstance(msg, HumanMessage):
            return True

        # For AI messages, filter out unhelpful ones
        if isinstance(msg, AIMessage):
            return self._is_useful_message(msg.content)

        # Keep tool messages
        if isinstance(msg, ToolMessage):
            return True

        return True

    async def handle(
        self,
        user_message: str,
        state: ConversationState,
        chat_history: List[BaseMessage] = None
    ) -> Tuple[str, BookingSlots, dict]:
        """
        Process booking request using direct LLM with tools.

        The LLM receives:
        1. Full booking context (what's collected, what's missing)
        2. Customer status
        3. Trimmed conversation summary
        4. The current user message

        The LLM decides what to say and what tools to call.
        NO FALLBACK LOGIC - the LLM handles everything.
        """
        logger.info(f"[BOOKING_AGENT] Processing: '{user_message}'")
        logger.info(f"[BOOKING_AGENT] Current slots: {self._build_booking_context(state.booking_slots, state)}")

        # Build the full context prompt
        booking_context = self._build_booking_context(state.booking_slots, state)
        customer_status = self._build_customer_status(state)
        conversation_summary = self._build_conversation_summary(chat_history or [])

        system_prompt = BOOKING_SYSTEM_PROMPT.format(
            booking_context=booking_context,
            customer_status=customer_status,
            conversation_summary=conversation_summary
        )

        # Build messages for LLM
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message)
        ]

        logger.info(f"[BOOKING_AGENT] System prompt includes booking context with missing slots")

        # Call LLM with tools
        response = None
        tool_calls_made = []
        max_iterations = 5  # Prevent infinite loops

        for iteration in range(max_iterations):
            try:
                ai_response = await self.llm_with_tools.ainvoke(messages)
                logger.info(f"[BOOKING_AGENT] LLM response (iter {iteration}): {type(ai_response)}")

                # Check if there are tool calls
                if hasattr(ai_response, 'tool_calls') and ai_response.tool_calls:
                    logger.info(f"[BOOKING_AGENT] Tool calls: {[tc['name'] for tc in ai_response.tool_calls]}")

                    # Add AI message with tool calls
                    messages.append(ai_response)

                    # Execute each tool call
                    for tool_call in ai_response.tool_calls:
                        tool_name = tool_call['name']
                        tool_args = tool_call['args']
                        tool_id = tool_call['id']

                        # Find and execute the tool
                        tool_result = await self._execute_tool(tool_name, tool_args, state)
                        tool_calls_made.append((tool_name, tool_args, tool_result))

                        # Add tool result message
                        messages.append(ToolMessage(
                            content=str(tool_result),
                            tool_call_id=tool_id
                        ))

                    # Continue loop to get final response
                    continue

                # No tool calls - this is the final response
                response = ai_response.content
                logger.info(f"[BOOKING_AGENT] Final response: '{response[:100]}...'")
                break

            except Exception as e:
                logger.error(f"[BOOKING_AGENT] LLM error: {e}", exc_info=True)
                response = "I'd be happy to help you with your booking. Could you tell me what type of appointment you'd like - a test drive or a service appointment?"
                break

        # Get any slot updates from tool calls
        updated_slots, raw_updates = self._apply_slot_updates(state)

        return response or "How can I help you with your booking today?", updated_slots, raw_updates

    async def _execute_tool(self, tool_name: str, tool_args: dict, state: ConversationState) -> str:
        """Execute a tool by name and return the result."""
        logger.info(f"[BOOKING_AGENT] Executing tool: {tool_name} with args: {tool_args}")

        # Find the tool
        tool_map = {tool.name: tool for tool in self.tools}

        if tool_name not in tool_map:
            return f"Unknown tool: {tool_name}"

        tool = tool_map[tool_name]

        try:
            # Add session_id to args if the tool needs it
            if 'session_id' in tool.args_schema.model_fields:
                tool_args['session_id'] = state.session_id

            # Execute the tool
            result = await tool.ainvoke(tool_args)
            logger.info(f"[BOOKING_AGENT] Tool result: {result}")
            return str(result)
        except Exception as e:
            logger.error(f"[BOOKING_AGENT] Tool error: {e}")
            return f"Tool error: {str(e)}"

    def _apply_slot_updates(self, state: ConversationState) -> Tuple[BookingSlots, dict]:
        """
        Apply pending slot updates from tool calls.
        """
        slots = state.booking_slots.model_copy()

        # Get pending updates from tool calls
        updates = get_pending_updates(state.session_id)

        if not updates:
            return slots, {}

        logger.info(f"[BOOKING_AGENT] Applying slot updates: {updates}")

        # Apply updates to slots
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
