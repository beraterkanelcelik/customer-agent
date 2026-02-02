from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict, Set, Optional, Callable, Awaitable
import json
import asyncio
from datetime import datetime

from app.background.state_store import state_store
from app.schemas.api import WSStateUpdate, WSTranscript, WSTaskUpdate, WSError


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")

router = APIRouter()


# ============================================
# Sales Dashboard Connection Manager
# ============================================

class SalesConnectionManager:
    """Manages WebSocket connections for sales dashboard."""

    def __init__(self):
        self.connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()
        # Pending escalation requests waiting for sales response
        self._pending_escalations: Dict[str, asyncio.Future] = {}

    async def connect(self, websocket: WebSocket):
        """Accept and register a sales connection."""
        await websocket.accept()
        async with self._lock:
            self.connections.add(websocket)
        print(f"Sales dashboard connected. Total connections: {len(self.connections)}")

    async def disconnect(self, websocket: WebSocket):
        """Remove a sales connection."""
        async with self._lock:
            self.connections.discard(websocket)
        print(f"Sales dashboard disconnected. Total connections: {len(self.connections)}")

    async def broadcast(self, message: dict):
        """Broadcast message to all sales connections."""
        async with self._lock:
            connections = self.connections.copy()

        json_message = json.loads(json.dumps(message, default=json_serial))

        for websocket in connections:
            try:
                await websocket.send_json(json_message)
            except Exception as e:
                print(f"Error broadcasting to sales websocket: {e}")

    async def ring_sales(
        self,
        session_id: str,
        customer_name: Optional[str],
        customer_phone: Optional[str],
        reason: Optional[str],
        timeout: int = 30
    ) -> dict:
        """
        Ring sales dashboard and wait for response.

        Returns:
            {"accepted": True, "sales_id": "..."} if sales accepts
            {"accepted": False, "reason": "timeout|declined|no_sales"} otherwise
        """
        # Check if any sales are connected
        if not self.connections:
            print("No sales dashboard connected")
            return {"accepted": False, "reason": "no_sales_online"}

        # Create future for this escalation
        future = asyncio.get_event_loop().create_future()
        self._pending_escalations[session_id] = future

        # Send ring to all sales dashboards
        await self.broadcast({
            "type": "incoming_call",
            "session_id": session_id,
            "customer_name": customer_name or "Unknown",
            "customer_phone": customer_phone or "Unknown",
            "reason": reason or "Customer requested human assistance",
            "timestamp": datetime.utcnow().isoformat()
        })

        try:
            # Wait for response with timeout
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            # Send timeout notification to sales
            await self.broadcast({
                "type": "call_timeout",
                "session_id": session_id
            })
            return {"accepted": False, "reason": "timeout"}
        finally:
            # Cleanup
            self._pending_escalations.pop(session_id, None)

    def handle_sales_response(self, session_id: str, accepted: bool, sales_id: str = None):
        """Handle response from sales dashboard."""
        future = self._pending_escalations.get(session_id)
        if future and not future.done():
            if accepted:
                future.set_result({"accepted": True, "sales_id": sales_id or "sales_001"})
            else:
                future.set_result({"accepted": False, "reason": "declined"})
            return True
        return False

    def has_pending_escalation(self, session_id: str) -> bool:
        """Check if there's a pending escalation for this session."""
        return session_id in self._pending_escalations


# Global sales manager
sales_manager = SalesConnectionManager()


class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""

    def __init__(self):
        # session_id -> set of websocket connections
        self.connections: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, session_id: str):
        """Accept and register a connection."""
        await websocket.accept()

        async with self._lock:
            if session_id not in self.connections:
                self.connections[session_id] = set()
            self.connections[session_id].add(websocket)

        print(f"WebSocket connected for session: {session_id}")

    async def disconnect(self, websocket: WebSocket, session_id: str):
        """Remove a connection."""
        async with self._lock:
            if session_id in self.connections:
                self.connections[session_id].discard(websocket)
                if not self.connections[session_id]:
                    del self.connections[session_id]

        print(f"WebSocket disconnected for session: {session_id}")

    async def broadcast(self, session_id: str, message: dict):
        """Broadcast message to all connections for a session."""
        async with self._lock:
            connections = self.connections.get(session_id, set()).copy()

        # Serialize with datetime support
        json_message = json.loads(json.dumps(message, default=json_serial))

        for websocket in connections:
            try:
                await websocket.send_json(json_message)
            except Exception as e:
                print(f"Error broadcasting to websocket: {e}")

    async def send_state_update(self, session_id: str):
        """Send current state to all connections."""
        state = await state_store.get_state(session_id)
        if not state:
            return

        # Handle both enum and string values for current_agent
        current_agent = state.current_agent
        if hasattr(current_agent, 'value'):
            current_agent = current_agent.value

        # Handle both enum and string values for detected_intent
        intent = None
        if state.detected_intent:
            intent = state.detected_intent
            if hasattr(intent, 'value'):
                intent = intent.value

        # Handle human_agent_status enum
        human_agent_status = None
        if state.human_agent_status:
            human_agent_status = state.human_agent_status
            if hasattr(human_agent_status, 'value'):
                human_agent_status = human_agent_status.value

        update = WSStateUpdate(
            session_id=session_id,
            current_agent=current_agent,
            intent=intent,
            confidence=state.confidence,
            escalation_in_progress=state.escalation_in_progress,
            human_agent_status=human_agent_status,
            customer=state.customer if state.customer and state.customer.is_identified else None,
            booking_slots=state.booking_slots.model_dump() if state.booking_slots else None,
            confirmed_appointment=state.confirmed_appointment.model_dump() if state.confirmed_appointment else None,
            pending_tasks=state.pending_tasks
        )

        await self.broadcast(session_id, update.model_dump())

    async def send_state_update_direct(
        self,
        session_id: str,
        current_agent: str = None,
        intent: str = None,
        confidence: float = 0,
        customer = None,
        booking_slots: dict = None,
        confirmed_appointment: dict = None,
        pending_tasks: list = None,
        escalation_in_progress: bool = False,
        human_agent_status: str = None
    ):
        """
        Send state update directly from response data without re-reading from store.
        This ensures real-time updates are immediate and accurate.
        """
        # Handle customer - check if it's identified
        customer_data = None
        if customer:
            if hasattr(customer, 'is_identified'):
                if customer.is_identified:
                    customer_data = customer.model_dump() if hasattr(customer, 'model_dump') else customer
            elif isinstance(customer, dict) and customer.get('is_identified'):
                customer_data = customer

        update = WSStateUpdate(
            session_id=session_id,
            current_agent=current_agent or "unified",
            intent=intent,
            confidence=confidence,
            escalation_in_progress=escalation_in_progress,
            human_agent_status=human_agent_status,
            customer=customer_data,
            booking_slots=booking_slots,
            confirmed_appointment=confirmed_appointment,
            pending_tasks=pending_tasks or []
        )

        await self.broadcast(session_id, update.model_dump())

    async def send_transcript(self, session_id: str, role: str, content: str, agent_type: str = None):
        """Send transcript update."""
        message = WSTranscript(
            session_id=session_id,
            role=role,
            content=content,
            agent_type=agent_type
        )
        await self.broadcast(session_id, message.model_dump())

    async def send_message(self, session_id: str, message: dict):
        """Send an arbitrary message to the session."""
        await self.broadcast(session_id, message)

    async def send_end_call(self, session_id: str, farewell_message: str):
        """Send end call signal to voice worker."""
        await self.broadcast(session_id, {
            "type": "end_call",
            "farewell_message": farewell_message
        })

    async def broadcast_availability_update(self, slot_date: str, slot_time: str, appointment_type: str, is_available: bool):
        """
        Broadcast availability update to all connected sessions.

        This is called when a slot is booked or cancelled.
        """
        message = {
            "type": "availability_update",
            "slot_date": slot_date,
            "slot_time": slot_time,
            "appointment_type": appointment_type,
            "is_available": is_available
        }
        # Broadcast to all sessions
        async with self._lock:
            all_sessions = list(self.connections.keys())

        for session_id in all_sessions:
            await self.broadcast(session_id, message)

    async def send_human_joined(self, session_id: str, human_id: str, delay: float = 10.0):
        """
        Signal voice worker that a human has joined the conversation.

        This triggers the agent to enter idle mode after the specified delay,
        allowing the current message to be heard before going silent.
        """
        await self.broadcast(session_id, {
            "type": "human_joined",
            "human_id": human_id,
            "delay": delay
        })
        print(f"Sent human_joined signal for session {session_id}, human: {human_id}")

    async def send_human_left(self, session_id: str, human_id: Optional[str] = None):
        """
        Signal voice worker that a human has left the conversation.

        If human_id is None, all humans are considered to have left.
        This triggers the agent to exit idle mode and resume normal operation.
        """
        await self.broadcast(session_id, {
            "type": "human_left",
            "human_id": human_id
        })
        print(f"Sent human_left signal for session {session_id}, human: {human_id}")


# Global connection manager
manager = ConnectionManager()


# Export manager for use by other modules
def get_ws_manager() -> ConnectionManager:
    return manager


def get_sales_manager() -> SalesConnectionManager:
    return sales_manager


# ============================================
# Sales Dashboard WebSocket Endpoint
# ============================================
# IMPORTANT: This route MUST be defined BEFORE the generic /ws/{session_id} route
# to prevent the dynamic route from capturing /ws/sales requests

@router.websocket("/ws/sales")
async def sales_websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for sales dashboard.

    Sales staff connect here to receive incoming call notifications
    and accept/decline escalation requests.
    """
    await sales_manager.connect(websocket)

    try:
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=30.0
                )

                message = json.loads(data)

                # Handle different message types
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})

                elif message.get("type") == "respond_to_call":
                    # Sales responding to incoming call
                    session_id = message.get("session_id")
                    accepted = message.get("accepted", False)
                    sales_id = message.get("sales_id", "sales_001")

                    handled = sales_manager.handle_sales_response(
                        session_id, accepted, sales_id
                    )

                    await websocket.send_json({
                        "type": "response_acknowledged",
                        "session_id": session_id,
                        "handled": handled
                    })

                elif message.get("type") == "get_status":
                    # Return current pending escalations
                    pending = list(sales_manager._pending_escalations.keys())
                    await websocket.send_json({
                        "type": "status",
                        "pending_calls": pending,
                        "connected_sales": len(sales_manager.connections)
                    })

            except asyncio.TimeoutError:
                # Send heartbeat
                try:
                    await websocket.send_json({"type": "heartbeat"})
                except Exception:
                    break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"Sales WebSocket error: {e}")
    finally:
        await sales_manager.disconnect(websocket)


# ============================================
# Session WebSocket Endpoint
# ============================================

@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time dashboard updates.

    The frontend connects here to receive:
    - State updates (agent changes, slot collection)
    - Transcript updates (user/agent messages)
    - Task updates (background task progress)
    - Notifications
    """
    await manager.connect(websocket, session_id)

    try:
        # Send initial state
        try:
            await manager.send_state_update(session_id)
        except Exception as e:
            print(f"Error sending initial state: {e}")

        # Keep connection alive and handle incoming messages
        while True:
            try:
                # Receive messages (heartbeat, commands, etc.)
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=30.0
                )

                message = json.loads(data)

                # Handle different message types
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})

                elif message.get("type") == "get_state":
                    await manager.send_state_update(session_id)

            except asyncio.TimeoutError:
                # Send heartbeat
                try:
                    await websocket.send_json({"type": "heartbeat"})
                except Exception as e:
                    print(f"Error sending heartbeat: {e}")
                    break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        await manager.disconnect(websocket, session_id)
