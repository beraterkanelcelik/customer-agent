"""
Conversation Graph - LLM-driven agent with no hardcoded logic.

The LLM decides everything through tools:
- Escalation via request_human_agent tool
- Call ending via end_call tool
- All booking decisions via booking tools

Flow:
  preprocess -> agent -> (conditional) -> tools -> agent (loop)
                      -> postprocess -> END
"""
from typing import Dict, Any, Literal, List
from datetime import date, timedelta
import logging

from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from app.schemas.state import ConversationState
from app.schemas.enums import AgentType, HumanAgentStatus
from app.config import get_settings

# Import all tools from the unified module
from app.tools import ALL_TOOLS

settings = get_settings()
logger = logging.getLogger("app.agents.graph")


# ============================================
# System Prompt - No hardcoded logic, just capabilities
# ============================================

SYSTEM_PROMPT = """You are a friendly voice assistant for Springfield Auto dealership.

## CURRENT CONTEXT
{context}

## VOICE/STT AWARENESS - CRITICAL

### Phone Numbers (Automatic Normalization)
Input comes from speech-to-text which may be messy. The tool handles this automatically:
- "five five five one two three four five six seven" -> 5551234567
- "0 1 2 - 3 4 5 - 6 7 8 9" -> 0123456789
- Mixed: "my number is five 5 five, one two three, 4567" -> 5551234567

**SEQUENCE - ALWAYS FOLLOW**:
1. User provides phone -> IMMEDIATELY call update_booking_info(customer_phone=...) FIRST
2. THEN confirm verbally: "I have (555) 123-4567. Is that correct?"
If unclear or incomplete, ask them to repeat digit by digit.

### Emails (YOU must normalize)
Speech-to-text garbles emails - reconstruct intelligently:
- "at/add/et" -> "@"
- "dot" -> "."
- "gmail/g mail/gee mail" -> "gmail"
Examples: "john add gmail dot com" -> john@gmail.com

**SEQUENCE - ALWAYS FOLLOW**:
1. User provides email -> IMMEDIATELY call update_booking_info(customer_email=...) FIRST
2. THEN confirm verbally: "Your email is john@gmail.com, correct?"

## YOUR TOOLS

### Information
- search_faq: Answer questions about hours, location, financing, policies
- list_services: Show service pricing and duration
- list_inventory: Show vehicles available for test drives
- get_todays_date: Get current date for scheduling

### Customer Management
- get_customer: Look up existing customer by phone
- create_customer: Create new customer record
- set_customer_identified: Mark customer as verified

### Booking
- update_booking_info: Save booking details (name, phone, email, date, time, etc.)
  **IMPORTANT: Call this IMMEDIATELY after each piece of info is provided!**
  Don't wait to batch - call it right away so the dashboard updates in real-time.
- check_availability: Check if a time slot is open
- book_appointment: Book the appointment (requires customer_id!)
- reschedule_appointment: Change appointment date/time
- cancel_appointment: Cancel an appointment
- get_customer_appointments: List customer's upcoming bookings

### Escalation
- request_human_agent: Transfer to a human team member

### Call Control
- end_call: End the voice call gracefully with a farewell message

## BOOKING FLOW - FOLLOW THESE STEPS

**CRITICAL - SAVE BEFORE YOU SPEAK**: When the customer provides ANY booking info:
1. FIRST: Call update_booking_info(...) to save it
2. THEN: Respond verbally to confirm or ask the next question
This ensures the dashboard updates in real-time. NEVER skip the tool call!

1. **CUSTOMER INFO FIRST**: Before any booking details:
   - User gives NAME -> FIRST call update_booking_info(customer_name=...), THEN respond
   - User gives PHONE -> FIRST call update_booking_info(customer_phone=...), THEN confirm
   - User gives EMAIL -> FIRST call update_booking_info(customer_email=...), THEN confirm
   - After all 3 collected: Call create_customer (this gives you customer_id)

2. **APPOINTMENT TYPE**: Ask if test drive or service
   -> Call update_booking_info(appointment_type=...) IMMEDIATELY

3. **DETAILS**:
   - Service: Ask what service -> Call update_booking_info(service_type=...) IMMEDIATELY
   - Test Drive: Call list_inventory, ask what vehicle -> Call update_booking_info(vehicle_interest=...) IMMEDIATELY

4. **DATE/TIME**:
   - Ask for preferred DATE -> Call update_booking_info(preferred_date=..., preferred_time=...) IMMEDIATELY
   - Call check_availability
   - Confirm time

5. **CONFIRM**: Read back all details, wait for "yes"

6. **BOOK**: Call book_appointment with customer_id

## ESCALATION - MANDATORY TOOL USE

**CRITICAL**: When customer wants to speak with a human, you MUST call the request_human_agent tool!
Just saying "I'm calling someone" is NOT enough - you must actually call the tool.

Trigger phrases (call the tool when you hear these):
- "give me a human", "talk to a person", "real person"
- "speak with someone", "transfer me", "representative"
- "talk to a manager", "supervisor", "sales rep"

How to escalate:
1. FIRST: Call request_human_agent(session_id, reason="customer request for human assistance")
2. THEN: Say "Let me try to reach a team member for you" or "I'm checking if someone is available"
   **DO NOT say "connecting you now" - the call outcome is not yet known!**
3. Continue chatting while the call is being placed

The tool triggers a real phone call to a team member in the background.
When the escalation result comes back, you'll receive a special message like [ESCALATION_RETURNED:busy].
Generate an appropriate response based on the result - keep it natural and helpful.

When customer says goodbye or conversation is complete:
- Use the end_call tool with a warm farewell message
- Example: end_call(farewell_message="Thank you for calling Springfield Auto. Have a great day!")
- This ends the voice call gracefully

## VOICE INTERFACE RULES
- Keep responses SHORT (1-2 sentences) - this is voice
- Ask ONE question at a time
- Don't repeat information already collected
- Be warm and professional

## SPECIAL MESSAGES (System Events)
These are system events, not actual user speech. Generate an appropriate spoken response for each:

### Call Events
- [CALL_STARTED]: New call connected. Greet warmly and naturally.
- [PROCESSING_ERROR]: Technical error occurred. Ask customer to repeat politely.

### Escalation Events
- [ESCALATION_RETURNED:busy]: Human was busy. Let customer know you'll continue helping.
- [ESCALATION_RETURNED:no-answer]: Human didn't answer. Offer to continue helping.
- [ESCALATION_RETURNED:declined]: Human unavailable. Express understanding and continue helping.
- [ESCALATION_RETURNED:human_ended]: Human left the call. Ask if there's anything else you can help with.
- [ESCALATION_RETURNED:unavailable]: Generic unavailable. Continue helping the customer.

### Notification Events (from background tasks)
- [NOTIFICATION:human_available:*]: Human agent is available! Let customer know you're connecting them.
- [NOTIFICATION:callback_scheduled:*]: Callback was scheduled. Inform customer of the time.
- [NOTIFICATION:call_failed:*]: Call to human failed. Let customer know and offer alternatives.
- [NOTIFICATION:voicemail_detected]: Reached voicemail. Offer to schedule callback.
- [NOTIFICATION:connection_error]: Connection issue. Offer alternatives.
- [NOTIFICATION:escalation_result:*]: Generic escalation result. Respond appropriately.

### Human Handoff
- [HUMAN_JOINED:*]: A human agent has joined. Briefly introduce the customer context to help the human.

## IMPORTANT
- You make ALL decisions - no hardcoded logic exists
- If booking is in progress, stay focused on completing it
- Handle mixed messages like "thanks, my name is John" - extract the name"""


def get_date_context() -> str:
    """Get current date context for the agent."""
    today = date.today()
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    lines = [f"TODAY: {today.strftime('%Y-%m-%d')} ({days[today.weekday()]})"]

    upcoming = []
    for i in range(1, 8):
        d = today + timedelta(days=i)
        label = "Tomorrow" if i == 1 else days[d.weekday()]
        upcoming.append(f"{label}={d.strftime('%Y-%m-%d')}")

    lines.append(f"UPCOMING: {', '.join(upcoming)}")
    return "\n".join(lines)


def build_context(state: ConversationState) -> str:
    """Build context string showing current state for the LLM."""
    lines = []

    # Voice call indicator
    if state.is_voice_call:
        lines.append("INTERFACE: Voice call - Keep responses SHORT (1-2 sentences)")
        lines.append("")

    # Date context
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

        missing = slots.get_missing_slots(is_new_customer=not state.customer.is_identified)
        if missing:
            lines.append(f"  STILL NEEDED: {', '.join(missing)}")
        else:
            lines.append("  ALL INFO COLLECTED - Ready to book!")
    else:
        lines.append("")
        lines.append("BOOKING: No booking in progress")

    # Escalation status - show both in-progress and failed/completed states
    if state.escalation_in_progress:
        # Handle both enum and string values (after Redis deserialization)
        status = state.human_agent_status.value if hasattr(state.human_agent_status, 'value') else (state.human_agent_status or "checking")
        status_messages = {
            "checking": "Checking availability...",
            "calling": "Calling team member...",
            "ringing": "Phone is ringing...",
            "waiting": "Waiting for team member to accept...",
            "connected": "Team member connected!",
        }
        lines.append("")
        lines.append(f"ESCALATION: In progress - {status_messages.get(status, status)}")
    elif state.human_agent_status:
        # Show completed/failed escalation status so AI knows what happened
        # Handle both enum and string values (after Redis deserialization)
        status = state.human_agent_status.value if hasattr(state.human_agent_status, 'value') else state.human_agent_status
        if status == "unavailable":
            lines.append("")
            lines.append("ESCALATION: FAILED - Team member did not answer. Inform the customer.")
        elif status == "connected":
            lines.append("")
            lines.append("ESCALATION: Team member was connected and has now left the call.")

    return "\n".join(lines)


# ============================================
# LLM Setup
# ============================================

llm = ChatOpenAI(
    model=settings.openai_model,
    temperature=0.3,
    api_key=settings.openai_api_key
)
llm_with_tools = llm.bind_tools(ALL_TOOLS)


# ============================================
# Node Functions
# ============================================

async def preprocess_node(state: ConversationState) -> Dict[str, Any]:
    """
    Preprocess: Handle notifications from background tasks.

    Checks for any pending notifications (e.g., escalation results)
    and injects special messages for the agent to handle (no hardcoded spoken text).
    """
    updates = {}

    notifications = state.get_undelivered_notifications()
    if not notifications:
        return updates

    logger.info(f"[PREPROCESS] Found {len(notifications)} undelivered notifications")

    # Sort by priority
    priority_order = {"interrupt": 3, "high": 2, "low": 1}

    def get_priority(n):
        priority = n.priority.value if hasattr(n.priority, 'value') else n.priority
        return priority_order.get(priority, 0)

    notifications.sort(key=get_priority, reverse=True)
    top_notification = notifications[0]

    # Mark as delivered
    for n in state.notifications_queue:
        if n.notification_id == top_notification.notification_id:
            n.delivered = True

    updates["notifications_queue"] = state.notifications_queue

    # Update escalation status based on task result
    for task in state.pending_tasks:
        if task.task_id == top_notification.task_id:
            task_status = task.status.value if hasattr(task.status, 'value') else task.status
            if task_status == "completed":
                updates["waiting_for_background"] = False
                if task.human_available:
                    updates["human_agent_status"] = HumanAgentStatus.CONNECTED
                else:
                    updates["human_agent_status"] = HumanAgentStatus.UNAVAILABLE
                    updates["escalation_in_progress"] = False

    # Generate a special message marker for the agent to handle (no hardcoded text)
    # The agent will generate an appropriate response based on the notification data
    if top_notification.data:
        data = top_notification.data
        if data.get("human_available"):
            updates["prepend_message"] = f"[NOTIFICATION:human_available:{data.get('human_agent_name', 'team member')}]"
        elif data.get("type") == "call_failed":
            updates["prepend_message"] = f"[NOTIFICATION:call_failed:{data.get('status', 'unknown')}]"
        elif data.get("type") == "voicemail_detected":
            updates["prepend_message"] = "[NOTIFICATION:voicemail_detected]"
        elif data.get("type") == "connection_error":
            updates["prepend_message"] = "[NOTIFICATION:connection_error]"
        elif data.get("callback_scheduled"):
            updates["prepend_message"] = f"[NOTIFICATION:callback_scheduled:{data.get('callback_scheduled')}]"
        else:
            # Generic notification with reason
            reason = data.get("reason", "unavailable")
            updates["prepend_message"] = f"[NOTIFICATION:escalation_result:{reason}]"
        logger.info(f"[PREPROCESS] Generated notification marker: {updates.get('prepend_message')}")
    elif top_notification.message:
        # Legacy: if message is provided, use it (backwards compatibility)
        updates["prepend_message"] = top_notification.message
        logger.info(f"[PREPROCESS] Using legacy message: {top_notification.message[:50]}...")

    return updates


async def agent_node(state: ConversationState) -> Dict[str, Any]:
    """
    Agent node: Invoke the LLM with tools.

    The LLM makes ALL decisions - no hardcoded logic here.
    """
    logger.info(f"[AGENT] Processing with {len(state.messages)} messages")

    # Build context and system prompt
    context = build_context(state)
    system_prompt = SYSTEM_PROMPT.format(context=context)

    # Build messages
    messages = [SystemMessage(content=system_prompt)]

    # Add conversation history (limit to last 20 messages)
    history = state.messages[-20:] if len(state.messages) > 20 else state.messages
    for msg in history:
        if isinstance(msg, HumanMessage):
            messages.append(HumanMessage(content=msg.content))
        elif isinstance(msg, AIMessage):
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                messages.append(msg)
            elif msg.content:
                messages.append(AIMessage(content=msg.content))
        elif isinstance(msg, ToolMessage):
            messages.append(msg)

    logger.info(f"[AGENT] Sending {len(messages)} messages to LLM")

    # Invoke LLM
    response = await llm_with_tools.ainvoke(messages)

    if hasattr(response, 'tool_calls') and response.tool_calls:
        logger.info(f"[AGENT] Tool calls: {[tc['name'] for tc in response.tool_calls]}")
    else:
        content = response.content[:100] if response.content else 'empty'
        logger.info(f"[AGENT] Response: '{content}...'")

    return {"messages": [response]}


async def tool_node(state: ConversationState) -> Dict[str, Any]:
    """
    Tool node: Execute tool calls from the LLM.

    Injects session_id where needed and executes tools.
    """
    messages = state.messages
    if not messages:
        return {"messages": []}

    last_message = messages[-1]
    if not isinstance(last_message, AIMessage):
        return {"messages": []}

    if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
        return {"messages": []}

    tool_map = {tool.name: tool for tool in ALL_TOOLS}
    results = []

    for tool_call in last_message.tool_calls:
        tool_name = tool_call['name']
        tool_args = tool_call['args'].copy()
        tool_id = tool_call['id']

        if tool_name not in tool_map:
            results.append(ToolMessage(
                content=f"Unknown tool: {tool_name}",
                tool_call_id=tool_id
            ))
            continue

        tool = tool_map[tool_name]

        try:
            # Inject session_id if tool needs it
            if hasattr(tool, 'args_schema') and 'session_id' in tool.args_schema.model_fields:
                tool_args['session_id'] = state.session_id

            result = await tool.ainvoke(tool_args)
            logger.info(f"[TOOLS] {tool_name} result: {str(result)[:200]}")

            results.append(ToolMessage(
                content=str(result),
                tool_call_id=tool_id
            ))

        except Exception as e:
            logger.error(f"[TOOLS] Error in {tool_name}: {e}")
            results.append(ToolMessage(
                content=f"Tool error: {str(e)}",
                tool_call_id=tool_id
            ))

    return {"messages": results}


def should_continue(state: ConversationState) -> Literal["tools", "postprocess"]:
    """
    Decide whether to execute tools or finish.
    """
    messages = state.messages
    if not messages:
        return "postprocess"

    last_message = messages[-1]

    if isinstance(last_message, AIMessage):
        if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
            logger.info("[ROUTING] Has tool calls -> tools")
            return "tools"

    logger.info("[ROUTING] No tool calls -> postprocess")
    return "postprocess"


async def postprocess_node(state: ConversationState) -> Dict[str, Any]:
    """
    Postprocess: Apply state updates from tool results.

    Parses structured tool responses and updates state accordingly.
    """
    logger.info("[POSTPROCESS] Processing final response")

    updates = {
        "current_agent": AgentType.RESPONSE,
        "turn_count": state.turn_count + 1,
    }

    # Get the last AI message
    response_content = ""
    for msg in reversed(state.messages):
        if isinstance(msg, AIMessage) and msg.content:
            response_content = msg.content
            break

    # If no response content, don't add a fallback - let the agent handle it naturally
    # by returning an empty response (the voice system will handle silence gracefully)

    # Prepend notification if present
    if state.prepend_message:
        response_content = f"{state.prepend_message} {response_content}"
        updates["prepend_message"] = None
        updates["messages"] = [AIMessage(content=response_content)]

    # Parse tool results for state updates
    updates.update(await _parse_tool_results(state))

    logger.info(f"[POSTPROCESS] Response: '{response_content[:80]}...'")
    return updates


async def _parse_tool_results(state: ConversationState) -> Dict[str, Any]:
    """
    Parse tool results and extract state updates.

    Handles structured responses like:
    - BOOKING_UPDATE: slot updates
    - ESCALATION_STARTED: escalation state
    - CALL_ENDING: call termination
    - BOOKING_CONFIRMED: appointment confirmation
    """
    updates = {}

    # Get slot updates from the global store (legacy, to be migrated)
    from app.tools.slot_tools import get_pending_updates
    from app.schemas.state import BookingSlots, ConfirmedAppointment
    from app.schemas.customer import CustomerContext
    from app.schemas.enums import AppointmentType
    from app.schemas.task import BackgroundTask
    from app.schemas.enums import TaskType, TaskStatus
    import time

    raw_updates = get_pending_updates(state.session_id)

    if raw_updates:
        logger.info(f"[POSTPROCESS] Applying slot updates: {raw_updates}")
        logger.info(f"[POSTPROCESS] _customer_identified={raw_updates.get('_customer_identified')}, _customer_id={raw_updates.get('_customer_id')}, _customer_name={raw_updates.get('_customer_name')}")
        slots = state.booking_slots.model_copy()

        if "appointment_type" in raw_updates:
            appt_type = raw_updates["appointment_type"]
            if appt_type == "service":
                slots.appointment_type = AppointmentType.SERVICE
            elif appt_type == "test_drive":
                slots.appointment_type = AppointmentType.TEST_DRIVE

        for field in ["service_type", "vehicle_interest", "preferred_date",
                      "preferred_time", "customer_name", "customer_phone", "customer_email"]:
            if field in raw_updates:
                setattr(slots, field, raw_updates[field])

        updates["booking_slots"] = slots

        # Customer identification
        if raw_updates.get("_customer_identified"):
            customer_ctx = CustomerContext(
                customer_id=raw_updates.get("_customer_id"),
                name=raw_updates.get("_customer_name"),
                phone=raw_updates.get("_customer_phone") or slots.customer_phone,
                email=raw_updates.get("_customer_email") or slots.customer_email,
                is_identified=True
            )
            updates["customer"] = customer_ctx
            logger.info(f"[POSTPROCESS] Customer identified: id={customer_ctx.customer_id}, name={customer_ctx.name}, is_identified={customer_ctx.is_identified}")

        # Confirmed appointment
        if raw_updates.get("_confirmed_appointment"):
            conf_data = raw_updates["_confirmed_appointment"]
            updates["confirmed_appointment"] = ConfirmedAppointment(
                appointment_id=conf_data.get("appointment_id"),
                appointment_type=conf_data.get("appointment_type"),
                scheduled_date=conf_data.get("scheduled_date"),
                scheduled_time=conf_data.get("scheduled_time"),
                customer_name=conf_data.get("customer_name"),
                service_type=conf_data.get("service_type"),
                vehicle=conf_data.get("vehicle"),
                confirmation_email=conf_data.get("customer_email")
            )
            logger.info(f"[POSTPROCESS] Booking confirmed: #{conf_data.get('appointment_id')}")

    # Also scan tool messages for structured responses
    for msg in state.messages:
        if isinstance(msg, ToolMessage):
            content = msg.content

            # Handle escalation started
            if content.startswith("ESCALATION_STARTED:"):
                # Parse task_id from response
                try:
                    parts = content.split("|", 1)
                    if "task_id=" in parts[0]:
                        task_id = parts[0].split("task_id=")[1].strip()
                        task = BackgroundTask(
                            task_id=task_id,
                            task_type=TaskType.HUMAN_ESCALATION,
                            status=TaskStatus.PENDING
                        )
                        updates["escalation_in_progress"] = True
                        updates["pending_tasks"] = state.pending_tasks + [task]
                        updates["waiting_for_background"] = True
                        logger.info(f"[POSTPROCESS] Escalation started: {task_id}")
                except Exception as e:
                    logger.warning(f"[POSTPROCESS] Failed to parse escalation: {e}")

            # Handle booking confirmation (parse embedded JSON if present)
            elif "BOOKING_CONFIRMED" in content and "__CONFIRMATION_DATA__:" in content:
                try:
                    import json
                    marker = "__CONFIRMATION_DATA__:"
                    json_start = content.index(marker) + len(marker)
                    json_str = content[json_start:].strip()
                    conf_data = json.loads(json_str)

                    updates["confirmed_appointment"] = ConfirmedAppointment(
                        appointment_id=conf_data.get("appointment_id"),
                        appointment_type=conf_data.get("appointment_type"),
                        scheduled_date=conf_data.get("scheduled_date"),
                        scheduled_time=conf_data.get("scheduled_time"),
                        customer_name=conf_data.get("customer_name"),
                        service_type=conf_data.get("service_type"),
                        vehicle=conf_data.get("vehicle"),
                        confirmation_email=conf_data.get("customer_email")
                    )
                    logger.info(f"[POSTPROCESS] Booking confirmed from tool: #{conf_data.get('appointment_id')}")
                except Exception as e:
                    logger.warning(f"[POSTPROCESS] Failed to parse confirmation: {e}")

    return updates


# ============================================
# Build Graph
# ============================================

def create_graph():
    """
    Create the conversation graph.

    Flow:
    preprocess -> agent -> (conditional)
                        |-> tools -> agent (loop back)
                        |-> postprocess -> END
    """
    workflow = StateGraph(ConversationState)

    # Add nodes
    workflow.add_node("preprocess", preprocess_node)
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)
    workflow.add_node("postprocess", postprocess_node)

    # Entry point
    workflow.set_entry_point("preprocess")

    # Edges
    workflow.add_edge("preprocess", "agent")

    # Conditional routing after agent
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            "postprocess": "postprocess"
        }
    )

    # After tools, back to agent
    workflow.add_edge("tools", "agent")

    # After postprocess, end
    workflow.add_edge("postprocess", END)

    return workflow.compile()


# Global graph instance
conversation_graph = create_graph()


# ============================================
# Public API
# ============================================

async def process_message(
    session_id: str,
    user_message: str,
    current_state: ConversationState = None
) -> ConversationState:
    """
    Process a user message through the conversation graph.
    """
    if current_state is None:
        current_state = ConversationState(session_id=session_id)

    logger.info(f"[GRAPH] Processing message with {len(current_state.messages)} existing messages")

    # Add the new user message
    all_messages = current_state.messages + [HumanMessage(content=user_message)]

    # Build input state
    input_state = {
        "session_id": current_state.session_id,
        "messages": all_messages,
        "current_agent": current_state.current_agent,
        "detected_intent": current_state.detected_intent,
        "confidence": current_state.confidence,
        "customer": current_state.customer,
        "booking_slots": current_state.booking_slots,
        "pending_confirmation": current_state.pending_confirmation,
        "confirmed_appointment": current_state.confirmed_appointment,
        "pending_tasks": current_state.pending_tasks,
        "notifications_queue": current_state.notifications_queue,
        "escalation_in_progress": current_state.escalation_in_progress,
        "human_agent_status": current_state.human_agent_status,
        "should_respond": current_state.should_respond,
        "needs_slot_filling": current_state.needs_slot_filling,
        "waiting_for_background": current_state.waiting_for_background,
        "is_voice_call": current_state.is_voice_call,
        "prepend_message": current_state.prepend_message,
        "turn_count": current_state.turn_count,
        "created_at": current_state.created_at,
        "last_updated": current_state.last_updated,
    }

    try:
        result = await conversation_graph.ainvoke(input_state)
        # Log customer state after processing
        customer_result = result.get("customer", {})
        if hasattr(customer_result, 'customer_id'):
            logger.info(f"[GRAPH] Result customer (obj): id={customer_result.customer_id}, name={customer_result.name}, is_identified={customer_result.is_identified}")
        elif isinstance(customer_result, dict):
            logger.info(f"[GRAPH] Result customer (dict): id={customer_result.get('customer_id')}, name={customer_result.get('name')}, is_identified={customer_result.get('is_identified')}")
        return ConversationState(**result)
    except Exception as e:
        logger.error(f"Graph error: {e}", exc_info=True)
        # Return state without adding a hardcoded error message
        # The voice system should handle this case by sending [PROCESSING_ERROR]
        return ConversationState(**input_state)
