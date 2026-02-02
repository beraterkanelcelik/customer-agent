from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

from .enums import AgentType, IntentType
from .customer import CustomerContext, CustomerResponse
from .appointment import AppointmentResponse
from .task import BackgroundTask, Notification


# ============================================
# Request Schemas
# ============================================

class ChatRequest(BaseModel):
    """Chat message request."""
    session_id: str
    message: str = Field(..., min_length=1, max_length=2000)


class CreateSessionRequest(BaseModel):
    """Create new session."""
    session_id: Optional[str] = None  # If provided, use this; otherwise generate one
    customer_phone: Optional[str] = None


class VoiceTokenRequest(BaseModel):
    """Request voice session token."""
    session_id: str


class SalesTokenRequest(BaseModel):
    """Request voice token for sales to join a call."""
    session_id: str
    sales_id: str = "sales_001"


class SalesRespondRequest(BaseModel):
    """Sales response to incoming call."""
    session_id: str
    accepted: bool
    sales_id: str = "sales_001"


class SalesRespondResponse(BaseModel):
    """Response to sales respond request."""
    success: bool
    message: str
    session_id: str


# ============================================
# Response Schemas
# ============================================

class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "healthy"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    version: str = "1.0.0"
    services: Dict[str, str] = Field(default_factory=dict)


class SessionResponse(BaseModel):
    """Session info response."""
    session_id: str
    created_at: datetime
    turn_count: int
    current_agent: str
    customer: Optional[CustomerContext] = None
    is_active: bool = True


class ChatResponse(BaseModel):
    """Chat response with state."""
    session_id: str
    response: str
    agent_type: str
    intent: Optional[str] = None
    confidence: float = 0.0

    # State snapshot
    customer: Optional[CustomerContext] = None
    booking_slots: Optional[Dict[str, Any]] = None
    confirmed_appointment: Optional[Dict[str, Any]] = None
    pending_tasks: List[BackgroundTask] = Field(default_factory=list)

    # Escalation state
    escalation_in_progress: bool = False
    human_agent_status: Optional[str] = None


class VoiceTokenResponse(BaseModel):
    """Voice session token response."""
    token: str
    livekit_url: str
    session_id: str


# ============================================
# WebSocket Messages
# ============================================

class WSMessage(BaseModel):
    """Base WebSocket message."""
    type: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class WSStateUpdate(WSMessage):
    """State update broadcast."""
    type: str = "state_update"
    session_id: str
    current_agent: str
    intent: Optional[str] = None
    confidence: float = 0.0
    escalation_in_progress: bool = False
    human_agent_status: Optional[str] = None
    customer: Optional[CustomerContext] = None
    booking_slots: Optional[Dict[str, Any]] = None
    confirmed_appointment: Optional[Dict[str, Any]] = None
    pending_tasks: List[BackgroundTask] = Field(default_factory=list)


class WSTranscript(WSMessage):
    """Transcript message."""
    type: str = "transcript"
    session_id: str
    role: str
    content: str
    agent_type: Optional[str] = None


class WSTaskUpdate(WSMessage):
    """Task status update."""
    type: str = "task_update"
    session_id: str
    task: BackgroundTask


class WSNotification(WSMessage):
    """Notification broadcast."""
    type: str = "notification"
    session_id: str
    notification: Notification


class WSError(WSMessage):
    """Error message."""
    type: str = "error"
    error: str
    code: Optional[str] = None


# ============================================
# List Responses
# ============================================

class FAQEntry(BaseModel):
    """FAQ entry."""
    id: int
    category: str
    question: str
    answer: str

    class Config:
        from_attributes = True


class FAQListResponse(BaseModel):
    """FAQ list."""
    entries: List[FAQEntry]
    total: int


class AppointmentListResponse(BaseModel):
    """Appointment list."""
    appointments: List[AppointmentResponse]
    total: int


class CustomerListResponse(BaseModel):
    """Customer list."""
    customers: List[CustomerResponse]
    total: int


# ============================================
# Availability Schemas
# ============================================

class AvailabilitySlotResponse(BaseModel):
    """Single availability slot."""
    id: int
    slot_time: str  # HH:MM format
    appointment_type: str
    is_available: bool
    inventory_id: Optional[int] = None  # For test drives - which car
    vehicle_name: Optional[str] = None  # e.g., "2025 Toyota Camry"

    class Config:
        from_attributes = True


class AvailabilityDayResponse(BaseModel):
    """Availability for a single day."""
    date: str  # YYYY-MM-DD format
    day_name: str  # Monday, Tuesday, etc.
    is_open: bool
    slots: List[AvailabilitySlotResponse]


class AvailabilityResponse(BaseModel):
    """Full availability response for calendar view."""
    start_date: str
    end_date: str
    days: List[AvailabilityDayResponse]
    total_available: int
