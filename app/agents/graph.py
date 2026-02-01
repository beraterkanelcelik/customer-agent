from typing import Literal, Dict, Any
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, AIMessage

from app.schemas.state import ConversationState
from app.schemas.enums import AgentType, IntentType, HumanAgentStatus, TaskStatus, TaskType, AppointmentType
from app.schemas.task import Notification, NotificationPriority

from .router_agent import RouterAgent
from .faq_agent import FAQAgent
from .booking_agent import BookingAgent
from .escalation_agent import EscalationAgent
from .response_generator import ResponseGenerator
from app.schemas.customer import CustomerContext
from app.tools.slot_tools import normalize_phone_number, normalize_email


# Initialize agents
router_agent = RouterAgent()
faq_agent = FAQAgent()
booking_agent = BookingAgent()
escalation_agent = EscalationAgent()
response_generator = ResponseGenerator()


def get_last_user_message(state: ConversationState) -> str:
    """Extract the last user message from state."""
    for msg in reversed(state.messages):
        if isinstance(msg, HumanMessage):
            return msg.content
    return ""


def get_chat_history(state: ConversationState, exclude_last: bool = True) -> list:
    """Extract chat history from state."""
    messages = state.messages[:-1] if exclude_last and state.messages else state.messages
    history = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            history.append(HumanMessage(content=msg.content))
        elif isinstance(msg, AIMessage):
            history.append(AIMessage(content=msg.content))
    return history


# ============================================
# Node Functions
# ============================================

async def check_notifications_node(state: ConversationState) -> Dict[str, Any]:
    """Check for and process any pending notifications from background tasks."""

    updates = {}

    # Get undelivered notifications sorted by priority
    notifications = state.get_undelivered_notifications()

    if not notifications:
        return updates

    # Process highest priority notification
    # Use string keys to handle both enum and string values
    priority_order = {
        "interrupt": 3,
        "high": 2,
        "low": 1
    }

    def get_priority(n):
        priority = n.priority.value if hasattr(n.priority, 'value') else n.priority
        return priority_order.get(priority, 0)

    notifications.sort(key=get_priority, reverse=True)
    top_notification = notifications[0]

    # Mark as delivered
    for n in state.notifications_queue:
        if n.notification_id == top_notification.notification_id:
            n.delivered = True

    # Set prepend message
    updates["prepend_message"] = top_notification.message
    updates["notifications_queue"] = state.notifications_queue

    # Update task status if this completes an escalation
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

    return updates


async def router_node(state: ConversationState) -> Dict[str, Any]:
    """Route user message to appropriate agent."""
    import logging
    logger = logging.getLogger("app.agents.graph")

    logger.info(f"[ROUTER] State has {len(state.messages)} messages")
    for i, msg in enumerate(state.messages):
        msg_type = type(msg).__name__
        content = msg.content[:50] if hasattr(msg, 'content') else str(msg)[:50]
        logger.info(f"[ROUTER]   msg[{i}] {msg_type}: {content}...")

    # Get the last user message
    user_message = ""
    for msg in reversed(state.messages):
        if isinstance(msg, HumanMessage):
            user_message = msg.content
            break

    if not user_message:
        return {"detected_intent": IntentType.GENERAL, "confidence": 0.0}

    # Get conversation history for context
    history = state.get_conversation_history(max_turns=5)
    logger.info(f"[ROUTER] History for LLM:\n{history}")

    # Classify intent
    result = await router_agent.classify(user_message, history)

    logger.info(f"Router classified: intent={result.intent}, entities={result.entities}")

    # Build response with intent
    response = {
        "detected_intent": result.intent,
        "confidence": result.confidence,
        "current_agent": AgentType.ROUTER
    }

    # IMPORTANT: Extract and save entities from router to booking_slots
    # This ensures information isn't lost before reaching the booking agent
    if result.entities:
        updated_slots = state.booking_slots.model_copy()
        entities = result.entities

        # Extract phone number - use normalization function to handle spoken numbers
        if entities.get("phone"):
            phone = normalize_phone_number(str(entities["phone"]))
            if len(phone) >= 7:  # Accept shorter phone numbers too
                updated_slots.customer_phone = phone

        # Extract name
        if entities.get("name"):
            updated_slots.customer_name = entities["name"]

        # Extract email - use normalization function
        if entities.get("email"):
            email = normalize_email(entities["email"])
            if "@" in email and "." in email:
                updated_slots.customer_email = email

        # Extract date
        if entities.get("date"):
            updated_slots.preferred_date = entities["date"]

        # Extract time
        if entities.get("time"):
            updated_slots.preferred_time = entities["time"]

        # Extract service type
        if entities.get("service_type"):
            updated_slots.service_type = entities["service_type"]

        # Extract vehicle info
        vehicle = entities.get("vehicle_make", "") + " " + entities.get("vehicle_model", "")
        vehicle = vehicle.strip()
        if vehicle:
            updated_slots.vehicle_interest = vehicle

        response["booking_slots"] = updated_slots
        logger.info(f"Saved entities to booking_slots: phone={updated_slots.customer_phone}, name={updated_slots.customer_name}, email={updated_slots.customer_email}")

    return response


async def faq_agent_node(state: ConversationState) -> Dict[str, Any]:
    """Handle FAQ queries."""

    user_message = ""
    for msg in reversed(state.messages):
        if isinstance(msg, HumanMessage):
            user_message = msg.content
            break

    # Convert messages to chat history format
    chat_history = []
    for msg in state.messages[:-1]:  # Exclude last message
        if isinstance(msg, HumanMessage):
            chat_history.append(HumanMessage(content=msg.content))
        elif isinstance(msg, AIMessage):
            chat_history.append(AIMessage(content=msg.content))

    response = await faq_agent.handle(user_message, chat_history)

    return {
        "current_agent": AgentType.FAQ,
        "messages": [AIMessage(content=response)]
    }


async def booking_agent_node(state: ConversationState) -> Dict[str, Any]:
    """Handle booking requests."""
    import logging
    logger = logging.getLogger("app.agents.graph")

    logger.info(f"[BOOKING] State has {len(state.messages)} messages")
    for i, msg in enumerate(state.messages):
        msg_type = type(msg).__name__
        content = getattr(msg, 'content', str(msg))[:50] if hasattr(msg, 'content') else str(msg)[:50]
        logger.info(f"[BOOKING]   msg[{i}]: {msg_type} = '{content}...'")

    user_message = ""
    for msg in reversed(state.messages):
        if isinstance(msg, HumanMessage):
            user_message = msg.content
            break

    if not user_message:
        logger.warning(f"[BOOKING] No HumanMessage found in state.messages!")
        # Fallback: look for dict-style messages
        for msg in reversed(state.messages):
            if isinstance(msg, dict) and msg.get('type') in ('human', 'HumanMessage'):
                user_message = msg.get('content', '')
                logger.info(f"[BOOKING] Found dict message: '{user_message}'")
                break

    logger.info(f"[BOOKING] Processing: '{user_message}'")

    # Pre-set appointment type based on detected intent (helps booking agent)
    intent = state.detected_intent
    intent_value = intent.value if hasattr(intent, 'value') else intent

    if intent_value == "book_test_drive" and state.booking_slots.appointment_type is None:
        state.booking_slots.appointment_type = AppointmentType.TEST_DRIVE
        logger.info(f"[BOOKING] Auto-set appointment_type to TEST_DRIVE based on intent")
    elif intent_value == "book_service" and state.booking_slots.appointment_type is None:
        state.booking_slots.appointment_type = AppointmentType.SERVICE
        logger.info(f"[BOOKING] Auto-set appointment_type to SERVICE based on intent")

    chat_history = []
    for msg in state.messages[:-1]:
        if isinstance(msg, HumanMessage):
            chat_history.append(HumanMessage(content=msg.content))
        elif isinstance(msg, AIMessage):
            chat_history.append(AIMessage(content=msg.content))

    # Call booking agent - it handles everything with full context
    response, updated_slots, raw_updates = await booking_agent.handle(
        user_message,
        state,
        chat_history
    )
    logger.info(f"[BOOKING] Agent response: '{response[:80]}...'")

    result = {
        "current_agent": AgentType.BOOKING,
        "booking_slots": updated_slots,
        "messages": [AIMessage(content=response)]
    }

    # Check for customer identification from set_customer_identified tool
    if raw_updates.get("_customer_identified"):
        customer = CustomerContext(
            customer_id=raw_updates.get("_customer_id"),
            name=raw_updates.get("_customer_name"),
            phone=updated_slots.customer_phone,
            email=updated_slots.customer_email
        )
        result["customer"] = customer

    return result


async def escalation_agent_node(state: ConversationState) -> Dict[str, Any]:
    """Handle escalation requests."""

    user_message = ""
    for msg in reversed(state.messages):
        if isinstance(msg, HumanMessage):
            user_message = msg.content
            break

    response, task = await escalation_agent.handle(user_message, state)

    # Add task to pending tasks
    pending_tasks = state.pending_tasks.copy()
    pending_tasks.append(task)

    return {
        "current_agent": AgentType.ESCALATION,
        "escalation_in_progress": True,
        "human_agent_status": HumanAgentStatus.CHECKING,
        "waiting_for_background": True,
        "pending_tasks": pending_tasks,
        "messages": [AIMessage(content=response)]
    }


async def respond_node(state: ConversationState) -> Dict[str, Any]:
    """
    Generate final response for simple intents or pass through agent responses.

    This node is simplified - agents now handle everything with full context.
    We just need to:
    1. Use existing agent response if present
    2. Generate response for simple intents (greeting, goodbye, general)
    3. Handle notification prepending
    """
    import logging
    logger = logging.getLogger("app.agents.graph")

    user_message = ""
    for msg in reversed(state.messages):
        if isinstance(msg, HumanMessage):
            user_message = msg.content
            break

    logger.info(f"[RESPOND] Processing: '{user_message}', intent: {state.detected_intent}")

    # Check if we already have a response from another agent
    last_msg = state.messages[-1] if state.messages else None
    existing_response = last_msg.content if isinstance(last_msg, AIMessage) else None

    if existing_response:
        # Agent already generated a response - use it
        response = existing_response
        logger.info(f"[RESPOND] Using existing agent response")
        should_add_message = False
    else:
        # Generate response for simple intents (greeting, goodbye, general)
        response = await response_generator.generate(user_message, state)
        logger.info(f"[RESPOND] Generated response: '{response[:50]}...'")
        should_add_message = True

    # Prepend notification message if present
    if state.prepend_message:
        response = f"{state.prepend_message} {response}"
        should_add_message = True  # Need to add the updated message

    return {
        "current_agent": AgentType.RESPONSE,
        "turn_count": state.turn_count + 1,
        "prepend_message": None,  # Clear after use
        "messages": [AIMessage(content=response)] if should_add_message else []
    }


# ============================================
# Routing Functions
# ============================================

def route_after_router(state: ConversationState) -> Literal["faq_agent", "booking_agent", "escalation_agent", "respond"]:
    """Determine next node based on detected intent."""
    import logging
    logger = logging.getLogger("app.agents.graph")

    intent = state.detected_intent

    # Handle both enum and string values (due to use_enum_values=True in Pydantic config)
    if hasattr(intent, 'value'):
        intent_value = intent.value
    else:
        intent_value = intent

    logger.info(f"[ROUTE] Intent value: '{intent_value}'")

    if intent_value == "faq":
        logger.info(f"[ROUTE] -> faq_agent")
        return "faq_agent"
    elif intent_value in ["book_service", "book_test_drive", "reschedule", "cancel"]:
        logger.info(f"[ROUTE] -> booking_agent")
        return "booking_agent"
    elif intent_value == "escalation":
        logger.info(f"[ROUTE] -> escalation_agent")
        return "escalation_agent"
    else:
        logger.info(f"[ROUTE] -> respond (default)")
        return "respond"


# ============================================
# Build Graph
# ============================================

def create_graph():
    """Create the LangGraph conversation graph."""

    # Create graph with state schema
    workflow = StateGraph(ConversationState)

    # Add nodes
    workflow.add_node("check_notifications", check_notifications_node)
    workflow.add_node("router", router_node)
    workflow.add_node("faq_agent", faq_agent_node)
    workflow.add_node("booking_agent", booking_agent_node)
    workflow.add_node("escalation_agent", escalation_agent_node)
    workflow.add_node("respond", respond_node)

    # Set entry point
    workflow.set_entry_point("check_notifications")

    # Add edges
    workflow.add_edge("check_notifications", "router")

    # Conditional routing after router
    workflow.add_conditional_edges(
        "router",
        route_after_router,
        {
            "faq_agent": "faq_agent",
            "booking_agent": "booking_agent",
            "escalation_agent": "escalation_agent",
            "respond": "respond"
        }
    )

    # All agents go to respond
    workflow.add_edge("faq_agent", "respond")
    workflow.add_edge("booking_agent", "respond")
    workflow.add_edge("escalation_agent", "respond")

    # End after respond
    workflow.add_edge("respond", END)

    # Compile without checkpointer - we manage state externally via Redis
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

    Args:
        session_id: Unique session identifier
        user_message: The user's message
        current_state: Current conversation state (optional)

    Returns:
        Updated conversation state
    """
    import logging
    logger = logging.getLogger("app.agents.graph")

    # Initialize state if not provided
    if current_state is None:
        current_state = ConversationState(session_id=session_id)

    logger.info(f"[GRAPH] process_message called with {len(current_state.messages)} existing messages")

    # Build input state dict with the new user message
    # Using add_messages reducer, we pass the new message and it gets merged
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

    # Run graph (stateless - we manage state externally via Redis)
    try:
        result = await conversation_graph.ainvoke(input_state)
        # Convert result back to ConversationState
        return ConversationState(**result)
    except Exception as e:
        # Log error and return state with error message
        import logging
        logging.error(f"Graph invocation error: {e}", exc_info=True)
        # Return state with an error message appended
        error_msg = "I apologize, but I encountered an error processing your request. Please try again."
        return ConversationState(
            **{
                **input_state,
                "messages": input_state["messages"] + [AIMessage(content=error_msg)]
            }
        )


def set_escalation_worker(worker):
    """Set the background worker for escalation agent."""
    escalation_agent.set_background_worker(worker)
