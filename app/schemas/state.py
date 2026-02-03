from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any, Annotated
from datetime import datetime

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langgraph.graph.message import add_messages

from .enums import AgentType, IntentType, AppointmentType, HumanAgentStatus, TaskStatus, TaskType
from .customer import CustomerContext
from .task import BackgroundTask, Notification


def deserialize_messages(messages: List[Any]) -> List[BaseMessage]:
    """Convert serialized message dicts back to LangChain message objects."""
    result = []
    for msg in messages:
        if isinstance(msg, BaseMessage):
            result.append(msg)
        elif isinstance(msg, dict):
            msg_type = msg.get("type", "")
            content = msg.get("content", "")
            if msg_type == "human":
                result.append(HumanMessage(content=content))
            elif msg_type == "ai":
                result.append(AIMessage(content=content))
            elif msg_type == "HumanMessage":
                result.append(HumanMessage(content=content))
            elif msg_type == "AIMessage":
                result.append(AIMessage(content=content))
            else:
                # Default to human message if unknown
                result.append(HumanMessage(content=content))
    return result


class ConfirmedAppointment(BaseModel):
    """Represents a confirmed appointment for display in the frontend."""
    appointment_id: int
    appointment_type: str
    scheduled_date: str
    scheduled_time: str
    customer_name: str
    service_type: Optional[str] = None
    vehicle: Optional[str] = None
    confirmation_email: Optional[str] = None


class BookingSlots(BaseModel):
    """Slots being collected for booking."""
    appointment_type: Optional[AppointmentType] = None
    service_type: Optional[str] = None
    service_type_id: Optional[int] = None
    vehicle_interest: Optional[str] = None
    inventory_id: Optional[int] = None
    preferred_date: Optional[str] = None  # YYYY-MM-DD
    preferred_time: Optional[str] = None  # HH:MM

    # New customer info
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    customer_vehicle_make: Optional[str] = None
    customer_vehicle_model: Optional[str] = None
    customer_vehicle_year: Optional[int] = None

    def get_missing_slots(self, is_new_customer: bool = True) -> List[str]:
        """Get list of missing required slots.

        IMPORTANT: Customer info is collected FIRST before any booking details.
        This ensures we have contact info before proceeding with appointment details.
        """
        missing = []

        # Step 1: Customer info FIRST (blocking) - must have all before proceeding
        if is_new_customer:
            if not self.customer_name:
                missing.append("customer_name")
            if not self.customer_phone:
                missing.append("customer_phone")
            if not self.customer_email:
                missing.append("customer_email")
            # Block until customer info is complete
            if missing:
                return missing

        # Step 2: Appointment type
        if self.appointment_type is None:
            return ["appointment_type"]

        # Handle both enum and string values
        appt_type = self.appointment_type.value if hasattr(self.appointment_type, 'value') else self.appointment_type

        # Step 3: Details based on type
        if appt_type == "service":
            if not self.service_type:
                return ["service_type"]
        elif appt_type == "test_drive":
            if not self.vehicle_interest:
                return ["vehicle_interest"]

        # Step 4: Date/time
        if not self.preferred_date:
            return ["preferred_date"]
        if not self.preferred_time:
            return ["preferred_time"]

        return missing

    def is_complete(self, is_new_customer: bool = True) -> bool:
        return len(self.get_missing_slots(is_new_customer)) == 0

    def to_summary(self) -> str:
        """Generate summary for prompts."""
        parts = []
        if self.appointment_type:
            parts.append(f"Type: {self.appointment_type.value}")
        if self.service_type:
            parts.append(f"Service: {self.service_type}")
        if self.vehicle_interest:
            parts.append(f"Vehicle: {self.vehicle_interest}")
        if self.preferred_date:
            parts.append(f"Date: {self.preferred_date}")
        if self.preferred_time:
            parts.append(f"Time: {self.preferred_time}")
        if self.customer_name:
            parts.append(f"Name: {self.customer_name}")
        if self.customer_phone:
            parts.append(f"Phone: {self.customer_phone}")
        return "\n".join(parts) if parts else "No slots collected yet"


class ConversationState(BaseModel):
    """
    Main conversation state for LangGraph.

    This state flows through the entire graph and maintains
    all context needed for the conversation.
    """
    # Session
    session_id: str

    # Messages - using LangGraph's add_messages for proper deduplication
    messages: Annotated[List[BaseMessage], add_messages] = Field(default_factory=list)

    @field_validator("messages", mode="before")
    @classmethod
    def validate_messages(cls, v):
        """Deserialize messages from JSON dicts to LangChain message objects."""
        if isinstance(v, list):
            return deserialize_messages(v)
        return v

    # Current processing
    current_agent: AgentType = AgentType.UNIFIED
    detected_intent: Optional[IntentType] = None
    confidence: float = 0.0

    # Customer
    customer: CustomerContext = Field(default_factory=CustomerContext)

    # Booking
    booking_slots: BookingSlots = Field(default_factory=BookingSlots)
    pending_confirmation: Optional[Dict[str, Any]] = None
    confirmed_appointment: Optional[ConfirmedAppointment] = None

    # Background tasks
    pending_tasks: List[BackgroundTask] = Field(default_factory=list)
    notifications_queue: List[Notification] = Field(default_factory=list)

    # Escalation
    escalation_in_progress: bool = False
    human_agent_status: Optional[HumanAgentStatus] = None

    # Flow control
    should_respond: bool = True
    needs_slot_filling: bool = False
    waiting_for_background: bool = False

    # Voice call indicator
    is_voice_call: bool = False

    # Response to prepend (from notifications)
    prepend_message: Optional[str] = None

    # Metadata
    turn_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    # Version for optimistic locking
    version: int = 0

    class Config:
        arbitrary_types_allowed = True
        use_enum_values = True

    def get_undelivered_notifications(self) -> List[Notification]:
        return [n for n in self.notifications_queue if not n.delivered]

    def get_active_tasks(self) -> List[BackgroundTask]:
        # Handle both enum and string values
        active_statuses = ["pending", "running"]
        return [t for t in self.pending_tasks
                if (t.status.value if hasattr(t.status, 'value') else t.status) in active_statuses]

    def has_pending_escalation(self) -> bool:
        # Handle both enum and string values
        active_statuses = ["pending", "running"]
        def is_active_escalation(t):
            task_type = t.task_type.value if hasattr(t.task_type, 'value') else t.task_type
            status = t.status.value if hasattr(t.status, 'value') else t.status
            return task_type == "human_escalation" and status in active_statuses
        return any(is_active_escalation(t) for t in self.pending_tasks)

    def get_conversation_history(self, max_turns: int = 10) -> str:
        """Get formatted conversation history for prompts."""
        recent = self.messages[-max_turns * 2:] if len(self.messages) > max_turns * 2 else self.messages
        lines = []
        for msg in recent:
            if isinstance(msg, HumanMessage):
                lines.append(f"User: {msg.content}")
            elif isinstance(msg, AIMessage):
                lines.append(f"Agent: {msg.content}")
        return "\n".join(lines)
