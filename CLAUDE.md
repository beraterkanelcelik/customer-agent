# CLAUDE.md - AI Agent Development Guide

This document serves as your guide to the Car Dealership Voice Agent (Customer Agent) project. Read this before making any changes.

---

## Quick Start

```bash
# 1. Setup environment
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY

# 2. Build and start all services
docker-compose up -d --build

# 3. Check health
curl http://localhost:8000/health

# 4. Open dashboard
# Navigate to http://localhost:5173
```

---

## Project Overview

A real-time voice customer service agent for car dealerships featuring:
- **Unified LangGraph agent** (single agent handles FAQ, booking, escalation)
- **Async background tasks** (human escalation doesn't block conversation)
- **Voice via LiveKit** + Faster-Whisper (STT) + Kokoro-82M (TTS)
- **React dashboard** showing real-time agent state
- **SQLite database** with customers, appointments, FAQ

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| **Backend** | FastAPI + LangGraph + SQLAlchemy (async) |
| **LLM** | OpenAI GPT-4o-mini (configurable) |
| **Voice STT** | Faster-Whisper (local, GPU-accelerated) |
| **Voice TTS** | Kokoro-82M (local GPU) |
| **Voice Infrastructure** | LiveKit (WebRTC) |
| **State Store** | Redis (with in-memory fallback) |
| **Database** | SQLite (async via aiosqlite) |
| **Frontend** | React 18 + Vite + TailwindCSS |
| **Containerization** | Docker Compose (5 services) |

---

## Directory Structure

```
customer-agent/
├── app/                      # FastAPI backend
│   ├── agents/               # LangGraph agents
│   │   ├── graph.py          # Main state graph definition
│   │   └── unified_agent.py  # Single agent with all capabilities
│   ├── api/
│   │   ├── routes.py         # HTTP endpoints
│   │   └── websocket.py      # Real-time updates
│   ├── background/
│   │   ├── state_store.py    # Redis/memory state
│   │   └── worker.py         # Async tasks
│   ├── database/
│   │   ├── models.py         # SQLAlchemy models
│   │   └── connection.py     # DB setup & seed
│   ├── schemas/              # Pydantic models
│   │   ├── state.py          # ConversationState (LangGraph)
│   │   ├── enums.py          # AgentType, IntentType, etc.
│   │   ├── api.py            # Request/Response schemas
│   │   ├── appointment.py    # Appointment schemas
│   │   ├── customer.py       # Customer schemas
│   │   └── task.py           # Background task schemas
│   ├── services/
│   │   └── conversation.py   # High-level conversation API
│   └── tools/                # LangChain tools (all with Pydantic schemas)
│       ├── faq_tools.py
│       ├── customer_tools.py
│       ├── booking_tools.py
│       ├── slot_tools.py
│       └── call_tools.py
├── voice_worker/             # Voice processing service
│   ├── agent.py              # LiveKit voice agent
│   ├── stt.py                # Faster-Whisper wrapper
│   ├── tts_kokoro.py         # Kokoro TTS wrapper
│   ├── config.py             # Voice worker settings
│   └── main.py               # Entrypoint
├── frontend/                 # React dashboard
│   ├── src/
│   │   ├── App.jsx
│   │   ├── SalesDashboard.jsx
│   │   ├── components/       # AgentState, BookingSlots, CallButton,
│   │   │                     # CustomerInfo, TaskMonitor, Transcript
│   │   └── hooks/            # useWebSocket, useLiveKit
│   ├── Dockerfile
│   └── nginx.conf
├── docker/
│   ├── Dockerfile.app
│   ├── Dockerfile.voice
│   └── entrypoint.sh
├── data/                     # SQLite DB (generated)
├── models/                   # Whisper/Piper/Kokoro models
├── logs/                     # Runtime logs (generated)
├── docs/                     # PRD documentation
│   ├── AGENT.md              # Agent-specific documentation
│   └── PRD_PART_*.md         # Product Requirements (6 parts)
└── architecture.md           # Detailed architecture document
```

---

## Key Files to Know

| File | Purpose |
|------|---------|
| `app/agents/graph.py` | LangGraph workflow definition (simple 2-node flow) |
| `app/agents/unified_agent.py` | Single agent with all tools - the heart of the AI |
| `app/schemas/state.py` | ConversationState - all state flows through this |
| `app/background/state_store.py` | Redis/memory state management |
| `voice_worker/agent.py` | LiveKit voice handling, VAD, barge-in |
| `voice_worker/config.py` | Voice settings (VAD thresholds, sample rates) |
| `app/config.py` | All configuration via Pydantic settings |
| `docker-compose.yml` | All 5 services orchestration |

---

## AI/ML Components Explained

### 1. LangGraph Unified Agent Workflow

The conversation flows through a simple graph:

```
check_notifications -> unified_agent -> END
```

**Nodes:**
- `check_notifications`: Processes async background task results (escalation callbacks)
- `unified_agent`: Single agent that handles ALL interactions (FAQ, booking, escalation, greetings)

**Why Single Agent?**
- No routing issues (can't lose context mid-booking)
- Simpler state management
- More natural conversation flow
- LLM handles mixed intents (e.g., "thanks, my name is John")

**State Management:**
- Uses `ConversationState` (Pydantic model) as graph state
- `messages` field uses LangGraph's `add_messages` reducer for proper deduplication
- State is persisted to Redis between turns

### 2. Unified Agent

Location: `app/agents/unified_agent.py`

The unified agent has access to ALL tools and handles every type of request:

**Capabilities:**
- Answer FAQ questions (hours, location, financing, services)
- Book test drives and service appointments (slot-filling)
- Reschedule or cancel existing appointments
- Handle human escalation requests (spawns background task)
- Greetings and goodbyes

**Available Tools:**

| Tool | Schema | Purpose |
|------|--------|---------|
| `search_faq` | `SearchFAQInput` | Search FAQ database |
| `list_services` | - | List services with pricing |
| `update_booking_info` | `BookingInfoInput` | Save collected slot information |
| `get_customer` | `GetCustomerInput` | Customer lookup by phone |
| `create_customer` | `CreateCustomerInput` | Create new customer record |
| `check_availability` | `CheckAvailabilityInput` | Check available time slots |
| `book_appointment` | `BookAppointmentInput` | Book the appointment |
| `reschedule_appointment` | `RescheduleInput` | Change appointment date/time |
| `cancel_appointment` | `CancelInput` | Cancel an appointment |
| `get_customer_appointments` | `GetAppointmentsInput` | List customer's bookings |
| `list_inventory` | `ListInventoryInput` | Show vehicles for test drive |
| `set_customer_identified` | `SetCustomerInput` | Mark customer as verified |
| `get_todays_date` | - | Date reference helper |
| `end_call` | `EndCallInput` | End voice call gracefully |

**Context Injection:**
The agent receives full context on every turn:
- Customer identification status
- Booking progress (what's collected, what's still needed)
- Escalation status
- Recent conversation summary

This ensures the agent always knows where it is in the conversation and what to do next.

### 3. Background Tasks (Escalation)

Location: `app/background/worker.py`

When user requests human assistance:
1. UnifiedAgent detects escalation request and spawns async task
2. Task runs 5-25 seconds (simulating availability check)
3. Result creates `Notification` in state
4. Next turn, `check_notifications` node delivers message
5. Voice worker also listens via WebSocket for immediate delivery

---

## Voice Processing Pipeline

### Full Flow (Speech -> Response -> Speech)

```
1. User speaks into microphone
          │
          ▼
2. Browser captures audio via WebRTC
          │
          ▼
3. LiveKit streams audio to voice-worker
          │
          ▼
4. VAD detects speech start/end
   (energy-based, ~50ms frames)
          │
          ▼
5. Audio buffered until silence detected
   (min_silence_frames = 60 = ~1.2s)
          │
          ▼
6. STT transcription (Faster-Whisper)
   - Resamples 48kHz -> 16kHz
   - Returns text
          │
          ▼
7. HTTP POST to /api/chat
   - LangGraph processes message
   - Returns response text
          │
          ▼
8. TTS synthesis (Kokoro)
   - Returns WAV audio
   - Sample rate: 24kHz
          │
          ▼
9. Audio resampled to 48kHz
          │
          ▼
10. Streamed to LiveKit in 20ms frames
          │
          ▼
11. User hears response
```

### VAD Configuration

Key settings in `voice_worker/config.py`:
- `vad_threshold = 0.012`: Energy threshold for speech detection
- `min_speech_frames = 5`: Frames needed to confirm speech start
- `min_silence_frames = 60`: Frames of silence to end utterance (~1.2s)
- `barge_in_frames = 8`: Frames needed to trigger barge-in (~160ms)

### Barge-In Support

The voice agent supports user interruption:
- While speaking, still monitors audio energy
- If user speaks for `barge_in_frames` (8 frames = ~160ms)
- Sets `_interrupt_speaking = True`
- TTS playback loop breaks early
- User's speech is buffered and processed

### Latency Budget

| Stage | Target | Notes |
|-------|--------|-------|
| VAD | <50ms | Energy-based detection |
| STT | <500ms | Faster-Whisper base/small |
| LangGraph | <2000ms | Includes LLM API calls |
| TTS | <300ms | Kokoro (local GPU) |
| **Total** | **<3s** | Acceptable for voice |

---

## State Management Architecture

### Current Design

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Browser   │────▶│   FastAPI   │────▶│    Redis    │
│  (Frontend) │     │   (app)     │     │  (state)    │
└─────────────┘     └─────────────┘     └─────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │ LangGraph   │
                    │  (agents)   │
                    └─────────────┘
```

### ConversationState Structure

```python
class ConversationState(BaseModel):
    # Core identity
    session_id: str
    messages: List[BaseMessage]  # LangGraph add_messages reducer

    # Agent routing
    current_agent: AgentType
    detected_intent: Optional[IntentType]
    confidence: float  # Intent classification confidence

    # Customer & booking context
    customer: CustomerContext
    booking_slots: BookingSlots
    pending_confirmation: Optional[Dict[str, Any]]

    # Background task management
    pending_tasks: List[BackgroundTask]
    notifications_queue: List[Notification]
    escalation_in_progress: bool
    human_agent_status: Optional[HumanAgentStatus]

    # Flow control flags
    should_respond: bool
    needs_slot_filling: bool
    waiting_for_background: bool
    prepend_message: Optional[str]  # Notification to prepend

    # Metadata
    turn_count: int
    created_at: datetime
    last_updated: datetime
    version: int  # Optimistic locking
```

### State Persistence Flow

1. Request arrives at `/api/chat`
2. `state_store.get_state(session_id)` fetches from Redis
3. State deserialized (messages converted back to LangChain objects)
4. LangGraph processes with state
5. Updated state saved via `state_store.set_state()`

### Known Issues & Improvements

**Issue 1: Message Serialization**
- LangChain messages serialize as `{"type": "human", "content": "..."}`
- Custom `deserialize_messages()` function handles reconstruction
- Works but adds complexity

**Issue 2: Dual State Management**
- LangGraph has its own checkpointer system
- We use external Redis instead (removed MemorySaver)
- This works but means we rebuild state each turn

**Potential Improvement:**
Consider using LangGraph's native Redis checkpointer when available, or use the memory checkpointer for simpler deployments.

---

## Environment Variables

```env
# Required
OPENAI_API_KEY=sk-...

# LiveKit (WebRTC)
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret

# Database
DATABASE_URL=sqlite+aiosqlite:///./data/dealership.db

# Redis
REDIS_URL=redis://localhost:6379/0


# App Settings
DEBUG=true
LOG_LEVEL=INFO

# Background Tasks
HUMAN_CHECK_MIN_SECONDS=15
HUMAN_CHECK_MAX_SECONDS=25
HUMAN_AVAILABILITY_CHANCE=0.6
```

---

## Testing Commands

```bash
# Health check
curl http://localhost:8000/health

# Create session
curl -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{}'

# Send chat message
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id": "sess_xxxx", "message": "What are your hours?"}'

# List FAQ
curl http://localhost:8000/api/faq

# View logs
docker-compose logs -f app
docker-compose logs -f voice-worker
```

---

## Common Development Tasks

### Adding a New Tool

1. Create Pydantic input schema with `Field` descriptions:
```python
class MyToolInput(BaseModel):
    param1: str = Field(description="What this parameter is for")
    param2: Optional[int] = Field(None, description="Optional parameter")
```
2. Create tool function with `@tool(args_schema=MyToolInput)` decorator
3. Add to `UnifiedAgent.tools` list in `app/agents/unified_agent.py`
4. The LLM sees the schema via `bind_tools()` - no need to document in prompt

### Adding New Capabilities

Since we use a single unified agent, adding new capabilities is simple:
1. Create the tool(s) needed for the capability
2. Add tools to `UnifiedAgent.tools` list
3. Update the system prompt in `UNIFIED_SYSTEM_PROMPT` if needed
4. The agent will automatically use the tools when appropriate

### Modifying State

1. Update `ConversationState` in `app/schemas/state.py`
2. Handle serialization if needed
3. Update context building in `build_context()` if the new field should be visible to the agent

---

## Troubleshooting

### "Redis connection failed"
- Check if Redis container is running: `docker-compose ps`
- Falls back to in-memory automatically

### "Transcription returns empty"
- Audio might be too short (<0.3s)
- Check `min_speech_frames` and `min_silence_frames` thresholds
- Verify Whisper model loaded correctly

### "Agent not responding"
- Check OpenAI API key is valid
- View logs: `docker-compose logs -f app`
- Verify LangGraph compiled correctly

### "Voice not working"
- Check LiveKit is healthy: `curl localhost:7880`
- Verify token generation in `/api/voice/token`
- Check browser microphone permissions

---

## Future Improvements

1. **Streaming LLM Responses**: Use streaming for faster perceived latency
2. **LangGraph Native Checkpointing**: Use Redis checkpointer when mature
3. **Better VAD**: Consider Silero VAD for more accurate speech detection
4. **Multiple Languages**: Add language detection and multilingual TTS
5. **Analytics**: Track conversation metrics, intents, completion rates
6. **Testing**: Add unit tests for agents and integration tests for full flow
7. **Monitoring**: Add Prometheus metrics and health dashboards

---

## Code Standards

- **Pydantic everywhere**: All data models use Pydantic for validation
- **Structured LLM output**: Use `llm.with_structured_output(PydanticModel)` for classification
- **Tool schemas**: All tools use explicit `args_schema` with `Field` descriptions
- **Async by default**: All I/O operations are async
- **Type hints**: Full type annotations with `Literal` for constrained values
- **Logging**: Use structlog for structured logging
- **Error handling**: Graceful fallbacks, don't crash on errors
