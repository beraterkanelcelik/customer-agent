"""
Conversation Graph - Proper LangGraph tool-calling pattern.

Flow:
  check_notifications -> call_model -> (conditional) -> tool_node -> call_model (loop)
                                    -> END (when no tool calls)

Uses the standard LangGraph pattern:
1. call_model node invokes LLM with tools bound
2. Conditional edge checks if response has tool_calls
3. If tool_calls: route to tool_node, then back to call_model
4. If no tool_calls: END
"""
from typing import Dict, Any, Literal
import logging

from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from app.schemas.state import ConversationState
from app.schemas.enums import AgentType, HumanAgentStatus
from app.config import get_settings

# Import tools
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

from .unified_agent import (
    UNIFIED_SYSTEM_PROMPT, build_context, UnifiedAgent
)

settings = get_settings()
logger = logging.getLogger("app.agents.graph")

# All tools
ALL_TOOLS = [
    search_faq,
    list_services,
    check_availability,
    book_appointment,
    reschedule_appointment,
    cancel_appointment,
    get_customer_appointments,
    list_inventory,
    get_customer,
    create_customer,
    update_booking_info,
    set_customer_identified,
    get_todays_date,
    end_call,
]

# Create LLM with tools bound
llm = ChatOpenAI(
    model=settings.openai_model,
    temperature=0.3,
    api_key=settings.openai_api_key
)
llm_with_tools = llm.bind_tools(ALL_TOOLS)

# Custom tool node that injects session_id
async def custom_tool_node(state: ConversationState) -> Dict[str, Any]:
    """
    Execute tools from the last AI message, injecting session_id where needed.
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
            # Inject session_id if the tool needs it
            if hasattr(tool, 'args_schema') and 'session_id' in tool.args_schema.model_fields:
                tool_args['session_id'] = state.session_id

            result = await tool.ainvoke(tool_args)
            logger.info(f"[TOOL_NODE] {tool_name} result: {str(result)[:200]}")

            # Handle booking confirmation data embedded in result
            result_str = str(result)
            if "BOOKING_CONFIRMED" in result_str and "__CONFIRMATION_DATA__:" in result_str:
                try:
                    import json
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
                    logger.warning(f"[TOOL_NODE] Failed to parse confirmation: {parse_err}")

            results.append(ToolMessage(
                content=result_str,
                tool_call_id=tool_id
            ))

        except Exception as e:
            logger.error(f"[TOOL_NODE] Tool error: {e}")
            results.append(ToolMessage(
                content=f"Tool error: {str(e)}",
                tool_call_id=tool_id
            ))

    return {"messages": results}

# Keep unified agent for escalation handling
unified_agent = UnifiedAgent()


# ============================================
# Node Functions
# ============================================

async def check_notifications_node(state: ConversationState) -> Dict[str, Any]:
    """Check for and process any pending notifications from background tasks."""
    updates = {}

    notifications = state.get_undelivered_notifications()

    if not notifications:
        return updates

    logger.info(f"[NOTIFICATIONS] Found {len(notifications)} undelivered notifications")

    priority_order = {"interrupt": 3, "high": 2, "low": 1}

    def get_priority(n):
        priority = n.priority.value if hasattr(n.priority, 'value') else n.priority
        return priority_order.get(priority, 0)

    notifications.sort(key=get_priority, reverse=True)
    top_notification = notifications[0]

    for n in state.notifications_queue:
        if n.notification_id == top_notification.notification_id:
            n.delivered = True

    updates["prepend_message"] = top_notification.message
    updates["notifications_queue"] = state.notifications_queue

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

    logger.info(f"[NOTIFICATIONS] Processed notification: {top_notification.message[:50]}...")

    return updates


async def call_model_node(state: ConversationState) -> Dict[str, Any]:
    """
    Call the LLM with tools bound.

    This node:
    1. Builds the system prompt with current context
    2. Invokes the LLM with all messages
    3. Returns the AI response (which may contain tool_calls)
    """
    logger.info(f"[CALL_MODEL] State has {len(state.messages)} messages")

    # Get the last user message for logging
    user_message = ""
    for msg in reversed(state.messages):
        if isinstance(msg, HumanMessage):
            user_message = msg.content
            break

    logger.info(f"[CALL_MODEL] Processing: '{user_message}'")

    # Build context and system prompt
    context = build_context(state)
    system_prompt = UNIFIED_SYSTEM_PROMPT.format(context=context)

    # Build messages list with system prompt at the start
    messages = [SystemMessage(content=system_prompt)]

    # Add conversation history (limit to last 20 messages to avoid context overflow)
    history = state.messages[-20:] if len(state.messages) > 20 else state.messages
    for msg in history:
        if isinstance(msg, HumanMessage):
            messages.append(HumanMessage(content=msg.content))
        elif isinstance(msg, AIMessage):
            # Include tool_calls if present (needed for tool response context)
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                messages.append(msg)
            elif msg.content:
                messages.append(AIMessage(content=msg.content))
        elif isinstance(msg, ToolMessage):
            # Include tool results so LLM can see what tools returned
            messages.append(msg)

    logger.info(f"[CALL_MODEL] Sending {len(messages)} messages to LLM")

    # Invoke LLM with tools
    response = await llm_with_tools.ainvoke(messages)

    # Log what happened
    if hasattr(response, 'tool_calls') and response.tool_calls:
        logger.info(f"[CALL_MODEL] Tool calls: {[tc['name'] for tc in response.tool_calls]}")
    else:
        logger.info(f"[CALL_MODEL] Final response: '{response.content[:100] if response.content else 'empty'}...'")

    # Return the response as a message to add to state
    return {"messages": [response]}


def should_continue(state: ConversationState) -> Literal["tool_node", "process_response"]:
    """
    Conditional edge: decide whether to call tools or finish.

    If the last message has tool_calls, route to tool_node.
    Otherwise, route to process_response (which handles final response).
    """
    messages = state.messages
    if not messages:
        return "process_response"

    last_message = messages[-1]

    # Check if this is an AI message with tool calls
    if isinstance(last_message, AIMessage):
        if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
            logger.info(f"[SHOULD_CONTINUE] Has tool calls, routing to tool_node")
            return "tool_node"

    logger.info(f"[SHOULD_CONTINUE] No tool calls, routing to process_response")
    return "process_response"


async def process_response_node(state: ConversationState) -> Dict[str, Any]:
    """
    Process the final response and apply any state updates from tools.

    This node:
    1. Gets the final AI response
    2. Applies slot updates from tool calls
    3. Handles customer identification
    4. Handles booking confirmations
    """
    logger.info(f"[PROCESS_RESPONSE] Processing final response")

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

    if not response_content:
        response_content = "I'm here to help. What can I do for you?"
        updates["messages"] = [AIMessage(content=response_content)]

    # Prepend notification message if present
    if state.prepend_message:
        response_content = f"{state.prepend_message} {response_content}"
        updates["prepend_message"] = None
        # Update the last message with prepended content
        updates["messages"] = [AIMessage(content=response_content)]

    logger.info(f"[PROCESS_RESPONSE] Response: '{response_content[:80]}...'")

    # Apply slot updates from tools
    from app.schemas.state import BookingSlots
    from app.schemas.enums import AppointmentType

    raw_updates = get_pending_updates(state.session_id)

    if raw_updates:
        logger.info(f"[PROCESS_RESPONSE] Applying slot updates: {raw_updates}")
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

        # Check for customer identification
        if raw_updates.get("_customer_identified"):
            from app.schemas.customer import CustomerContext
            updates["customer"] = CustomerContext(
                customer_id=raw_updates.get("_customer_id"),
                name=raw_updates.get("_customer_name"),
                phone=raw_updates.get("_customer_phone") or slots.customer_phone,
                email=raw_updates.get("_customer_email") or slots.customer_email,
                is_identified=True
            )

        # Check for confirmed appointment
        if raw_updates.get("_confirmed_appointment"):
            from app.schemas.state import ConfirmedAppointment
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
            logger.info(f"[PROCESS_RESPONSE] Booking confirmed: #{conf_data.get('appointment_id')}")

    return updates


# ============================================
# Build Graph
# ============================================

def create_graph():
    """
    Create the LangGraph conversation graph with proper tool-calling pattern.

    Flow:
    check_notifications -> call_model -> should_continue conditional edge
                                      |-> tool_node -> call_model (loop)
                                      |-> process_response -> END
    """

    workflow = StateGraph(ConversationState)

    # Add nodes
    workflow.add_node("check_notifications", check_notifications_node)
    workflow.add_node("call_model", call_model_node)
    workflow.add_node("tool_node", custom_tool_node)
    workflow.add_node("process_response", process_response_node)

    # Set entry point
    workflow.set_entry_point("check_notifications")

    # Edges
    workflow.add_edge("check_notifications", "call_model")

    # Conditional edge after call_model
    workflow.add_conditional_edges(
        "call_model",
        should_continue,
        {
            "tool_node": "tool_node",
            "process_response": "process_response"
        }
    )

    # After tools, go back to call_model to process results
    workflow.add_edge("tool_node", "call_model")

    # After processing response, end
    workflow.add_edge("process_response", END)

    # Compile
    graph = workflow.compile()

    return graph


# Create global graph instance
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

    logger.info(f"[GRAPH] process_message called with {len(current_state.messages)} existing messages")

    all_messages = current_state.messages + [HumanMessage(content=user_message)]
    logger.info(f"[GRAPH] Total messages for graph: {len(all_messages)}")

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
        "prepend_message": current_state.prepend_message,
        "turn_count": current_state.turn_count,
        "created_at": current_state.created_at,
        "last_updated": current_state.last_updated,
    }

    try:
        result = await conversation_graph.ainvoke(input_state)
        return ConversationState(**result)
    except Exception as e:
        logger.error(f"Graph invocation error: {e}", exc_info=True)
        error_msg = "I apologize, but I encountered an error processing your request. Please try again."
        return ConversationState(
            **{
                **input_state,
                "messages": input_state["messages"] + [AIMessage(content=error_msg)]
            }
        )


def set_escalation_worker(worker):
    """Set the background worker for escalation handling."""
    unified_agent.set_background_worker(worker)
