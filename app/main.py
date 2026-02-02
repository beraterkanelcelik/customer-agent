from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import structlog

from app.config import get_settings
from app.logging_config import setup_logging
from app.api.routes import router as api_router
from app.api.websocket import router as ws_router, get_ws_manager
from app.database.connection import init_db
from app.background.state_store import state_store
from app.background.worker import background_worker
# Note: Escalation is now handled via request_human_agent tool which imports background_worker directly
from app.schemas.task import Notification, BackgroundTask

settings = get_settings()

# Configure standard library logging to work with our custom loggers
setup_logging(settings.log_level)

logger = structlog.get_logger()


async def notification_callback(session_id: str, notification: Notification):
    """Push high-priority notifications to connected clients via WebSocket."""
    ws_manager = get_ws_manager()
    await ws_manager.broadcast(session_id, {
        "type": "notification",
        "session_id": session_id,
        "notification_id": notification.notification_id,
        "message": notification.message,
        "priority": notification.priority.value if hasattr(notification.priority, 'value') else notification.priority,
        "task_id": notification.task_id
    })

    # Mark notification as delivered so it won't be re-delivered on next turn
    await state_store.mark_notification_delivered(session_id, notification.notification_id)

    logger.info(f"Pushed notification to session {session_id}: {notification.message[:50]}...")


async def task_update_callback(session_id: str, task: BackgroundTask):
    """Push task status updates to connected clients via WebSocket."""
    ws_manager = get_ws_manager()

    # Serialize task status enum
    status = task.status.value if hasattr(task.status, 'value') else task.status
    task_type = task.task_type.value if hasattr(task.task_type, 'value') else task.task_type

    await ws_manager.broadcast(session_id, {
        "type": "task_update",
        "session_id": session_id,
        "task": {
            "task_id": task.task_id,
            "task_type": task_type,
            "status": status,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "human_available": task.human_available,
            "human_agent_name": task.human_agent_name,
            "callback_scheduled": task.callback_scheduled
        }
    })
    logger.info(f"Pushed task update to session {session_id}: {task.task_id} -> {status}")

    # For escalation tasks, also send state_update with human_agent_status
    if task_type == "human_escalation" and status == "completed":
        human_agent_status = "connected" if task.human_available else "unavailable"
        escalation_in_progress = task.human_available  # Only stay in progress if connected

        await ws_manager.broadcast(session_id, {
            "type": "state_update",
            "session_id": session_id,
            "current_agent": "unified",
            "escalation_in_progress": escalation_in_progress,
            "human_agent_status": human_agent_status
        })
        logger.info(f"Pushed escalation state update: {human_agent_status}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting Car Dealership Voice Agent API...")

    # Initialize database
    logger.info("Initializing database...")
    init_db()

    # Connect state store
    logger.info("Connecting to state store...")
    await state_store.connect()

    # Background worker is imported directly by escalation_tools.py
    # No need to wire it up here anymore

    # Set up callbacks for real-time push
    background_worker.set_notification_callback(notification_callback)
    background_worker.set_task_update_callback(task_update_callback)
    logger.info("Background worker callbacks configured")

    logger.info("API startup complete!")

    yield

    # Shutdown
    logger.info("Shutting down...")
    await state_store.disconnect()
    logger.info("Shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Car Dealership Voice Agent",
    description="CARA8-style voice agent for car dealerships",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(api_router, prefix="/api")
app.include_router(ws_router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "car-dealership-voice-agent",
        "version": "1.0.0"
    }
