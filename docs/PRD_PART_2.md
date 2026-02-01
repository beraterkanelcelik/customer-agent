# Car Dealership Voice Agent - PRD Part 2 of 6
## Pydantic Schemas & Database Models

---

# SECTION 1: CONFIGURATION

## 1.1 app/config.py

```python
from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache


class Settings(BaseSettings):
    """Application configuration with Pydantic validation."""
    
    # OpenAI
    openai_api_key: str = Field(..., validation_alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4-turbo-preview")
    
    # LiveKit
    livekit_url: str = Field(default="ws://localhost:7880")
    livekit_api_key: str = Field(default="devkey")
    livekit_api_secret: str = Field(default="secret")
    
    # Database
    database_url: str = Field(default="sqlite+aiosqlite:///./data/dealership.db")
    
    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0")
    
    # Voice
    whisper_model: str = Field(default="base")
    whisper_device: str = Field(default="cpu")
    piper_voice: str = Field(default="en_US-amy-medium")
    
    # App
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")
    
    # Background Tasks
    human_check_min_seconds: int = Field(default=5)
    human_check_max_seconds: int = Field(default=10)
    human_availability_chance: float = Field(default=0.6)
    
    # Session
    session_timeout_minutes: int = Field(default=30)
    max_turns: int = Field(default=50)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
```

---

# SECTION 2: ENUMS

## 2.1 app/schemas/enums.py

```python
from enum import Enum


class AgentType(str, Enum):
    """Agent types in the multi-agent system."""
    ROUTER = "router"
    FAQ = "faq"
    BOOKING = "booking"
    ESCALATION = "escalation"
    SLOT_FILLER = "slot_filler"
    RESPONSE = "response"


class IntentType(str, Enum):
    """User intent classifications."""
    FAQ = "faq"
    BOOK_SERVICE = "book_service"
    BOOK_TEST_DRIVE = "book_test_drive"
    RESCHEDULE = "reschedule"
    CANCEL = "cancel"
    ESCALATION = "escalation"
    GREETING = "greeting"
    GOODBYE = "goodbye"
    GENERAL = "general"


class AppointmentType(str, Enum):
    """Types of appointments."""
    SERVICE = "service"
    TEST_DRIVE = "test_drive"


class AppointmentStatus(str, Enum):
    """Appointment statuses."""
    SCHEDULED = "scheduled"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class TaskStatus(str, Enum):
    """Background task statuses."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskType(str, Enum):
    """Background task types."""
    HUMAN_ESCALATION = "human_escalation"
    SEND_EMAIL = "send_email"
    SCHEDULE_CALLBACK = "schedule_callback"


class NotificationPriority(str, Enum):
    """Notification priority levels."""
    LOW = "low"           # Deliver on next user turn
    HIGH = "high"         # Deliver at next pause
    INTERRUPT = "interrupt"  # Interrupt current speech


class HumanAgentStatus(str, Enum):
    """Human agent availability status."""
    CHECKING = "checking"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    CONNECTED = "connected"


class MessageRole(str, Enum):
    """Conversation message roles."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"
```

---

# SECTION 3: PYDANTIC SCHEMAS

## 3.1 app/schemas/customer.py

```python
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime


class VehicleBase(BaseModel):
    """Base vehicle schema."""
    make: str = Field(..., min_length=1, max_length=50, examples=["Toyota"])
    model: str = Field(..., min_length=1, max_length=50, examples=["Camry"])
    year: Optional[int] = Field(default=None, ge=1900, le=2030, examples=[2022])
    license_plate: Optional[str] = Field(default=None, max_length=20)
    vin: Optional[str] = Field(default=None, max_length=17)


class VehicleCreate(VehicleBase):
    """Create vehicle request."""
    pass


class VehicleResponse(VehicleBase):
    """Vehicle response with ID."""
    id: int
    customer_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class CustomerBase(BaseModel):
    """Base customer schema."""
    phone: str = Field(..., min_length=10, max_length=20, examples=["555-123-4567"])
    name: Optional[str] = Field(default=None, max_length=100, examples=["John Doe"])
    email: Optional[EmailStr] = Field(default=None, examples=["john@example.com"])


class CustomerCreate(CustomerBase):
    """Create customer request."""
    vehicle: Optional[VehicleCreate] = None


class CustomerUpdate(BaseModel):
    """Update customer request."""
    name: Optional[str] = Field(default=None, max_length=100)
    email: Optional[EmailStr] = None


class CustomerResponse(CustomerBase):
    """Customer response with relationships."""
    id: int
    vehicles: List[VehicleResponse] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CustomerContext(BaseModel):
    """Customer context for conversation state."""
    customer_id: Optional[int] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    vehicles: List[dict] = Field(default_factory=list)

    @property
    def is_identified(self) -> bool:
        return self.customer_id is not None
    
    def to_summary(self) -> str:
        """Generate summary string for prompts."""
        if not self.is_identified:
            return "Customer not yet identified"
        
        summary = f"Customer: {self.name or 'Unknown'} (ID: {self.customer_id})"
        if self.phone:
            summary += f", Phone: {self.phone}"
        if self.vehicles:
            v = self.vehicles[0]
            summary += f", Vehicle: {v.get('year', '')} {v.get('make', '')} {v.get('model', '')}"
        return summary
```

## 3.2 app/schemas/appointment.py

```python
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import date, time, datetime

from .enums import AppointmentType, AppointmentStatus


class TimeSlot(BaseModel):
    """Available time slot."""
    date: date
    start_time: time
    end_time: time
    is_available: bool = True

    def format_time(self) -> str:
        return self.start_time.strftime("%I:%M %p").lstrip("0")


class ServiceTypeResponse(BaseModel):
    """Service type info."""
    id: int
    name: str
    estimated_duration_minutes: int
    estimated_price_min: Optional[float] = None
    estimated_price_max: Optional[float] = None

    class Config:
        from_attributes = True

    def price_display(self) -> str:
        if self.estimated_price_min is None or self.estimated_price_min == 0:
            return "Free"
        if self.estimated_price_min == self.estimated_price_max:
            return f"${self.estimated_price_min:.2f}"
        return f"${self.estimated_price_min:.2f} - ${self.estimated_price_max:.2f}"


class InventoryVehicleResponse(BaseModel):
    """Inventory vehicle for test drives."""
    id: int
    make: str
    model: str
    year: int
    color: Optional[str] = None
    price: Optional[float] = None
    is_new: bool = True
    stock_number: Optional[str] = None

    class Config:
        from_attributes = True

    def display_name(self) -> str:
        return f"{self.year} {self.make} {self.model}"


class AppointmentBase(BaseModel):
    """Base appointment schema."""
    appointment_type: AppointmentType
    scheduled_date: date
    scheduled_time: time
    duration_minutes: int = Field(default=60, ge=15, le=480)
    notes: Optional[str] = Field(default=None, max_length=500)


class AppointmentCreate(AppointmentBase):
    """Create appointment request."""
    customer_id: int
    vehicle_id: Optional[int] = None
    inventory_id: Optional[int] = None
    service_type_id: Optional[int] = None


class AppointmentUpdate(BaseModel):
    """Update appointment request."""
    scheduled_date: Optional[date] = None
    scheduled_time: Optional[time] = None
    status: Optional[AppointmentStatus] = None
    notes: Optional[str] = None


class AppointmentResponse(AppointmentBase):
    """Appointment response."""
    id: int
    customer_id: int
    vehicle_id: Optional[int] = None
    inventory_id: Optional[int] = None
    service_type_id: Optional[int] = None
    status: AppointmentStatus = AppointmentStatus.SCHEDULED
    created_at: datetime
    updated_at: datetime
    
    service_type: Optional[ServiceTypeResponse] = None
    inventory_vehicle: Optional[InventoryVehicleResponse] = None

    class Config:
        from_attributes = True

    def display_datetime(self) -> str:
        date_str = self.scheduled_date.strftime("%A, %B %d")
        time_str = self.scheduled_time.strftime("%I:%M %p").lstrip("0")
        return f"{date_str} at {time_str}"


class AvailabilityRequest(BaseModel):
    """Check availability request."""
    appointment_type: AppointmentType
    preferred_date: date
    preferred_time: Optional[time] = None


class AvailabilityResponse(BaseModel):
    """Availability check response."""
    available: bool
    slots: List[TimeSlot] = []
    next_available: Optional[date] = None
    message: str


class BookingConfirmation(BaseModel):
    """Booking confirmation."""
    success: bool
    appointment_id: Optional[int] = None
    confirmation_message: str
    appointment: Optional[AppointmentResponse] = None
```

## 3.3 app/schemas/task.py

```python
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime

from .enums import TaskStatus, TaskType, NotificationPriority


class BackgroundTask(BaseModel):
    """Background task model."""
    task_id: str = Field(..., examples=["esc_sess123_1706789000"])
    task_type: TaskType
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    
    # Human escalation specific
    human_agent_id: Optional[str] = None
    human_agent_name: Optional[str] = None
    human_available: Optional[bool] = None
    callback_scheduled: Optional[str] = None

    class Config:
        use_enum_values = True


class HumanCheckResult(BaseModel):
    """Result of human availability check."""
    human_available: bool
    human_agent_id: Optional[str] = None
    human_agent_name: Optional[str] = None
    estimated_wait: Optional[str] = None
    reason: Optional[str] = None
    callback_scheduled: Optional[str] = None
    email_sent: bool = False


class Notification(BaseModel):
    """Notification from background task."""
    notification_id: str = Field(..., examples=["notif_1706789000123"])
    task_id: str
    message: str
    priority: NotificationPriority
    delivered: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True
```

## 3.4 app/schemas/state.py (LangGraph State)

```python
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Annotated
from datetime import datetime
from operator import add

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

from .enums import AgentType, IntentType, AppointmentType, HumanAgentStatus
from .customer import CustomerContext
from .task import BackgroundTask, Notification


def merge_messages(left: List[BaseMessage], right: List[BaseMessage]) -> List[BaseMessage]:
    """Merge message lists (append right to left)."""
    return left + right


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
        """Get list of missing required slots."""
        missing = []
        
        if self.appointment_type is None:
            missing.append("appointment_type")
            return missing  # Can't determine other requirements yet
        
        if self.appointment_type == AppointmentType.SERVICE:
            if not self.service_type:
                missing.append("service_type")
        elif self.appointment_type == AppointmentType.TEST_DRIVE:
            if not self.vehicle_interest:
                missing.append("vehicle_interest")
        
        if not self.preferred_date:
            missing.append("preferred_date")
        if not self.preferred_time:
            missing.append("preferred_time")
        
        if is_new_customer:
            if not self.customer_name:
                missing.append("customer_name")
            if not self.customer_phone:
                missing.append("customer_phone")
            if not self.customer_email:
                missing.append("customer_email")
        
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
    
    # Messages - using list that gets merged
    messages: Annotated[List[BaseMessage], merge_messages] = Field(default_factory=list)
    
    # Current processing
    current_agent: AgentType = AgentType.ROUTER
    detected_intent: Optional[IntentType] = None
    confidence: float = 0.0
    
    # Customer
    customer: CustomerContext = Field(default_factory=CustomerContext)
    
    # Booking
    booking_slots: BookingSlots = Field(default_factory=BookingSlots)
    pending_confirmation: Optional[Dict[str, Any]] = None
    
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
    
    # Response to prepend (from notifications)
    prepend_message: Optional[str] = None
    
    # Metadata
    turn_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        arbitrary_types_allowed = True
        use_enum_values = True

    def get_undelivered_notifications(self) -> List[Notification]:
        return [n for n in self.notifications_queue if not n.delivered]

    def get_active_tasks(self) -> List[BackgroundTask]:
        return [t for t in self.pending_tasks 
                if t.status in [TaskStatus.PENDING, TaskStatus.RUNNING]]

    def has_pending_escalation(self) -> bool:
        return any(
            t.task_type == TaskType.HUMAN_ESCALATION 
            and t.status in [TaskStatus.PENDING, TaskStatus.RUNNING]
            for t in self.pending_tasks
        )
    
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
```

## 3.5 app/schemas/api.py

```python
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
    customer_phone: Optional[str] = None


class VoiceTokenRequest(BaseModel):
    """Request voice session token."""
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
    pending_tasks: List[BackgroundTask] = Field(default_factory=list)


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
    customer: Optional[CustomerContext] = None
    booking_slots: Optional[Dict[str, Any]] = None
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
```

---

# SECTION 4: DATABASE MODELS

## 4.1 app/database/models.py

```python
from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean,
    DateTime, Date, Time, ForeignKey, Index
)
from sqlalchemy.orm import relationship, DeclarativeBase
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customers"
    
    id = Column(Integer, primary_key=True)
    phone = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(100))
    email = Column(String(100))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    vehicles = relationship("Vehicle", back_populates="customer", lazy="selectin")
    appointments = relationship("Appointment", back_populates="customer", lazy="selectin")


class Vehicle(Base):
    __tablename__ = "vehicles"
    
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    make = Column(String(50), nullable=False)
    model = Column(String(50), nullable=False)
    year = Column(Integer)
    license_plate = Column(String(20))
    vin = Column(String(17))
    created_at = Column(DateTime, server_default=func.now())
    
    customer = relationship("Customer", back_populates="vehicles")


class AppointmentTypeModel(Base):
    __tablename__ = "appointment_types"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False)
    display_name = Column(String(100), nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    description = Column(Text)


class ServiceType(Base):
    __tablename__ = "service_types"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    estimated_duration_minutes = Column(Integer, nullable=False)
    estimated_price_min = Column(Float)
    estimated_price_max = Column(Float)


class Inventory(Base):
    __tablename__ = "inventory"
    
    id = Column(Integer, primary_key=True)
    make = Column(String(50), nullable=False)
    model = Column(String(50), nullable=False)
    year = Column(Integer, nullable=False)
    color = Column(String(30))
    price = Column(Float)
    is_new = Column(Boolean, default=True)
    is_available = Column(Boolean, default=True)
    stock_number = Column(String(20), unique=True)


class Appointment(Base):
    __tablename__ = "appointments"
    
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    appointment_type_id = Column(Integer, ForeignKey("appointment_types.id"), nullable=False)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"))
    inventory_id = Column(Integer, ForeignKey("inventory.id"))
    service_type_id = Column(Integer, ForeignKey("service_types.id"))
    
    scheduled_date = Column(Date, nullable=False)
    scheduled_time = Column(Time, nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    
    status = Column(String(20), default="scheduled", index=True)
    notes = Column(Text)
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    customer = relationship("Customer", back_populates="appointments")
    service_type = relationship("ServiceType", lazy="joined")
    inventory_vehicle = relationship("Inventory", lazy="joined")
    
    __table_args__ = (
        Index("idx_appointments_date", "scheduled_date"),
        Index("idx_appointments_customer", "customer_id"),
    )


class FAQ(Base):
    __tablename__ = "faq"
    
    id = Column(Integer, primary_key=True)
    category = Column(String(50), nullable=False, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    keywords = Column(Text)


class ConversationLog(Base):
    __tablename__ = "conversation_logs"
    
    id = Column(Integer, primary_key=True)
    session_id = Column(String(50), nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    agent_type = Column(String(50))
    tool_calls = Column(Text)
    created_at = Column(DateTime, server_default=func.now())


class EscalationRequest(Base):
    __tablename__ = "escalation_requests"
    
    id = Column(Integer, primary_key=True)
    session_id = Column(String(50), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    reason = Column(Text)
    status = Column(String(20), default="pending")
    human_agent_id = Column(String(50))
    created_at = Column(DateTime, server_default=func.now())
```

## 4.2 app/database/connection.py

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import create_engine
from contextlib import asynccontextmanager

from app.config import get_settings
from .models import Base

settings = get_settings()

# Async engine
async_engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    future=True
)

# Async session factory
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)


async def get_db() -> AsyncSession:
    """FastAPI dependency for database sessions."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context():
    """Context manager for database sessions."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


def init_db():
    """Initialize database with tables and seed data."""
    # Use sync engine for initialization
    sync_url = settings.database_url.replace("+aiosqlite", "")
    sync_engine = create_engine(sync_url, echo=settings.debug)
    
    # Create tables
    Base.metadata.create_all(bind=sync_engine)
    
    # Seed data
    from sqlalchemy.orm import Session
    with Session(sync_engine) as session:
        from .models import FAQ, AppointmentTypeModel, ServiceType, Inventory
        
        # Check if already seeded
        if session.query(FAQ).count() > 0:
            return
        
        # Appointment types
        session.add_all([
            AppointmentTypeModel(name="service", display_name="Service Appointment", 
                                duration_minutes=60, description="Maintenance and repairs"),
            AppointmentTypeModel(name="test_drive", display_name="Test Drive",
                                duration_minutes=30, description="Test drive a vehicle"),
        ])
        
        # Service types
        session.add_all([
            ServiceType(name="Oil Change", estimated_duration_minutes=30,
                       estimated_price_min=49.99, estimated_price_max=89.99),
            ServiceType(name="Tire Rotation", estimated_duration_minutes=30,
                       estimated_price_min=29.99, estimated_price_max=49.99),
            ServiceType(name="Brake Inspection", estimated_duration_minutes=45,
                       estimated_price_min=0, estimated_price_max=0),
            ServiceType(name="Brake Pad Replacement", estimated_duration_minutes=90,
                       estimated_price_min=150.00, estimated_price_max=300.00),
            ServiceType(name="Battery Replacement", estimated_duration_minutes=30,
                       estimated_price_min=100.00, estimated_price_max=200.00),
            ServiceType(name="General Inspection", estimated_duration_minutes=60,
                       estimated_price_min=49.99, estimated_price_max=99.99),
        ])
        
        # Inventory
        session.add_all([
            Inventory(make="Toyota", model="Camry", year=2025, color="Silver",
                     price=28999.00, is_new=True, stock_number="TC2025-001"),
            Inventory(make="Toyota", model="RAV4", year=2025, color="Blue",
                     price=34999.00, is_new=True, stock_number="TR2025-002"),
            Inventory(make="Honda", model="Civic", year=2024, color="Black",
                     price=24999.00, is_new=True, stock_number="HC2024-003"),
            Inventory(make="Honda", model="CR-V", year=2025, color="White",
                     price=32999.00, is_new=True, stock_number="HCR2025-004"),
            Inventory(make="Ford", model="Mustang", year=2024, color="Red",
                     price=42999.00, is_new=True, stock_number="FM2024-005"),
        ])
        
        # FAQ
        session.add_all([
            FAQ(category="hours", question="What are your opening hours?",
                answer="We are open Monday through Friday from 8 AM to 7 PM, Saturday from 9 AM to 5 PM, and closed on Sunday. Our service department opens at 7:30 AM on weekdays.",
                keywords="hours,open,close,time,when,schedule"),
            FAQ(category="hours", question="Is the service department open on weekends?",
                answer="Yes, our service department is open on Saturday from 9 AM to 4 PM. We are closed on Sunday.",
                keywords="service,weekend,saturday,sunday"),
            FAQ(category="location", question="Where are you located?",
                answer="We are located at 1234 Auto Drive, Springfield. We are right off Highway 101, next to the Springfield Mall. Free parking is available.",
                keywords="location,address,where,directions,find"),
            FAQ(category="financing", question="Do you offer financing?",
                answer="Yes, we offer competitive financing options through multiple lenders. We can work with all credit situations. Our finance team can help you find the best rate for your budget.",
                keywords="financing,loan,credit,payment,monthly,finance"),
            FAQ(category="services", question="What services do you offer?",
                answer="We offer a full range of services including oil changes, tire rotation, brake service, battery replacement, AC service, and general inspections. We service all makes and models.",
                keywords="services,offer,repair,maintenance,fix"),
            FAQ(category="services", question="How long does an oil change take?",
                answer="A standard oil change typically takes about 30 to 45 minutes. If you schedule an appointment, we can often complete it even faster.",
                keywords="oil,change,time,long,duration"),
            FAQ(category="general", question="Do you offer loaner vehicles?",
                answer="Yes, we offer complimentary loaner vehicles for service appointments expected to take more than 2 hours. Please request this when scheduling your appointment.",
                keywords="loaner,rental,car,borrow,vehicle"),
        ])
        
        session.commit()
        print("Database seeded successfully!")
```

---

**END OF PART 2**

Say "continue" to get Part 3: LangGraph Agents & Graph Definition
