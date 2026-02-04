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
    message: Optional[str] = None  # Optional - agent generates message from data
    data: Optional[Dict[str, Any]] = None  # Raw result data for agent context
    priority: NotificationPriority
    delivered: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True
