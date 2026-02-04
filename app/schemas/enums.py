from enum import Enum


class AgentType(str, Enum):
    """Agent types in the system."""
    UNIFIED = "unified"     # Main agent handling all interactions
    RESPONSE = "response"   # Final response state (for compatibility)


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
    CUSTOMER_SERVICE_ESCALATION = "customer_service_escalation"
    SEND_EMAIL = "send_email"
    SCHEDULE_CALLBACK = "schedule_callback"


class EscalationType(str, Enum):
    """Types of escalation for human handoff."""
    SALES = "sales"
    CUSTOMER_SERVICE = "customer_service"


class NotificationPriority(str, Enum):
    """Notification priority levels."""
    LOW = "low"           # Deliver on next user turn
    HIGH = "high"         # Deliver at next pause
    INTERRUPT = "interrupt"  # Interrupt current speech


class HumanAgentStatus(str, Enum):
    """Human agent availability status for escalation tracking."""
    CHECKING = "checking"      # Initial state
    CALLING = "calling"        # Outbound call initiated
    RINGING = "ringing"        # Phone is ringing
    WAITING = "waiting"        # Call connected, waiting for human to confirm
    AVAILABLE = "available"    # Human confirmed availability
    UNAVAILABLE = "unavailable"  # Human not available (no-answer, busy, failed)
    CONNECTED = "connected"    # Human connected to customer


class MessageRole(str, Enum):
    """Conversation message roles."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"
