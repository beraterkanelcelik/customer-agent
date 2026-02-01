from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from datetime import datetime
import uuid

from livekit import api as livekit_api

from app.config import get_settings
from app.api.deps import get_database, get_conversation_service
from app.api.websocket import get_ws_manager
from app.services.conversation import ConversationService
from app.database.models import FAQ, Customer, Appointment, ServiceType, Inventory
from app.schemas.api import (
    HealthResponse, ChatRequest, ChatResponse,
    CreateSessionRequest, SessionResponse,
    VoiceTokenRequest, VoiceTokenResponse,
    FAQListResponse, FAQEntry,
    CustomerListResponse, AppointmentListResponse,
    SalesRespondRequest, SalesRespondResponse, SalesTokenRequest
)
from app.schemas.customer import CustomerResponse
from app.schemas.appointment import AppointmentResponse, ServiceTypeResponse, InventoryVehicleResponse

router = APIRouter()
settings = get_settings()


def get_enum_value(enum_or_str, default=None):
    """Safely get value from enum or return string as-is."""
    if enum_or_str is None:
        return default
    if hasattr(enum_or_str, 'value'):
        return enum_or_str.value
    return enum_or_str


# ============================================
# Session Endpoints
# ============================================

@router.post("/sessions", response_model=SessionResponse)
async def create_session(
    request: CreateSessionRequest = None,
    service: ConversationService = Depends(get_conversation_service)
):
    """Create a new conversation session."""
    # Use provided session_id or generate a new one
    if request and request.session_id:
        session_id = request.session_id
    else:
        session_id = f"sess_{uuid.uuid4().hex[:12]}"

    phone = request.customer_phone if request else None
    state = await service.create_session(session_id, phone)

    return SessionResponse(
        session_id=session_id,
        created_at=state.created_at,
        turn_count=0,
        current_agent=get_enum_value(state.current_agent, "router"),
        customer=state.customer if state.customer.is_identified else None,
        is_active=True
    )


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    service: ConversationService = Depends(get_conversation_service)
):
    """Get session information."""
    state = await service.get_session(session_id)

    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found"
        )

    return SessionResponse(
        session_id=session_id,
        created_at=state.created_at,
        turn_count=state.turn_count,
        current_agent=get_enum_value(state.current_agent, "router"),
        customer=state.customer if state.customer.is_identified else None,
        is_active=True
    )


@router.delete("/sessions/{session_id}")
async def end_session(
    session_id: str,
    service: ConversationService = Depends(get_conversation_service)
):
    """End and cleanup a session."""
    await service.end_session(session_id)
    return {"status": "ended", "session_id": session_id}


# ============================================
# Chat Endpoint
# ============================================

@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    service: ConversationService = Depends(get_conversation_service)
):
    """
    Process a chat message and return response.

    This is the main endpoint for conversation processing.
    """
    ws_manager = get_ws_manager()

    # Send user transcript to WebSocket
    await ws_manager.send_transcript(
        session_id=request.session_id,
        role="user",
        content=request.message
    )

    response = await service.process_message(
        session_id=request.session_id,
        user_message=request.message
    )

    # Send agent response transcript to WebSocket
    await ws_manager.send_transcript(
        session_id=request.session_id,
        role="assistant",
        content=response.response,
        agent_type=response.agent_type
    )

    # Send state update to WebSocket
    await ws_manager.send_state_update(request.session_id)

    return response


# ============================================
# Voice Token Endpoint
# ============================================

@router.post("/voice/token", response_model=VoiceTokenResponse)
async def get_voice_token(request: VoiceTokenRequest):
    """
    Generate a LiveKit token for voice session.

    The frontend uses this to connect to LiveKit room.
    """
    # Create LiveKit token
    token = livekit_api.AccessToken(
        settings.livekit_api_key,
        settings.livekit_api_secret
    )

    token.with_identity(f"user_{request.session_id}")
    token.with_name("Customer")

    # Grant permissions
    token.with_grants(livekit_api.VideoGrants(
        room_join=True,
        room=request.session_id,
        can_publish=True,
        can_subscribe=True
    ))

    jwt_token = token.to_jwt()

    # Create room and dispatch an agent to it
    try:
        lk_api = livekit_api.LiveKitAPI(
            settings.livekit_url,
            settings.livekit_api_key,
            settings.livekit_api_secret
        )
        # Create the room first
        await lk_api.room.create_room(
            livekit_api.CreateRoomRequest(
                name=request.session_id,
                empty_timeout=300,  # 5 minutes
            )
        )
        # Check if agent already dispatched
        dispatches = await lk_api.agent_dispatch.list_dispatch(
            livekit_api.ListAgentDispatchRequest(room=request.session_id)
        )
        if not dispatches.agent_dispatches:
            # Dispatch an agent to the room
            await lk_api.agent_dispatch.create_dispatch(
                livekit_api.CreateAgentDispatchRequest(
                    room=request.session_id,
                    agent_name="",  # Use default agent
                )
            )
            print(f"Agent dispatched to room: {request.session_id}")
        else:
            print(f"Agent already dispatched to room: {request.session_id}")
        await lk_api.aclose()
    except Exception as e:
        print(f"Room/Agent dispatch: {e}")

    # Return localhost URL for browser access (not internal docker hostname)
    return VoiceTokenResponse(
        token=jwt_token,
        livekit_url="ws://localhost:7880",
        session_id=request.session_id
    )


# ============================================
# Sales Endpoints
# ============================================

@router.post("/sales/token", response_model=VoiceTokenResponse)
async def get_sales_voice_token(request: SalesTokenRequest):
    """
    Generate a LiveKit token for sales to join a customer call.

    This allows sales staff to join the same room as the customer
    when they accept an escalation.
    """
    # Create LiveKit token for sales
    token = livekit_api.AccessToken(
        settings.livekit_api_key,
        settings.livekit_api_secret
    )

    token.with_identity(f"sales_{request.sales_id}")
    token.with_name(f"Sales ({request.sales_id})")

    # Grant permissions
    token.with_grants(livekit_api.VideoGrants(
        room_join=True,
        room=request.session_id,
        can_publish=True,
        can_subscribe=True
    ))

    jwt_token = token.to_jwt()

    return VoiceTokenResponse(
        token=jwt_token,
        livekit_url="ws://localhost:7880",
        session_id=request.session_id
    )


@router.post("/sales/respond", response_model=SalesRespondResponse)
async def sales_respond_to_call(request: SalesRespondRequest):
    """
    REST endpoint for sales to respond to incoming call.

    Alternative to WebSocket response - useful for testing.
    """
    from app.api.websocket import get_sales_manager

    sales_mgr = get_sales_manager()
    handled = sales_mgr.handle_sales_response(
        request.session_id,
        request.accepted,
        request.sales_id
    )

    if handled:
        action = "accepted" if request.accepted else "declined"
        return SalesRespondResponse(
            success=True,
            message=f"Call {action} successfully",
            session_id=request.session_id
        )
    else:
        return SalesRespondResponse(
            success=False,
            message="No pending escalation found for this session",
            session_id=request.session_id
        )


@router.get("/sales/pending")
async def get_pending_escalations():
    """Get list of pending escalation requests."""
    from app.api.websocket import get_sales_manager

    sales_mgr = get_sales_manager()
    pending = list(sales_mgr._pending_escalations.keys())

    return {
        "pending_calls": pending,
        "count": len(pending),
        "sales_online": len(sales_mgr.connections)
    }


# ============================================
# FAQ Endpoints
# ============================================

@router.get("/faq", response_model=FAQListResponse)
async def list_faq(
    category: Optional[str] = None,
    db: AsyncSession = Depends(get_database)
):
    """List all FAQ entries."""
    stmt = select(FAQ)
    if category:
        stmt = stmt.where(FAQ.category == category)

    result = await db.execute(stmt)
    faqs = result.scalars().all()

    return FAQListResponse(
        entries=[FAQEntry.model_validate(f) for f in faqs],
        total=len(faqs)
    )


# ============================================
# Service Endpoints
# ============================================

@router.get("/services", response_model=list[ServiceTypeResponse])
async def list_services(db: AsyncSession = Depends(get_database)):
    """List all available services."""
    result = await db.execute(select(ServiceType))
    services = result.scalars().all()
    return [ServiceTypeResponse.model_validate(s) for s in services]


# ============================================
# Inventory Endpoints
# ============================================

@router.get("/inventory", response_model=list[InventoryVehicleResponse])
async def list_inventory(
    make: Optional[str] = None,
    available_only: bool = True,
    db: AsyncSession = Depends(get_database)
):
    """List dealership inventory."""
    stmt = select(Inventory)

    if available_only:
        stmt = stmt.where(Inventory.is_available == True)
    if make:
        stmt = stmt.where(Inventory.make.ilike(f"%{make}%"))

    result = await db.execute(stmt)
    vehicles = result.scalars().all()

    return [InventoryVehicleResponse.model_validate(v) for v in vehicles]


# ============================================
# Customer Endpoints
# ============================================

@router.get("/customers/{phone}", response_model=CustomerResponse)
async def get_customer(
    phone: str,
    db: AsyncSession = Depends(get_database)
):
    """Get customer by phone number."""
    stmt = select(Customer).where(Customer.phone == phone)
    result = await db.execute(stmt)
    customer = result.scalar_one_or_none()

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer with phone {phone} not found"
        )

    return CustomerResponse.model_validate(customer)


# ============================================
# Appointment Endpoints
# ============================================

# ============================================
# Latency Tracking Endpoint
# ============================================

@router.post("/latency")
async def report_latency(
    data: dict
):
    """
    Receive latency metrics from voice worker.
    Forwards to frontend via WebSocket.
    """
    ws_manager = get_ws_manager()

    session_id = data.get("session_id")
    latency = data.get("latency", {})

    if session_id and latency:
        await ws_manager.send_message(session_id, {
            "type": "latency",
            "data": {
                "stt_ms": latency.get("stt_ms", 0),
                "llm_ms": latency.get("llm_ms", 0),
                "tts_ms": latency.get("tts_ms", 0),
                "total_ms": latency.get("total_ms", 0),
                "audio_duration_ms": latency.get("audio_duration", 0),
                "user_message": data.get("user_message", ""),
                "agent_response": data.get("agent_response", "")
            }
        })

    return {"status": "ok"}


@router.get("/appointments", response_model=AppointmentListResponse)
async def list_appointments(
    customer_id: Optional[int] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_database)
):
    """List appointments with optional filters."""
    stmt = select(Appointment)

    if customer_id:
        stmt = stmt.where(Appointment.customer_id == customer_id)
    if status:
        stmt = stmt.where(Appointment.status == status)

    stmt = stmt.order_by(Appointment.scheduled_date.desc())

    result = await db.execute(stmt)
    appointments = result.scalars().all()

    return AppointmentListResponse(
        appointments=[AppointmentResponse.model_validate(a) for a in appointments],
        total=len(appointments)
    )
