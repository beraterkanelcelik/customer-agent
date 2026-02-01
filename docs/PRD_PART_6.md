# Car Dealership Voice Agent - PRD Part 6 of 6
## FastAPI Routes & Frontend Dashboard

---

# SECTION 1: FASTAPI APPLICATION

## 1.1 app/main.py

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import structlog

from app.config import get_settings
from app.api.routes import router as api_router
from app.api.websocket import router as ws_router
from app.database.connection import init_db
from app.background.state_store import state_store
from app.background.worker import background_worker
from app.agents.graph import set_escalation_worker

settings = get_settings()
logger = structlog.get_logger()


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
    
    # Set up background worker
    set_escalation_worker(background_worker)
    
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
```

## 1.2 app/api/deps.py

```python
from typing import AsyncGenerator
from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.connection import get_db
from app.background.state_store import state_store
from app.services.conversation import conversation_service


async def get_database() -> AsyncGenerator[AsyncSession, None]:
    """Database session dependency."""
    async for session in get_db():
        yield session


async def get_conversation_service():
    """Conversation service dependency."""
    return conversation_service


async def get_state_store():
    """State store dependency."""
    return state_store
```

## 1.3 app/api/routes.py

```python
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from datetime import datetime
import uuid

from livekit import api as livekit_api

from app.config import get_settings
from app.api.deps import get_database, get_conversation_service
from app.services.conversation import ConversationService
from app.database.models import FAQ, Customer, Appointment, ServiceType, Inventory
from app.schemas.api import (
    HealthResponse, ChatRequest, ChatResponse,
    CreateSessionRequest, SessionResponse,
    VoiceTokenRequest, VoiceTokenResponse,
    FAQListResponse, FAQEntry,
    CustomerListResponse, AppointmentListResponse
)
from app.schemas.customer import CustomerResponse
from app.schemas.appointment import AppointmentResponse, ServiceTypeResponse, InventoryVehicleResponse

router = APIRouter()
settings = get_settings()


# ============================================
# Session Endpoints
# ============================================

@router.post("/sessions", response_model=SessionResponse)
async def create_session(
    request: CreateSessionRequest = None,
    service: ConversationService = Depends(get_conversation_service)
):
    """Create a new conversation session."""
    session_id = f"sess_{uuid.uuid4().hex[:12]}"
    
    phone = request.customer_phone if request else None
    state = await service.create_session(session_id, phone)
    
    return SessionResponse(
        session_id=session_id,
        created_at=state.created_at,
        turn_count=0,
        current_agent=state.current_agent.value,
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
        current_agent=state.current_agent.value,
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
    response = await service.process_message(
        session_id=request.session_id,
        user_message=request.message
    )
    
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
    
    return VoiceTokenResponse(
        token=jwt_token,
        livekit_url=settings.livekit_url.replace("ws://", "wss://").replace("localhost", settings.livekit_url.split("://")[1].split(":")[0]),
        session_id=request.session_id
    )


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
```

## 1.4 app/api/websocket.py

```python
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict, Set
import json
import asyncio

from app.background.state_store import state_store
from app.schemas.api import WSStateUpdate, WSTranscript, WSTaskUpdate, WSError

router = APIRouter()


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
        
        for websocket in connections:
            try:
                await websocket.send_json(message)
            except Exception as e:
                print(f"Error broadcasting to websocket: {e}")
    
    async def send_state_update(self, session_id: str):
        """Send current state to all connections."""
        state = await state_store.get_state(session_id)
        if not state:
            return
        
        update = WSStateUpdate(
            session_id=session_id,
            current_agent=state.current_agent.value,
            intent=state.detected_intent.value if state.detected_intent else None,
            customer=state.customer if state.customer.is_identified else None,
            booking_slots=state.booking_slots.model_dump() if state.booking_slots else None,
            pending_tasks=state.pending_tasks
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


# Global connection manager
manager = ConnectionManager()


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
        await manager.send_state_update(session_id)
        
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
                await websocket.send_json({"type": "heartbeat"})
                
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        await manager.disconnect(websocket, session_id)


# Export manager for use by other modules
def get_ws_manager() -> ConnectionManager:
    return manager
```

---

# SECTION 2: FRONTEND SETUP

## 2.1 frontend/package.json

```json
{
  "name": "dealership-dashboard",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "livekit-client": "^2.0.0",
    "@livekit/components-react": "^2.0.0",
    "lucide-react": "^0.300.0"
  },
  "devDependencies": {
    "@types/react": "^18.2.0",
    "@types/react-dom": "^18.2.0",
    "@vitejs/plugin-react": "^4.2.0",
    "autoprefixer": "^10.4.0",
    "postcss": "^8.4.0",
    "tailwindcss": "^3.4.0",
    "vite": "^5.0.0"
  }
}
```

## 2.2 frontend/vite.config.js

```javascript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173
  },
  define: {
    'process.env': {}
  }
})
```

## 2.3 frontend/tailwind.config.js

```javascript
/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
```

## 2.4 frontend/postcss.config.js

```javascript
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
```

## 2.5 frontend/index.html

```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/favicon.ico" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Springfield Auto - Voice Agent Dashboard</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
```

---

# SECTION 3: FRONTEND COMPONENTS

## 3.1 frontend/src/main.jsx

```jsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles/main.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
```

## 3.2 frontend/src/styles/main.css

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

body {
  @apply bg-gray-950 text-white;
}

/* Custom scrollbar */
::-webkit-scrollbar {
  width: 6px;
}

::-webkit-scrollbar-track {
  @apply bg-gray-800;
}

::-webkit-scrollbar-thumb {
  @apply bg-gray-600 rounded-full;
}

::-webkit-scrollbar-thumb:hover {
  @apply bg-gray-500;
}
```

## 3.3 frontend/src/App.jsx

```jsx
import React, { useState, useEffect, useCallback } from 'react'
import { Phone, PhoneOff, Mic, MicOff } from 'lucide-react'
import CallButton from './components/CallButton'
import Transcript from './components/Transcript'
import AgentState from './components/AgentState'
import CustomerInfo from './components/CustomerInfo'
import TaskMonitor from './components/TaskMonitor'
import BookingSlots from './components/BookingSlots'
import { useWebSocket } from './hooks/useWebSocket'
import { useLiveKit } from './hooks/useLiveKit'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000'
const LIVEKIT_URL = import.meta.env.VITE_LIVEKIT_URL || 'ws://localhost:7880'

export default function App() {
  const [sessionId, setSessionId] = useState(null)
  const [isCallActive, setIsCallActive] = useState(false)
  const [isMuted, setIsMuted] = useState(false)
  const [transcript, setTranscript] = useState([])
  const [agentState, setAgentState] = useState({
    currentAgent: 'router',
    intent: null,
    confidence: 0
  })
  const [customer, setCustomer] = useState(null)
  const [bookingSlots, setBookingSlots] = useState({})
  const [pendingTasks, setPendingTasks] = useState([])
  const [error, setError] = useState(null)

  // WebSocket for state updates
  const { sendMessage } = useWebSocket(
    sessionId ? `${WS_URL}/ws/${sessionId}` : null,
    {
      onMessage: (data) => {
        handleWSMessage(data)
      },
      onError: (err) => {
        console.error('WebSocket error:', err)
      }
    }
  )

  // LiveKit for voice
  const { connect, disconnect, toggleMute, isConnected } = useLiveKit()

  const handleWSMessage = useCallback((data) => {
    switch (data.type) {
      case 'state_update':
        setAgentState({
          currentAgent: data.current_agent,
          intent: data.intent,
          confidence: data.confidence || 0
        })
        if (data.customer) setCustomer(data.customer)
        if (data.booking_slots) setBookingSlots(data.booking_slots)
        if (data.pending_tasks) setPendingTasks(data.pending_tasks)
        break
      
      case 'transcript':
        setTranscript(prev => [...prev, {
          role: data.role,
          content: data.content,
          timestamp: new Date().toLocaleTimeString(),
          agentType: data.agent_type
        }])
        break
      
      case 'task_update':
        setPendingTasks(prev => {
          const updated = prev.filter(t => t.task_id !== data.task.task_id)
          return [...updated, data.task]
        })
        break
      
      case 'notification':
        // Handle notification (could show toast)
        console.log('Notification:', data.notification)
        break
    }
  }, [])

  const startCall = async () => {
    try {
      setError(null)
      
      // Create session
      const sessionRes = await fetch(`${API_URL}/api/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      })
      const sessionData = await sessionRes.json()
      setSessionId(sessionData.session_id)
      
      // Get LiveKit token
      const tokenRes = await fetch(`${API_URL}/api/voice/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionData.session_id })
      })
      const tokenData = await tokenRes.json()
      
      // Connect to LiveKit
      await connect(tokenData.livekit_url, tokenData.token)
      
      setIsCallActive(true)
      setTranscript([])
      
    } catch (err) {
      console.error('Failed to start call:', err)
      setError('Failed to start call. Please try again.')
    }
  }

  const endCall = async () => {
    try {
      await disconnect()
      
      if (sessionId) {
        await fetch(`${API_URL}/api/sessions/${sessionId}`, {
          method: 'DELETE'
        })
      }
      
      setIsCallActive(false)
      setSessionId(null)
      
    } catch (err) {
      console.error('Failed to end call:', err)
    }
  }

  const handleMuteToggle = () => {
    toggleMute()
    setIsMuted(!isMuted)
  }

  return (
    <div className="min-h-screen bg-gray-950">
      {/* Header */}
      <header className="bg-gray-900 border-b border-gray-800 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="text-3xl">🚗</div>
            <div>
              <h1 className="text-xl font-bold">Springfield Auto</h1>
              <p className="text-sm text-gray-400">Voice Agent Dashboard</p>
            </div>
          </div>
          
          <div className="flex items-center gap-4">
            {/* Call Status */}
            <div className={`flex items-center gap-2 px-4 py-2 rounded-full ${
              isCallActive 
                ? 'bg-green-900/50 text-green-300' 
                : 'bg-gray-800 text-gray-400'
            }`}>
              <div className={`w-2 h-2 rounded-full ${
                isCallActive ? 'bg-green-400 animate-pulse' : 'bg-gray-600'
              }`} />
              <span className="text-sm font-medium">
                {isCallActive ? 'Call Active' : 'Ready'}
              </span>
            </div>
            
            {/* Mute Button */}
            {isCallActive && (
              <button
                onClick={handleMuteToggle}
                className={`p-2 rounded-lg ${
                  isMuted ? 'bg-red-600' : 'bg-gray-700 hover:bg-gray-600'
                }`}
              >
                {isMuted ? <MicOff size={20} /> : <Mic size={20} />}
              </button>
            )}
            
            {/* Call Button */}
            <CallButton
              isActive={isCallActive}
              onStart={startCall}
              onEnd={endCall}
            />
          </div>
        </div>
      </header>

      {/* Error Banner */}
      {error && (
        <div className="bg-red-900/50 border-b border-red-800 px-6 py-3">
          <div className="max-w-7xl mx-auto text-red-300 text-sm">
            {error}
          </div>
        </div>
      )}

      {/* Main Content */}
      <main className="max-w-7xl mx-auto p-6">
        <div className="grid grid-cols-12 gap-6">
          
          {/* Left: Transcript */}
          <div className="col-span-5">
            <Transcript messages={transcript} isActive={isCallActive} />
          </div>
          
          {/* Middle: Agent State & Booking */}
          <div className="col-span-4 space-y-6">
            <AgentState state={agentState} />
            <BookingSlots slots={bookingSlots} />
          </div>
          
          {/* Right: Customer & Tasks */}
          <div className="col-span-3 space-y-6">
            <TaskMonitor tasks={pendingTasks} />
            <CustomerInfo customer={customer} />
          </div>
          
        </div>
      </main>

      {/* Session ID Footer */}
      {sessionId && (
        <footer className="fixed bottom-0 left-0 right-0 bg-gray-900 border-t border-gray-800 px-6 py-2">
          <div className="max-w-7xl mx-auto text-xs text-gray-500">
            Session: {sessionId}
          </div>
        </footer>
      )}
    </div>
  )
}
```

## 3.4 frontend/src/components/CallButton.jsx

```jsx
import React from 'react'
import { Phone, PhoneOff } from 'lucide-react'

export default function CallButton({ isActive, onStart, onEnd }) {
  return (
    <button
      onClick={isActive ? onEnd : onStart}
      className={`flex items-center gap-2 px-6 py-2.5 rounded-lg font-medium transition-all ${
        isActive
          ? 'bg-red-600 hover:bg-red-700 text-white'
          : 'bg-indigo-600 hover:bg-indigo-700 text-white'
      }`}
    >
      {isActive ? (
        <>
          <PhoneOff size={18} />
          End Call
        </>
      ) : (
        <>
          <Phone size={18} />
          Start Call
        </>
      )}
    </button>
  )
}
```

## 3.5 frontend/src/components/Transcript.jsx

```jsx
import React, { useRef, useEffect } from 'react'
import { MessageCircle } from 'lucide-react'

export default function Transcript({ messages, isActive }) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  return (
    <div className="bg-gray-900 rounded-xl overflow-hidden h-[500px] flex flex-col">
      {/* Header */}
      <div className="px-4 py-3 bg-gray-800 border-b border-gray-700 flex items-center gap-2">
        <MessageCircle size={18} className="text-indigo-400" />
        <h2 className="font-semibold">Live Transcript</h2>
        {isActive && (
          <span className="ml-auto text-xs text-green-400 flex items-center gap-1">
            <span className="w-1.5 h-1.5 bg-green-400 rounded-full animate-pulse" />
            Live
          </span>
        )}
      </div>
      
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 ? (
          <div className="text-center text-gray-500 py-12">
            <MessageCircle size={32} className="mx-auto mb-2 opacity-50" />
            <p className="text-sm">
              {isActive ? 'Waiting for conversation...' : 'Start a call to begin'}
            </p>
          </div>
        ) : (
          messages.map((msg, i) => (
            <div
              key={i}
              className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}
            >
              {/* Avatar */}
              <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm flex-shrink-0 ${
                msg.role === 'user' ? 'bg-blue-600' : 'bg-indigo-600'
              }`}>
                {msg.role === 'user' ? '👤' : '🤖'}
              </div>
              
              {/* Message */}
              <div className={`flex-1 ${msg.role === 'user' ? 'text-right' : ''}`}>
                <div className={`inline-block px-4 py-2 rounded-2xl max-w-[85%] ${
                  msg.role === 'user'
                    ? 'bg-blue-600 rounded-br-md'
                    : 'bg-gray-800 rounded-bl-md'
                }`}>
                  <p className="text-sm">{msg.content}</p>
                </div>
                <p className="text-xs text-gray-500 mt-1">
                  {msg.timestamp}
                  {msg.agentType && msg.role !== 'user' && (
                    <span className="ml-2 text-indigo-400">• {msg.agentType}</span>
                  )}
                </p>
              </div>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
```

## 3.6 frontend/src/components/AgentState.jsx

```jsx
import React from 'react'
import { Brain, ArrowRight } from 'lucide-react'

const AGENTS = {
  router: { name: 'Router', icon: '🔀', color: 'bg-purple-500' },
  faq: { name: 'FAQ', icon: '📚', color: 'bg-blue-500' },
  booking: { name: 'Booking', icon: '📅', color: 'bg-green-500' },
  escalation: { name: 'Escalation', icon: '👤', color: 'bg-orange-500' },
  response: { name: 'Response', icon: '💬', color: 'bg-teal-500' }
}

const INTENTS = {
  faq: 'FAQ Question',
  book_service: 'Book Service',
  book_test_drive: 'Book Test Drive',
  reschedule: 'Reschedule',
  cancel: 'Cancel',
  escalation: 'Human Request',
  greeting: 'Greeting',
  goodbye: 'Goodbye',
  general: 'General'
}

export default function AgentState({ state }) {
  const currentAgent = AGENTS[state.currentAgent] || AGENTS.router

  return (
    <div className="bg-gray-900 rounded-xl overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 bg-gray-800 border-b border-gray-700 flex items-center gap-2">
        <Brain size={18} className="text-purple-400" />
        <h2 className="font-semibold">Agent State</h2>
      </div>
      
      <div className="p-4 space-y-4">
        {/* Agent Pipeline */}
        <div className="flex items-center justify-between overflow-x-auto pb-2">
          {Object.entries(AGENTS).map(([key, agent], i) => (
            <React.Fragment key={key}>
              <div className={`flex flex-col items-center transition-all ${
                state.currentAgent === key ? 'scale-110' : 'opacity-40'
              }`}>
                <div className={`w-10 h-10 rounded-lg ${agent.color} flex items-center justify-center ${
                  state.currentAgent === key ? 'ring-2 ring-white' : ''
                }`}>
                  <span>{agent.icon}</span>
                </div>
                <span className="text-xs mt-1">{agent.name}</span>
              </div>
              {i < Object.keys(AGENTS).length - 1 && (
                <ArrowRight size={14} className="text-gray-600 flex-shrink-0" />
              )}
            </React.Fragment>
          ))}
        </div>
        
        {/* Intent */}
        <div className="bg-gray-800 rounded-lg p-3">
          <div className="text-xs text-gray-400 mb-1">Detected Intent</div>
          <div className="flex items-center gap-2">
            {state.intent ? (
              <>
                <span className="px-2 py-1 bg-indigo-600 rounded text-xs font-medium uppercase">
                  {state.intent}
                </span>
                <span className="text-sm text-gray-300">
                  {INTENTS[state.intent] || state.intent}
                </span>
              </>
            ) : (
              <span className="text-gray-500 text-sm">Waiting for input...</span>
            )}
          </div>
        </div>
        
        {/* Confidence */}
        {state.confidence > 0 && (
          <div className="bg-gray-800 rounded-lg p-3">
            <div className="text-xs text-gray-400 mb-2">Confidence</div>
            <div className="flex items-center gap-3">
              <div className="flex-1 h-2 bg-gray-700 rounded-full overflow-hidden">
                <div 
                  className="h-full bg-indigo-500 rounded-full transition-all"
                  style={{ width: `${state.confidence * 100}%` }}
                />
              </div>
              <span className="text-sm font-medium">
                {Math.round(state.confidence * 100)}%
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
```

## 3.7 frontend/src/components/BookingSlots.jsx

```jsx
import React from 'react'
import { Calendar, Check, Circle } from 'lucide-react'

const SLOT_LABELS = {
  appointment_type: 'Type',
  service_type: 'Service',
  vehicle_interest: 'Vehicle',
  preferred_date: 'Date',
  preferred_time: 'Time',
  customer_name: 'Name',
  customer_phone: 'Phone',
  customer_email: 'Email'
}

export default function BookingSlots({ slots }) {
  const hasAnySlot = Object.values(slots || {}).some(v => v !== null && v !== undefined)

  if (!hasAnySlot) {
    return (
      <div className="bg-gray-900 rounded-xl overflow-hidden">
        <div className="px-4 py-3 bg-gray-800 border-b border-gray-700 flex items-center gap-2">
          <Calendar size={18} className="text-green-400" />
          <h2 className="font-semibold">Booking Info</h2>
        </div>
        <div className="p-4 text-center text-gray-500 py-8">
          <Calendar size={28} className="mx-auto mb-2 opacity-50" />
          <p className="text-sm">No booking in progress</p>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-gray-900 rounded-xl overflow-hidden">
      <div className="px-4 py-3 bg-gray-800 border-b border-gray-700 flex items-center gap-2">
        <Calendar size={18} className="text-green-400" />
        <h2 className="font-semibold">Booking Info</h2>
      </div>
      
      <div className="p-4 space-y-2">
        {Object.entries(SLOT_LABELS).map(([key, label]) => {
          const value = slots[key]
          const hasValue = value !== null && value !== undefined
          
          return (
            <div 
              key={key}
              className="flex items-center justify-between py-2 border-b border-gray-800 last:border-0"
            >
              <span className="text-sm text-gray-400">{label}</span>
              {hasValue ? (
                <span className="text-sm font-medium text-green-400 flex items-center gap-1">
                  <Check size={14} />
                  {String(value)}
                </span>
              ) : (
                <span className="text-sm text-gray-600 flex items-center gap-1">
                  <Circle size={10} />
                  —
                </span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
```

## 3.8 frontend/src/components/TaskMonitor.jsx

```jsx
import React from 'react'
import { Zap, Check, Loader2, XCircle } from 'lucide-react'

const STATUS_CONFIG = {
  pending: { icon: Loader2, color: 'text-yellow-400', bg: 'bg-yellow-900/30' },
  running: { icon: Loader2, color: 'text-blue-400', bg: 'bg-blue-900/30', spin: true },
  completed: { icon: Check, color: 'text-green-400', bg: 'bg-green-900/30' },
  failed: { icon: XCircle, color: 'text-red-400', bg: 'bg-red-900/30' }
}

export default function TaskMonitor({ tasks }) {
  const activeTasks = tasks.filter(t => t.status !== 'completed' && t.status !== 'failed')
  const hasActive = activeTasks.length > 0

  return (
    <div className="bg-gray-900 rounded-xl overflow-hidden">
      <div className="px-4 py-3 bg-gray-800 border-b border-gray-700 flex items-center gap-2">
        <Zap size={18} className="text-yellow-400" />
        <h2 className="font-semibold">Background Tasks</h2>
        {hasActive && (
          <span className="ml-auto text-xs bg-yellow-600 px-2 py-0.5 rounded-full">
            {activeTasks.length} active
          </span>
        )}
      </div>
      
      <div className="p-4">
        {tasks.length === 0 ? (
          <div className="text-center text-gray-500 py-6">
            <Zap size={24} className="mx-auto mb-2 opacity-50" />
            <p className="text-sm">No active tasks</p>
          </div>
        ) : (
          <div className="space-y-3">
            {tasks.map(task => {
              const config = STATUS_CONFIG[task.status] || STATUS_CONFIG.pending
              const Icon = config.icon
              
              return (
                <div 
                  key={task.task_id}
                  className={`${config.bg} border border-gray-700 rounded-lg p-3`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <Icon 
                      size={16} 
                      className={`${config.color} ${config.spin ? 'animate-spin' : ''}`}
                    />
                    <span className="text-sm font-medium">
                      {task.task_type.replace('_', ' ')}
                    </span>
                  </div>
                  <div className="text-xs text-gray-400">
                    Status: {task.status}
                  </div>
                  {task.human_agent_name && (
                    <div className="text-xs text-green-400 mt-1">
                      Agent: {task.human_agent_name}
                    </div>
                  )}
                  {task.callback_scheduled && (
                    <div className="text-xs text-yellow-400 mt-1">
                      Callback: {task.callback_scheduled}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
```

## 3.9 frontend/src/components/CustomerInfo.jsx

```jsx
import React from 'react'
import { User, Phone, Mail, Car } from 'lucide-react'

export default function CustomerInfo({ customer }) {
  if (!customer || !customer.customer_id) {
    return (
      <div className="bg-gray-900 rounded-xl overflow-hidden">
        <div className="px-4 py-3 bg-gray-800 border-b border-gray-700 flex items-center gap-2">
          <User size={18} className="text-blue-400" />
          <h2 className="font-semibold">Customer</h2>
        </div>
        <div className="p-4 text-center text-gray-500 py-6">
          <User size={24} className="mx-auto mb-2 opacity-50" />
          <p className="text-sm">Not identified yet</p>
          <p className="text-xs mt-1">Waiting for phone number...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-gray-900 rounded-xl overflow-hidden">
      <div className="px-4 py-3 bg-gray-800 border-b border-gray-700 flex items-center gap-2">
        <User size={18} className="text-blue-400" />
        <h2 className="font-semibold">Customer</h2>
      </div>
      
      <div className="p-4 space-y-3">
        {/* Avatar & Name */}
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 bg-indigo-600 rounded-full flex items-center justify-center text-lg font-bold">
            {customer.name ? customer.name.charAt(0).toUpperCase() : '?'}
          </div>
          <div>
            <div className="font-medium">{customer.name || 'Unknown'}</div>
            <div className="text-xs text-gray-400">ID: {customer.customer_id}</div>
          </div>
        </div>
        
        {/* Contact Info */}
        <div className="space-y-2 pt-2 border-t border-gray-800">
          {customer.phone && (
            <div className="flex items-center gap-2 text-sm">
              <Phone size={14} className="text-gray-500" />
              <span>{customer.phone}</span>
            </div>
          )}
          {customer.email && (
            <div className="flex items-center gap-2 text-sm">
              <Mail size={14} className="text-gray-500" />
              <span>{customer.email}</span>
            </div>
          )}
        </div>
        
        {/* Vehicles */}
        {customer.vehicles && customer.vehicles.length > 0 && (
          <div className="pt-2 border-t border-gray-800">
            <div className="text-xs text-gray-400 mb-2">Vehicles</div>
            {customer.vehicles.map((v, i) => (
              <div key={i} className="flex items-center gap-2 text-sm">
                <Car size={14} className="text-gray-500" />
                <span>{v.year} {v.make} {v.model}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
```

---

# SECTION 4: FRONTEND HOOKS

## 4.1 frontend/src/hooks/useWebSocket.js

```javascript
import { useEffect, useRef, useState, useCallback } from 'react'

export function useWebSocket(url, options = {}) {
  const { onMessage, onError, onOpen, onClose } = options
  const wsRef = useRef(null)
  const [isConnected, setIsConnected] = useState(false)
  const reconnectTimeoutRef = useRef(null)

  const connect = useCallback(() => {
    if (!url) return

    try {
      wsRef.current = new WebSocket(url)
      
      wsRef.current.onopen = () => {
        setIsConnected(true)
        onOpen?.()
      }
      
      wsRef.current.onclose = () => {
        setIsConnected(false)
        onClose?.()
        
        // Reconnect after delay
        reconnectTimeoutRef.current = setTimeout(() => {
          connect()
        }, 3000)
      }
      
      wsRef.current.onerror = (error) => {
        onError?.(error)
      }
      
      wsRef.current.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          onMessage?.(data)
        } catch (e) {
          console.error('Failed to parse WS message:', e)
        }
      }
    } catch (error) {
      onError?.(error)
    }
  }, [url, onMessage, onError, onOpen, onClose])

  useEffect(() => {
    connect()
    
    return () => {
      clearTimeout(reconnectTimeoutRef.current)
      wsRef.current?.close()
    }
  }, [connect])

  const sendMessage = useCallback((data) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data))
    }
  }, [])

  return { isConnected, sendMessage }
}
```

## 4.2 frontend/src/hooks/useLiveKit.js

```javascript
import { useRef, useState, useCallback } from 'react'
import { Room, RoomEvent, Track } from 'livekit-client'

export function useLiveKit() {
  const roomRef = useRef(null)
  const [isConnected, setIsConnected] = useState(false)
  const [isMuted, setIsMuted] = useState(false)

  const connect = useCallback(async (url, token) => {
    try {
      const room = new Room()
      roomRef.current = room
      
      // Set up event handlers
      room.on(RoomEvent.Connected, () => {
        console.log('Connected to LiveKit room')
        setIsConnected(true)
      })
      
      room.on(RoomEvent.Disconnected, () => {
        console.log('Disconnected from LiveKit room')
        setIsConnected(false)
      })
      
      room.on(RoomEvent.TrackSubscribed, (track, publication, participant) => {
        if (track.kind === Track.Kind.Audio) {
          const audioElement = track.attach()
          document.body.appendChild(audioElement)
        }
      })
      
      // Connect
      await room.connect(url, token)
      
      // Enable microphone
      await room.localParticipant.setMicrophoneEnabled(true)
      
    } catch (error) {
      console.error('LiveKit connection error:', error)
      throw error
    }
  }, [])

  const disconnect = useCallback(async () => {
    if (roomRef.current) {
      await roomRef.current.disconnect()
      roomRef.current = null
    }
    setIsConnected(false)
  }, [])

  const toggleMute = useCallback(async () => {
    if (roomRef.current) {
      const newMuted = !isMuted
      await roomRef.current.localParticipant.setMicrophoneEnabled(!newMuted)
      setIsMuted(newMuted)
    }
  }, [isMuted])

  return {
    connect,
    disconnect,
    toggleMute,
    isConnected,
    isMuted
  }
}
```

---

# SECTION 5: FINAL CHECKLIST

## 5.1 Quick Start Commands

```bash
# 1. Clone and setup
git clone <repo>
cd car-dealership-voice-agent
cp .env.example .env
# Edit .env with your OPENAI_API_KEY

# 2. Build and start all services
docker-compose build
docker-compose up -d

# 3. Check logs
docker-compose logs -f app voice-worker

# 4. Open dashboard
open http://localhost:5173

# 5. Stop services
docker-compose down
```

## 5.2 Testing Checklist

| Test | Expected Result |
|------|-----------------|
| Health check | `curl localhost:8000/health` returns 200 |
| Create session | POST `/api/sessions` returns session_id |
| Chat API | POST `/api/chat` returns response |
| WebSocket | Connect to `/ws/{session_id}` receives updates |
| FAQ query | "What are your hours?" → Correct answer |
| Booking flow | Book oil change → All slots collected |
| Escalation | "Talk to human" → Background task starts |
| Voice call | Click Start → Audio works both ways |

## 5.3 Demo Scenarios

1. **FAQ Only**: Ask about hours, location, financing
2. **Service Booking**: "I need an oil change tomorrow"
3. **Test Drive**: "I want to test drive a Toyota"
4. **Reschedule**: "I need to change my appointment"
5. **Escalation**: "I want to speak to someone"
6. **Mixed**: Start with FAQ, then book appointment

---

# PRD COMPLETE! 🎉

## Summary of All 6 Parts

| Part | Contents |
|------|----------|
| **Part 1** | Project overview, Docker setup, all Dockerfiles |
| **Part 2** | Pydantic schemas, enums, database models |
| **Part 3** | LangGraph agents, graph definition |
| **Part 4** | Tools (FAQ, booking, customer), background tasks |
| **Part 5** | Voice worker (STT, TTS, LiveKit) |
| **Part 6** | FastAPI routes, WebSocket, React dashboard |

## Total Files Created

- Docker: 4 files
- Backend (app/): ~25 files
- Voice Worker: 6 files
- Frontend: ~15 files
- Tests: 4 files

## Key Architecture Decisions

1. **Multi-container Docker** - Separation of concerns
2. **LangGraph** - Multi-agent orchestration
3. **Pydantic everywhere** - Type safety and validation
4. **Async background tasks** - Non-blocking escalation
5. **Redis state store** - Shared state between processes
6. **WebSocket** - Real-time dashboard updates
7. **LiveKit** - Production-grade voice infrastructure

---

**Feed these 6 PRD files to Claude Code agent in order. Each part is self-contained and builds on the previous parts.**
