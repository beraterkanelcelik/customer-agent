# CLAUDE.md - AI Agent Development Guide

This document serves as your guide to the Car Dealership Voice Agent (Customer Agent) project. Read this before making any changes.

---

## Quick Start

```bash
# 1. Setup environment
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY and Twilio credentials

# 2. Build and start all services
docker-compose up -d --build

# 3. Check health
curl http://localhost:8000/health

# 4. Open dashboard
# Navigate to http://localhost:5173

# 5. Call your Twilio number to start a conversation!
```

---

## Project Overview

A real-time voice customer service agent for car dealerships featuring:
- **Unified LangGraph agent** (single agent handles FAQ, booking, escalation)
- **Async background tasks** (human escalation doesn't block conversation)
- **Voice via Twilio Media Streams** + Faster-Whisper (STT) + Kokoro-82M (TTS)
- **React dashboard** showing real-time agent state and transcripts
- **SQLite database** with customers, appointments, FAQ

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| **Backend** | FastAPI + LangGraph + SQLAlchemy (async) |
| **LLM** | OpenAI GPT-4.1-mini (configurable) |
| **Voice STT** | Faster-Whisper (local, GPU-accelerated) |
| **Voice TTS** | Kokoro-82M (local GPU) |
| **Voice Infrastructure** | Twilio (Media Streams + WebSocket) |
| **State Store** | Redis (with in-memory fallback) |
| **Database** | SQLite (async via aiosqlite) |
| **Frontend** | React 18 + Vite + TailwindCSS |
| **Containerization** | Docker Compose (3 services) |

---

## Directory Structure

```
customer-agent/
├── app/                      # FastAPI backend
│   ├── agents/               # LangGraph agents
│   │   └── graph.py          # Unified agent with tool-calling loop
│   ├── api/
│   │   ├── routes.py         # HTTP endpoints
│   │   ├── routes_twilio.py  # Twilio escalation webhooks
│   │   ├── voice_routes.py   # Twilio voice/media stream endpoints
│   │   └── websocket.py      # Real-time updates to dashboard
│   ├── background/
│   │   ├── state_store.py    # Redis/memory state with optimistic locking
│   │   └── worker.py         # Async background tasks
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
│   │   ├── conversation.py   # High-level conversation API
│   │   ├── audio_processor.py # STT/TTS using Faster-Whisper + Kokoro
│   │   ├── twilio_service.py # Twilio outbound calls for escalation
│   │   └── twilio_voice.py   # Twilio Media Streams voice handling
│   └── tools/                # LangChain tools (all with Pydantic schemas)
│       ├── __init__.py       # ALL_TOOLS export
│       ├── faq_tools.py
│       ├── customer_tools.py
│       ├── booking_tools.py
│       ├── slot_tools.py
│       ├── escalation_tools.py
│       └── call_tools.py
├── frontend/                 # React dashboard
│   ├── src/
│   │   ├── App.jsx           # Main voice agent dashboard
│   │   ├── AgentFlowDiagram.jsx # Architecture visualization
│   │   ├── components/       # AgentState, BookingSlots, Transcript,
│   │   │                     # CustomerInfo, TaskMonitor, AvailabilityCalendar
│   │   └── hooks/            # useWebSocket
│   ├── Dockerfile
│   └── nginx.conf
├── docker/
│   ├── Dockerfile.app
│   └── entrypoint.sh
├── data/                     # SQLite DB (generated)
├── models/                   # Whisper/Kokoro models (auto-downloaded)
├── cache/                    # ML model caches (huggingface, torch)
├── logs/                     # Runtime logs (generated)
└── docs/                     # PRD documentation
```

---

## Key Files to Know

| File | Purpose |
|------|---------|
| `app/agents/graph.py` | LangGraph workflow: preprocess -> agent -> tools -> postprocess |
| `app/tools/__init__.py` | ALL_TOOLS list - all 15 tools available to the agent |
| `app/schemas/state.py` | ConversationState - all state flows through this |
| `app/background/state_store.py` | Redis/memory state with optimistic locking |
| `app/services/twilio_voice.py` | Twilio Media Streams handling, VAD, audio processing |
| `app/services/audio_processor.py` | STT (Faster-Whisper) and TTS (Kokoro) |
| `app/api/voice_routes.py` | Twilio voice webhooks and WebSocket media stream |
| `app/config.py` | All configuration via Pydantic settings |
| `docker-compose.yml` | All 3 services orchestration |

---

## LangGraph Agent Flow

### Graph Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        LangGraph Workflow                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ┌──────────────┐                                              │
│   │   START      │                                              │
│   └──────┬───────┘                                              │
│          │                                                      │
│          ▼                                                      │
│   ┌──────────────┐     Process background task results          │
│   │  preprocess  │     (escalation callbacks, notifications)    │
│   └──────┬───────┘                                              │
│          │                                                      │
│          ▼                                                      │
│   ┌──────────────┐     Invoke LLM with all tools bound          │
│   │    agent     │◄────────────────────────────────────┐        │
│   └──────┬───────┘                                     │        │
│          │                                             │        │
│          ▼                                             │        │
│   ┌──────────────┐     Has tool calls?                 │        │
│   │  conditional │─────────────────────────────────────┤        │
│   └──────┬───────┘     YES: Execute tools              │        │
│          │                                             │        │
│          │ NO                                          │        │
│          ▼                                             │        │
│   ┌──────────────┐     ┌──────────────┐               │        │
│   │ postprocess  │     │    tools     │───────────────┘        │
│   └──────┬───────┘     └──────────────┘                        │
│          │             Execute tool calls, return results       │
│          ▼                                                      │
│   ┌──────────────┐                                              │
│   │     END      │                                              │
│   └──────────────┘                                              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Node Functions

| Node | Function | Purpose |
|------|----------|---------|
| `preprocess_node` | `preprocess_node()` | Process notifications from background tasks (escalation results), inject special markers for agent |
| `agent_node` | `agent_node()` | Build context, invoke LLM with tools bound, return response with possible tool calls |
| `tool_node` | `tool_node()` | Execute tool calls, inject session_id where needed, return ToolMessages |
| `postprocess_node` | `postprocess_node()` | Update state from tool results, handle confirmations, increment turn count |

### Routing Logic

```python
def should_continue(state) -> Literal["tools", "postprocess"]:
    last_message = state.messages[-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"  # Execute tools, then back to agent
    return "postprocess"  # Finish turn
```

### Why Single Agent?

- **No routing issues**: Can't lose context mid-booking
- **Simpler state management**: One agent, one state
- **Natural conversation flow**: Handles mixed intents (e.g., "thanks, my name is John")
- **LLM decides everything**: No hardcoded logic, all decisions via tools

---

## Available Tools

All tools are defined in `app/tools/` and exported via `ALL_TOOLS` in `app/tools/__init__.py`.

| Tool | File | Purpose |
|------|------|---------|
| `search_faq` | `faq_tools.py` | Search FAQ database for answers |
| `list_services` | `faq_tools.py` | List services with pricing |
| `get_customer` | `customer_tools.py` | Look up customer by phone |
| `create_customer` | `customer_tools.py` | Create new customer record |
| `check_availability` | `booking_tools.py` | Check available time slots |
| `book_appointment` | `booking_tools.py` | Book the appointment |
| `reschedule_appointment` | `booking_tools.py` | Change appointment date/time |
| `cancel_appointment` | `booking_tools.py` | Cancel an appointment |
| `get_customer_appointments` | `booking_tools.py` | List customer's bookings |
| `list_inventory` | `booking_tools.py` | Show vehicles for test drive |
| `update_booking_info` | `slot_tools.py` | Save collected slot information |
| `set_customer_identified` | `slot_tools.py` | Mark customer as verified |
| `get_todays_date` | `slot_tools.py` | Get current date for scheduling |
| `request_human_agent` | `escalation_tools.py` | Request human escalation |
| `end_call` | `call_tools.py` | End voice call gracefully |

### Context Injection

The agent receives full context on every turn via `build_context()`:
- Current date and upcoming days
- Customer identification status
- Booking progress (what's collected, what's still needed)
- Escalation status (in-progress, failed, connected)
- Voice call indicator (affects response length)

---

## Voice Processing Pipeline

### Full Flow (Phone Call -> AI Response -> Audio)

```
┌─────────────────────────────────────────────────────────────────┐
│                    Voice Processing Pipeline                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Customer calls Twilio phone number                          │
│              │                                                  │
│              ▼                                                  │
│  2. Twilio POST /api/voice/incoming                             │
│              │                                                  │
│              ▼                                                  │
│  3. Backend returns TwiML with <Connect><Stream>                │
│              │                                                  │
│              ▼                                                  │
│  4. Twilio opens WebSocket to /api/voice/media-stream           │
│              │                                                  │
│              ▼                                                  │
│  5. Audio streamed as base64 mulaw (8kHz)                       │
│              │                                                  │
│              ▼                                                  │
│  6. VAD detects speech start/end                                │
│     (energy-based, ~20ms frames)                                │
│              │                                                  │
│              ▼                                                  │
│  7. Audio buffered until silence detected                       │
│     (MIN_SILENCE_FRAMES = 30 = ~600ms)                          │
│              │                                                  │
│              ▼                                                  │
│  8. STT transcription (Faster-Whisper)                          │
│     mulaw -> linear PCM -> 16kHz WAV -> text                    │
│              │                                                  │
│              ▼                                                  │
│  9. LangGraph processes via conversation_service                │
│     Returns response text + metadata                            │
│              │                                                  │
│              ▼                                                  │
│ 10. TTS synthesis (Kokoro)                                      │
│     text -> WAV audio (24kHz)                                   │
│              │                                                  │
│              ▼                                                  │
│ 11. Audio converted (soxr resampling)                           │
│     WAV 24kHz -> mulaw 8kHz                                     │
│              │                                                  │
│              ▼                                                  │
│ 12. Streamed back to Twilio in 20ms chunks                      │
│              │                                                  │
│              ▼                                                  │
│ 13. Customer hears AI response                                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### VAD Configuration

Key settings in `app/services/twilio_voice.py`:
- `SILENCE_THRESHOLD = 500`: Energy threshold for speech detection
- `MIN_SPEECH_FRAMES = 5`: Frames needed to confirm speech start (~100ms)
- `MIN_SILENCE_FRAMES = 30`: Frames of silence to end utterance (~600ms)

### Human Escalation via Twilio Conference

```
1. AI calls request_human_agent tool
           │
           ▼
2. Background task initiates outbound call to CUSTOMER_SERVICE_PHONE
           │
           ▼
3. Human's phone rings, they hear "Press any key to accept"
           │
           ▼
4. Human presses key -> Confirmation prompt plays
           │
           ▼
5. Human presses 1 -> Joined to Twilio Conference
           │
           ▼
6. Customer transferred from AI to Conference
           │
           ▼
7. Customer and human can now talk directly
```

### Barge-in Support

The system supports barge-in (user interrupting AI while speaking):
- `twilio_voice.set_playing_audio()` tracks playback state
- `twilio_voice.should_barge_in()` checks if user started speaking
- Audio playback stops and user's speech is processed

### Latency Budget

| Stage | Target | Notes |
|-------|--------|-------|
| VAD | <50ms | Energy-based detection |
| STT | <500ms | Faster-Whisper medium |
| LangGraph | <2000ms | Includes LLM API calls |
| TTS | <300ms | Kokoro (local GPU) |
| **Total** | **<3s** | Acceptable for voice |

---

## State Management

### Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Browser   │────▶│   FastAPI   │────▶│    Redis    │
│  (Frontend) │     │   (app)     │     │  (state)    │
└─────────────┘     └─────────────┘     └─────────────┘
       │                   │
       │ WebSocket         │
       ▼                   ▼
┌─────────────┐     ┌─────────────┐
│  Dashboard  │     │ LangGraph   │
│  Updates    │     │  (agents)   │
└─────────────┘     └─────────────┘
```

### ConversationState Structure

```python
class ConversationState(BaseModel):
    # Core identity
    session_id: str
    messages: List[BaseMessage]  # LangGraph add_messages reducer

    # Agent routing
    current_agent: AgentType  # Always UNIFIED
    detected_intent: Optional[IntentType]
    confidence: float

    # Customer & booking context
    customer: CustomerContext
    booking_slots: BookingSlots
    pending_confirmation: Optional[Dict[str, Any]]
    confirmed_appointment: Optional[ConfirmedAppointment]

    # Background task management
    pending_tasks: List[BackgroundTask]
    notifications_queue: List[Notification]
    escalation_in_progress: bool
    human_agent_status: Optional[HumanAgentStatus]

    # Flow control flags
    should_respond: bool
    needs_slot_filling: bool
    waiting_for_background: bool
    is_voice_call: bool  # Affects response length
    prepend_message: Optional[str]

    # Metadata
    turn_count: int
    created_at: datetime
    last_updated: datetime
    version: int  # Optimistic locking
```

### Optimistic Locking

State updates use optimistic locking to handle concurrent updates:
1. `get_state_with_version()` returns state + version
2. Process through LangGraph
3. `set_state_if_version()` only saves if version matches
4. On conflict, retry up to `MAX_RETRIES` times

---

## Environment Variables

```env
# Required
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4.1-mini

# Database
DATABASE_URL=sqlite+aiosqlite:///./data/dealership.db

# Redis
REDIS_URL=redis://localhost:6379/0

# App Settings
DEBUG=true
LOG_LEVEL=INFO

# Background Tasks
HUMAN_CHECK_MIN_SECONDS=5
HUMAN_CHECK_MAX_SECONDS=10
HUMAN_AVAILABILITY_CHANCE=0.6

# Twilio Voice (Required for phone conversations)
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_PHONE_NUMBER=+15551234567
TWILIO_WEBHOOK_BASE_URL=https://your-ngrok-url.ngrok.io
CUSTOMER_SERVICE_PHONE=+15559876543

# Local Audio Models (STT/TTS)
WHISPER_MODEL=medium
WHISPER_DEVICE=cuda
WHISPER_COMPUTE_TYPE=int8
KOKORO_VOICE=af_heart
KOKORO_LANG=a

# Hugging Face (optional)
HF_TOKEN=hf_your_token_here
```

---

## API Endpoints

### Session Management
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/sessions` | POST | Create new session |
| `/api/sessions/{id}` | GET | Get session info |
| `/api/sessions/{id}` | DELETE | End session |

### Chat
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/chat` | POST | Send message, get response |

### Voice (Twilio)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/voice/incoming` | POST | Incoming call webhook |
| `/api/voice/media-stream` | WS | Bidirectional audio stream |
| `/api/voice/status` | GET | Check STT/TTS model status |
| `/api/voice/escalate` | POST | Put customer in conference |
| `/api/voice/human-answer` | POST | Human answered webhook |
| `/api/voice/human-confirmed` | POST | Human pressed 1 to accept |
| `/api/voice/human-status` | POST | Human call status updates |
| `/api/voice/return-to-ai` | POST | Return from conference to AI |

### Data
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/faq` | GET | List FAQ entries |
| `/api/services` | GET | List services |
| `/api/inventory` | GET | List vehicles |
| `/api/availability` | GET | Get appointment slots |
| `/api/customers/{phone}` | GET | Get customer by phone |
| `/api/appointments` | GET | List appointments |

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
3. Add to `ALL_TOOLS` list in `app/tools/__init__.py`
4. The LLM sees the schema via `bind_tools()` - no need to document in prompt

### Modifying State

1. Update `ConversationState` in `app/schemas/state.py`
2. Handle serialization in `deserialize_messages()` if needed
3. Update `build_context()` in `graph.py` if the new field should be visible to the agent

### Adding Special Message Markers

The agent handles special messages like `[CALL_STARTED]`, `[PROCESSING_ERROR]`, `[ESCALATION_RETURNED:busy]`. To add a new marker:
1. Add documentation in `SYSTEM_PROMPT` in `graph.py`
2. Generate the marker in the appropriate place (voice_routes.py, etc.)
3. Agent will generate appropriate response based on the marker

---

## Testing Commands

```bash
# Health check
curl http://localhost:8000/health

# Check voice models status
curl http://localhost:8000/api/voice/status

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
```

---

## Troubleshooting

### "Redis connection failed"
- Check if Redis container is running: `docker-compose ps`
- Falls back to in-memory automatically

### "Transcription returns empty"
- Audio might be too short (<0.3s)
- Check `MIN_SPEECH_FRAMES` and `MIN_SILENCE_FRAMES` thresholds
- Verify Whisper model loaded: check `/api/voice/status`

### "Agent not responding"
- Check OpenAI API key is valid
- View logs: `docker-compose logs -f app`
- Verify LangGraph compiled correctly

### "Voice not working / No audio"
- Check Twilio webhook URL is correct and reachable
- Verify ngrok is running and URL matches .env
- Check browser console for WebSocket errors
- Ensure Twilio phone number has Voice capability

### "TTS/STT models not loading"
- Check GPU availability: `nvidia-smi`
- If no GPU, set `WHISPER_DEVICE=cpu`
- Models download on first use (~2-3GB)

---

## Code Standards

- **Pydantic everywhere**: All data models use Pydantic for validation
- **Tool schemas**: All tools use explicit `args_schema` with `Field` descriptions
- **Async by default**: All I/O operations are async
- **Type hints**: Full type annotations with `Literal` for constrained values
- **No hardcoded messages**: All spoken text generated by the LLM agent
- **Error handling**: Graceful fallbacks, don't crash on errors
