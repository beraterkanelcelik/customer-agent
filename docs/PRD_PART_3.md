# Car Dealership Voice Agent - PRD Part 3 of 6
## LangGraph Agents & Graph Definition

---

# SECTION 1: AGENT ARCHITECTURE

## 1.1 Agent Flow Diagram

```
                         User Message
                              │
                              ▼
                    ┌─────────────────┐
                    │ check_notifs    │ ◄── Check for background task results
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │     router      │ ◄── Classify intent
                    └────────┬────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
         ▼                   ▼                   ▼
   ┌───────────┐      ┌───────────┐      ┌───────────┐
   │ faq_agent │      │  booking  │      │ escalation│
   └─────┬─────┘      │   _agent  │      └─────┬─────┘
         │            └─────┬─────┘            │
         │                  │                  │
         │                  ▼                  │
         │           ┌───────────┐             │
         │           │slot_filler│             │
         │           └─────┬─────┘             │
         │                 │                   │
         └────────────────┬┴───────────────────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │    respond      │ ◄── Generate final response
                 └─────────────────┘
```

---

# SECTION 2: ROUTER AGENT

## 2.1 app/agents/router_agent.py

```python
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from typing import Optional
import json

from app.config import get_settings
from app.schemas.enums import IntentType

settings = get_settings()


class RouterOutput(BaseModel):
    """Structured output from router."""
    intent: IntentType
    confidence: float = Field(ge=0.0, le=1.0)
    entities: dict = Field(default_factory=dict)
    reasoning: str


ROUTER_SYSTEM_PROMPT = """You are an intent classifier for Springfield Auto car dealership voice agent.

Analyze the user's message and classify it into exactly ONE intent:

INTENTS:
- faq: Questions about hours, location, services offered, financing, policies, pricing
- book_service: Wants to schedule a service appointment (oil change, repairs, maintenance, inspection)
- book_test_drive: Wants to test drive or see a specific vehicle
- reschedule: Wants to change/move an existing appointment to different time
- cancel: Wants to cancel an existing appointment
- escalation: Explicitly asks for human/manager, is frustrated, or request is too complex
- greeting: Hello, hi, good morning, how are you (conversation start)
- goodbye: Bye, thanks, that's all, ending conversation
- general: Unclear, off-topic, or doesn't fit other categories

ALSO EXTRACT ENTITIES when present:
- service_type: "oil change", "brake repair", "tire rotation", etc.
- vehicle_make: "Toyota", "Honda", etc.
- vehicle_model: "Camry", "Civic", etc.
- date: Any mentioned date
- time: Any mentioned time
- phone: Phone number if provided
- name: Customer name if provided

Respond with valid JSON only:
{
  "intent": "<intent>",
  "confidence": <0.0-1.0>,
  "entities": {"key": "value"},
  "reasoning": "<brief explanation>"
}
"""


class RouterAgent:
    """Routes user messages to appropriate specialist agents."""
    
    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.openai_model,
            temperature=0,
            api_key=settings.openai_api_key
        )
    
    async def classify(
        self, 
        user_message: str, 
        conversation_history: str = ""
    ) -> RouterOutput:
        """Classify user intent and extract entities."""
        
        context = ""
        if conversation_history:
            context = f"\n\nRecent conversation:\n{conversation_history}\n"
        
        messages = [
            SystemMessage(content=ROUTER_SYSTEM_PROMPT),
            HumanMessage(content=f"{context}User message: {user_message}")
        ]
        
        response = await self.llm.ainvoke(messages)
        
        try:
            # Parse JSON response
            content = response.content.strip()
            # Handle markdown code blocks
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            
            data = json.loads(content)
            return RouterOutput(
                intent=IntentType(data.get("intent", "general")),
                confidence=float(data.get("confidence", 0.5)),
                entities=data.get("entities", {}),
                reasoning=data.get("reasoning", "")
            )
        except Exception as e:
            # Default fallback
            return RouterOutput(
                intent=IntentType.GENERAL,
                confidence=0.3,
                entities={},
                reasoning=f"Parse error: {str(e)}"
            )
    
    def get_next_node(self, intent: IntentType) -> str:
        """Map intent to next graph node."""
        mapping = {
            IntentType.FAQ: "faq_agent",
            IntentType.BOOK_SERVICE: "booking_agent",
            IntentType.BOOK_TEST_DRIVE: "booking_agent",
            IntentType.RESCHEDULE: "booking_agent",
            IntentType.CANCEL: "booking_agent",
            IntentType.ESCALATION: "escalation_agent",
            IntentType.GREETING: "respond",
            IntentType.GOODBYE: "respond",
            IntentType.GENERAL: "respond",
        }
        return mapping.get(intent, "respond")
```

---

# SECTION 3: FAQ AGENT

## 3.1 app/agents/faq_agent.py

```python
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.agents import AgentExecutor, create_openai_tools_agent

from app.config import get_settings
from app.tools.faq_tools import search_faq, list_services

settings = get_settings()


FAQ_SYSTEM_PROMPT = """You are a helpful customer service agent for Springfield Auto dealership.

Your role is to answer customer questions using the FAQ knowledge base.

GUIDELINES:
1. Use search_faq tool to find accurate information
2. Be friendly, professional, and concise
3. Keep responses SHORT - suitable for voice (2-3 sentences max)
4. If info not found, offer to connect with team member
5. Suggest relevant follow-ups when appropriate

TOOLS AVAILABLE:
- search_faq: Search FAQ database by query and optional category
- list_services: List all available services with pricing

VOICE-FRIENDLY TIPS:
- Don't use bullet points or lists
- Use natural speech patterns
- Avoid technical jargon
- Numbers should be spoken naturally ("two thirty" not "2:30")
"""


class FAQAgent:
    """Handles FAQ queries using knowledge base."""
    
    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.openai_model,
            temperature=0.3,
            api_key=settings.openai_api_key
        )
        self.tools = [search_faq, list_services]
        
        self.prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content=FAQ_SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="chat_history"),
            HumanMessage(content="{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])
        
        agent = create_openai_tools_agent(self.llm, self.tools, self.prompt)
        self.executor = AgentExecutor(
            agent=agent,
            tools=self.tools,
            verbose=settings.debug,
            max_iterations=3,
            handle_parsing_errors=True
        )
    
    async def handle(
        self, 
        user_message: str, 
        chat_history: list = None
    ) -> str:
        """Process FAQ query and return response."""
        
        result = await self.executor.ainvoke({
            "input": user_message,
            "chat_history": chat_history or []
        })
        
        return result.get("output", "I'm sorry, I couldn't find that information.")
```

---

# SECTION 4: BOOKING AGENT

## 4.1 app/agents/booking_agent.py

```python
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.agents import AgentExecutor, create_openai_tools_agent
from typing import Optional, Tuple

from app.config import get_settings
from app.schemas.state import ConversationState, BookingSlots
from app.schemas.enums import AppointmentType
from app.tools.booking_tools import (
    check_availability, book_appointment, 
    reschedule_appointment, cancel_appointment,
    get_customer_appointments, list_inventory
)
from app.tools.customer_tools import get_customer, create_customer

settings = get_settings()


BOOKING_SYSTEM_PROMPT = """You are a booking specialist for Springfield Auto dealership.

CURRENT BOOKING STATE:
{booking_state}

CUSTOMER STATUS:
{customer_status}

MISSING INFORMATION:
{missing_slots}

YOUR TASK:
Help the customer complete their booking by collecting missing information ONE PIECE AT A TIME.

BOOKING FLOW:
1. Determine appointment type (service or test drive)
2. For service: what service they need
3. For test drive: what vehicle they want to see
4. Preferred date
5. Preferred time (after checking availability)
6. Customer identification (phone number)
7. If new customer: collect name and email
8. Confirm all details
9. Book the appointment

GUIDELINES:
- Ask for ONE piece of information at a time
- Be conversational, not robotic
- Confirm availability before asking for customer info
- Always verify details before final booking
- Keep responses short for voice

TOOLS:
- check_availability: Check available time slots
- book_appointment: Create the appointment
- reschedule_appointment: Change existing appointment
- cancel_appointment: Cancel appointment
- get_customer_appointments: Find customer's appointments
- get_customer: Look up customer by phone
- create_customer: Register new customer
- list_inventory: Show vehicles for test drive
"""


class BookingAgent:
    """Handles appointment booking, rescheduling, and cancellation."""
    
    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.openai_model,
            temperature=0.3,
            api_key=settings.openai_api_key
        )
        
        self.tools = [
            check_availability,
            book_appointment,
            reschedule_appointment,
            cancel_appointment,
            get_customer_appointments,
            get_customer,
            create_customer,
            list_inventory
        ]
    
    def _build_prompt(self, state: ConversationState) -> ChatPromptTemplate:
        """Build dynamic prompt with current booking state."""
        
        # Booking state summary
        booking_state = state.booking_slots.to_summary()
        
        # Customer status
        if state.customer.is_identified:
            customer_status = state.customer.to_summary()
        else:
            customer_status = "Customer not yet identified. Need to collect phone number."
        
        # Missing slots
        is_new = not state.customer.is_identified
        missing = state.booking_slots.get_missing_slots(is_new_customer=is_new)
        missing_slots = ", ".join(missing) if missing else "All information collected - ready to book!"
        
        system_content = BOOKING_SYSTEM_PROMPT.format(
            booking_state=booking_state,
            customer_status=customer_status,
            missing_slots=missing_slots
        )
        
        return ChatPromptTemplate.from_messages([
            SystemMessage(content=system_content),
            MessagesPlaceholder(variable_name="chat_history"),
            HumanMessage(content="{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])
    
    async def handle(
        self, 
        user_message: str,
        state: ConversationState,
        chat_history: list = None
    ) -> Tuple[str, BookingSlots]:
        """
        Process booking request.
        
        Returns:
            Tuple of (response_text, updated_booking_slots)
        """
        
        prompt = self._build_prompt(state)
        
        agent = create_openai_tools_agent(self.llm, self.tools, prompt)
        executor = AgentExecutor(
            agent=agent,
            tools=self.tools,
            verbose=settings.debug,
            max_iterations=5,
            handle_parsing_errors=True
        )
        
        result = await executor.ainvoke({
            "input": user_message,
            "chat_history": chat_history or []
        })
        
        response = result.get("output", "I'm having trouble with that booking. Can you try again?")
        
        # Extract any slot updates from the conversation
        updated_slots = self._extract_slots(user_message, state.booking_slots)
        
        return response, updated_slots
    
    def _extract_slots(
        self, 
        user_message: str, 
        current_slots: BookingSlots
    ) -> BookingSlots:
        """Extract slot values from user message."""
        
        message_lower = user_message.lower()
        slots = current_slots.model_copy()
        
        # Detect appointment type
        if not slots.appointment_type:
            if any(word in message_lower for word in ["oil", "brake", "tire", "service", "repair", "maintenance", "inspection"]):
                slots.appointment_type = AppointmentType.SERVICE
            elif any(word in message_lower for word in ["test drive", "see the", "look at", "drive the"]):
                slots.appointment_type = AppointmentType.TEST_DRIVE
        
        # Detect service type
        if slots.appointment_type == AppointmentType.SERVICE and not slots.service_type:
            services = ["oil change", "brake", "tire rotation", "battery", "inspection", "ac service"]
            for service in services:
                if service in message_lower:
                    slots.service_type = service.title()
                    break
        
        # Date detection (basic patterns)
        if not slots.preferred_date:
            if "tomorrow" in message_lower:
                from datetime import date, timedelta
                slots.preferred_date = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
            elif "today" in message_lower:
                from datetime import date
                slots.preferred_date = date.today().strftime("%Y-%m-%d")
        
        # Time detection (basic patterns)
        if not slots.preferred_time:
            import re
            time_pattern = r'(\d{1,2})(?::(\d{2}))?\s*(am|pm|AM|PM)?'
            match = re.search(time_pattern, user_message)
            if match:
                hour = int(match.group(1))
                minute = match.group(2) or "00"
                period = match.group(3)
                
                if period and period.lower() == "pm" and hour < 12:
                    hour += 12
                elif period and period.lower() == "am" and hour == 12:
                    hour = 0
                
                if 0 <= hour <= 23:
                    slots.preferred_time = f"{hour:02d}:{minute}"
        
        return slots
```

---

# SECTION 5: ESCALATION AGENT

## 5.1 app/agents/escalation_agent.py

```python
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
import asyncio
import time
from typing import Tuple

from app.config import get_settings
from app.schemas.state import ConversationState
from app.schemas.task import BackgroundTask
from app.schemas.enums import TaskType, TaskStatus, HumanAgentStatus

settings = get_settings()


ESCALATION_SYSTEM_PROMPT = """You are handling a customer escalation request for Springfield Auto dealership.

The customer wants to speak with a human team member.

Your job:
1. Acknowledge their request warmly
2. Let them know you're checking availability
3. Assure them they can continue asking questions while you check

Keep response SHORT and reassuring. Example:
"Absolutely, let me check if one of our team members is available right now. This might take just a moment. While I'm checking, is there anything else I can help you with?"
"""


class EscalationAgent:
    """Handles human escalation requests with async background check."""
    
    def __init__(self, background_worker=None):
        self.llm = ChatOpenAI(
            model=settings.openai_model,
            temperature=0.3,
            api_key=settings.openai_api_key
        )
        self.background_worker = background_worker
    
    def set_background_worker(self, worker):
        """Set the background worker reference."""
        self.background_worker = worker
    
    async def handle(
        self,
        user_message: str,
        state: ConversationState
    ) -> Tuple[str, BackgroundTask]:
        """
        Handle escalation request.
        
        Returns:
            Tuple of (response_text, background_task)
        """
        
        # Generate response
        messages = [
            SystemMessage(content=ESCALATION_SYSTEM_PROMPT),
            HumanMessage(content=f"Customer said: {user_message}")
        ]
        
        response = await self.llm.ainvoke(messages)
        response_text = response.content
        
        # Create background task
        task_id = f"esc_{state.session_id}_{int(time.time())}"
        task = BackgroundTask(
            task_id=task_id,
            task_type=TaskType.HUMAN_ESCALATION,
            status=TaskStatus.PENDING
        )
        
        # Spawn background check (non-blocking)
        if self.background_worker:
            asyncio.create_task(
                self.background_worker.execute_human_check(
                    task_id=task_id,
                    session_id=state.session_id,
                    customer_phone=state.customer.phone,
                    reason=user_message
                )
            )
        
        return response_text, task
```

---

# SECTION 6: RESPONSE GENERATOR

## 6.1 app/agents/response_generator.py

```python
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from app.config import get_settings
from app.schemas.state import ConversationState
from app.schemas.enums import IntentType

settings = get_settings()


RESPONSE_SYSTEM_PROMPT = """You are a friendly voice agent for Springfield Auto dealership.

Generate a natural, conversational response for the given situation.

VOICE GUIDELINES:
- Keep responses SHORT (1-3 sentences)
- Use natural speech patterns
- Be warm and professional
- Don't use bullet points or lists
- Avoid jargon

CURRENT CONTEXT:
Intent: {intent}
Customer: {customer_info}
"""

GREETING_RESPONSES = [
    "Hello! Welcome to Springfield Auto. How can I help you today?",
    "Hi there! Thanks for calling Springfield Auto. What can I do for you?",
    "Good day! You've reached Springfield Auto. How may I assist you?",
]

GOODBYE_RESPONSES = [
    "Thank you for calling Springfield Auto! Have a great day!",
    "Thanks for reaching out! Take care and drive safe!",
    "It was my pleasure helping you. Goodbye!",
]


class ResponseGenerator:
    """Generates final responses for simple intents."""
    
    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.openai_model,
            temperature=0.5,
            api_key=settings.openai_api_key
        )
    
    async def generate(
        self,
        user_message: str,
        state: ConversationState,
        agent_response: str = None
    ) -> str:
        """Generate or enhance response."""
        
        # Handle simple intents directly
        if state.detected_intent == IntentType.GREETING:
            import random
            return random.choice(GREETING_RESPONSES)
        
        if state.detected_intent == IntentType.GOODBYE:
            import random
            return random.choice(GOODBYE_RESPONSES)
        
        # If we have an agent response, optionally enhance it
        if agent_response:
            return agent_response
        
        # Generate general response
        customer_info = state.customer.to_summary() if state.customer.is_identified else "New customer"
        
        system_content = RESPONSE_SYSTEM_PROMPT.format(
            intent=state.detected_intent.value if state.detected_intent else "general",
            customer_info=customer_info
        )
        
        messages = [
            SystemMessage(content=system_content),
            HumanMessage(content=user_message)
        ]
        
        response = await self.llm.ainvoke(messages)
        return response.content
```

---

# SECTION 7: LANGGRAPH GRAPH DEFINITION

## 7.1 app/agents/graph.py

```python
from typing import Literal, Dict, Any
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage

from app.schemas.state import ConversationState
from app.schemas.enums import AgentType, IntentType, HumanAgentStatus, TaskStatus
from app.schemas.task import Notification, NotificationPriority

from .router_agent import RouterAgent
from .faq_agent import FAQAgent
from .booking_agent import BookingAgent
from .escalation_agent import EscalationAgent
from .response_generator import ResponseGenerator


# Initialize agents
router_agent = RouterAgent()
faq_agent = FAQAgent()
booking_agent = BookingAgent()
escalation_agent = EscalationAgent()
response_generator = ResponseGenerator()


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
    priority_order = {
        NotificationPriority.INTERRUPT: 3,
        NotificationPriority.HIGH: 2,
        NotificationPriority.LOW: 1
    }
    
    notifications.sort(key=lambda n: priority_order.get(n.priority, 0), reverse=True)
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
            if task.status == TaskStatus.COMPLETED:
                updates["waiting_for_background"] = False
                if task.human_available:
                    updates["human_agent_status"] = HumanAgentStatus.CONNECTED
                else:
                    updates["human_agent_status"] = HumanAgentStatus.UNAVAILABLE
                    updates["escalation_in_progress"] = False
    
    return updates


async def router_node(state: ConversationState) -> Dict[str, Any]:
    """Route user message to appropriate agent."""
    
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
    
    # Classify intent
    result = await router_agent.classify(user_message, history)
    
    return {
        "detected_intent": result.intent,
        "confidence": result.confidence,
        "current_agent": AgentType.ROUTER
    }


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
    
    user_message = ""
    for msg in reversed(state.messages):
        if isinstance(msg, HumanMessage):
            user_message = msg.content
            break
    
    chat_history = []
    for msg in state.messages[:-1]:
        if isinstance(msg, HumanMessage):
            chat_history.append(HumanMessage(content=msg.content))
        elif isinstance(msg, AIMessage):
            chat_history.append(AIMessage(content=msg.content))
    
    response, updated_slots = await booking_agent.handle(
        user_message, 
        state, 
        chat_history
    )
    
    return {
        "current_agent": AgentType.BOOKING,
        "booking_slots": updated_slots,
        "messages": [AIMessage(content=response)]
    }


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
    """Generate final response for simple intents."""
    
    user_message = ""
    for msg in reversed(state.messages):
        if isinstance(msg, HumanMessage):
            user_message = msg.content
            break
    
    # Check if we already have a response from another agent
    last_msg = state.messages[-1] if state.messages else None
    if isinstance(last_msg, AIMessage):
        response = last_msg.content
    else:
        response = await response_generator.generate(user_message, state)
    
    # Prepend notification message if present
    if state.prepend_message:
        response = f"{state.prepend_message} {response}"
    
    # Increment turn count
    return {
        "current_agent": AgentType.RESPONSE,
        "turn_count": state.turn_count + 1,
        "prepend_message": None,  # Clear after use
        "messages": [AIMessage(content=response)] if not isinstance(last_msg, AIMessage) else []
    }


# ============================================
# Routing Functions
# ============================================

def route_after_router(state: ConversationState) -> Literal["faq_agent", "booking_agent", "escalation_agent", "respond"]:
    """Determine next node based on detected intent."""
    
    intent = state.detected_intent
    
    if intent == IntentType.FAQ:
        return "faq_agent"
    elif intent in [IntentType.BOOK_SERVICE, IntentType.BOOK_TEST_DRIVE, 
                    IntentType.RESCHEDULE, IntentType.CANCEL]:
        return "booking_agent"
    elif intent == IntentType.ESCALATION:
        return "escalation_agent"
    else:
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
    
    # Compile with memory checkpointer
    memory = MemorySaver()
    graph = workflow.compile(checkpointer=memory)
    
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
    
    # Initialize state if not provided
    if current_state is None:
        current_state = ConversationState(session_id=session_id)
    
    # Add user message
    current_state.messages.append(HumanMessage(content=user_message))
    
    # Configure for this session
    config = {"configurable": {"thread_id": session_id}}
    
    # Run graph
    result = await conversation_graph.ainvoke(
        current_state.model_dump(),
        config=config
    )
    
    # Convert result back to ConversationState
    return ConversationState(**result)


def set_escalation_worker(worker):
    """Set the background worker for escalation agent."""
    escalation_agent.set_background_worker(worker)
```

## 7.2 app/agents/__init__.py

```python
from .graph import (
    conversation_graph,
    process_message,
    set_escalation_worker
)
from .router_agent import RouterAgent
from .faq_agent import FAQAgent
from .booking_agent import BookingAgent
from .escalation_agent import EscalationAgent
from .response_generator import ResponseGenerator

__all__ = [
    "conversation_graph",
    "process_message",
    "set_escalation_worker",
    "RouterAgent",
    "FAQAgent", 
    "BookingAgent",
    "EscalationAgent",
    "ResponseGenerator"
]
```

---

**END OF PART 3**

Say "continue" to get Part 4: Tools & Background Tasks
