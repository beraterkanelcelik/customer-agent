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
- **Voice via Twilio** + Faster-Whisper (STT) + Kokoro-82M (TTS)
- **React dashboard** showing real-time agent state and transcripts
- **SQLite database** with customers, appointments, FAQ

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| **Backend** | FastAPI + LangGraph + SQLAlchemy (async) |
| **LLM** | OpenAI GPT-4o-mini (configurable) |
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
│   │   ├── graph.py          # Main state graph definition
│   │   └── unified_agent.py  # Single agent with all capabilities
│   ├── api/
│   │   ├── routes.py         # HTTP endpoints
│   │   ├── routes_twilio.py  # Twilio escalation webhooks
│   │   ├── voice_routes.py   # Twilio voice/media stream endpoints
│   │   └── websocket.py      # Real-time updates to dashboard
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
│   │   ├── conversation.py   # High-level conversation API
│   │   ├── audio_processor.py # STT/TTS using Faster-Whisper + Kokoro
│   │   ├── twilio_service.py # Twilio outbound calls for escalation
│   │   └── twilio_voice.py   # Twilio Media Streams voice handling
│   └── tools/                # LangChain tools (all with Pydantic schemas)
│       ├── faq_tools.py
│       ├── customer_tools.py
│       ├── booking_tools.py
│       ├── slot_tools.py
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
├── logs/                     # Runtime logs (generated)
└── docs/                     # PRD documentation
```

---

## Key Files to Know

| File | Purpose |
|------|---------|
| `app/agents/graph.py` | LangGraph workflow definition (tool-calling loop) |
| `app/agents/unified_agent.py` | Single agent with all tools - the heart of the AI |
| `app/schemas/state.py` | ConversationState - all state flows through this |
| `app/background/state_store.py` | Redis/memory state management |
| `app/services/twilio_voice.py` | Twilio Media Streams handling, VAD, audio processing |
| `app/services/audio_processor.py` | STT (Faster-Whisper) and TTS (Kokoro) |
| `app/api/voice_routes.py` | Twilio voice webhooks and WebSocket media stream |
| `app/config.py` | All configuration via Pydantic settings |
| `docker-compose.yml` | All 3 services orchestration |

---

## AI/ML Components Explained

### 1. LangGraph Unified Agent Workflow

The conversation flows through a tool-calling loop:

```
preprocess_node -> agent_node -> [tool_node -> agent_node]* -> postprocess_node -> END
```

**Nodes:**
- `preprocess_node`: Processes async background task results (escalation callbacks)
- `agent_node`: Invokes LLM with tools bound
- `tool_node`: Executes tool calls and returns results
- `postprocess_node`: Updates state, handles confirmations, prepends notifications

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
4. Next turn, `preprocess_node` delivers message
5. Dashboard also receives updates via WebSocket

---

## Voice Processing Pipeline (Twilio)

### Full Flow (Phone Call -> AI Response -> Audio)

```
1. Customer calls Twilio phone number
          │
          ▼
2. Twilio sends webhook to /api/voice/incoming
          │
          ▼
3. Backend returns TwiML with <Connect><Stream>
          │
          ▼
4. Twilio opens WebSocket to /api/voice/media-stream
          │
          ▼
5. Audio streamed as base64 mulaw (8kHz)
          │
          ▼
6. VAD detects speech start/end
   (energy-based, ~20ms frames)
          │
          ▼
7. Audio buffered until silence detected
   (MIN_SILENCE_FRAMES = 30 = ~600ms)
          │
          ▼
8. STT transcription (Faster-Whisper)
   - Converts mulaw -> linear PCM -> 16kHz WAV
   - Returns transcribed text
          │
          ▼
9. LangGraph processes message via conversation_service
   - Returns response text + metadata
          │
          ▼
10. TTS synthesis (Kokoro)
    - Returns MP3 audio
          │
          ▼
11. Audio converted to mulaw 8kHz for Twilio
          │
          ▼
12. Streamed back to Twilio in 20ms chunks
          │
          ▼
13. Customer hears AI response
```

### VAD Configuration

Key settings in `app/services/twilio_voice.py`:
- `SILENCE_THRESHOLD = 500`: Energy threshold for speech detection
- `MIN_SPEECH_FRAMES = 5`: Frames needed to confirm speech start (~100ms)
- `MIN_SILENCE_FRAMES = 30`: Frames of silence to end utterance (~600ms)

### Human Escalation via Twilio Conference

When the AI decides to escalate:
1. AI calls `request_human_agent` tool
2. Customer is moved to a Twilio Conference room
3. Outbound call placed to `CUSTOMER_SERVICE_PHONE`
4. Human answers -> joined to same conference
5. Customer and human can now talk directly

### Latency Budget

| Stage | Target | Notes |
|-------|--------|-------|
| VAD | <50ms | Energy-based detection |
| STT | <500ms | Faster-Whisper medium |
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

1. Request arrives at `/api/chat` or via Twilio media stream
2. `state_store.get_state(session_id)` fetches from Redis
3. State deserialized (messages converted back to LangChain objects)
4. LangGraph processes with state
5. Updated state saved via `state_store.set_state()`

---

## Environment Variables

```env
# Required
OPENAI_API_KEY=sk-...

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

# Twilio Voice (Required for phone conversations)
# Get credentials from https://console.twilio.com
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_PHONE_NUMBER=+15551234567           # Your Twilio number
TWILIO_WEBHOOK_BASE_URL=https://your-ngrok-url.ngrok.io  # Public URL for webhooks
CUSTOMER_SERVICE_PHONE=+15559876543        # Human agent number for escalation

# Local Audio Models (STT/TTS)
# Faster-Whisper for Speech-to-Text (GPU-accelerated)
WHISPER_MODEL=medium           # Options: tiny, base, small, medium, large-v2
WHISPER_DEVICE=cuda            # Options: cuda, cpu
WHISPER_COMPUTE_TYPE=int8      # Options: int8, float16, float32

# Kokoro-82M for Text-to-Speech (local, <2GB VRAM)
KOKORO_VOICE=af_heart          # af_heart = warm friendly female voice
KOKORO_LANG=a                  # a = American English
```

---

## Testing Commands

```bash
# Health check
curl http://localhost:8000/health

# Check voice models status
curl http://localhost:8000/api/voice/status

# Create session (for testing without phone)
curl -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{}'

# Send chat message (text mode)
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id": "sess_xxxx", "message": "What are your hours?"}'

# List FAQ
curl http://localhost:8000/api/faq

# View logs
docker-compose logs -f app
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

## Twilio Setup Guide

### 1. Get Twilio Credentials

1. Create account at https://console.twilio.com
2. Get a phone number (Voice capable)
3. Copy Account SID, Auth Token from dashboard

### 2. Set Up ngrok for Local Development

```bash
# Install ngrok
brew install ngrok  # or download from ngrok.com

# Start tunnel
ngrok http 8000

# Copy the https URL (e.g., https://abc123.ngrok.io)
```

### 3. Configure Twilio Webhooks

In Twilio Console > Phone Numbers > Your Number:
- **Voice Configuration**:
  - "A call comes in": Webhook, `https://your-ngrok-url/api/voice/incoming`, HTTP POST
  - "Call status changes": `https://your-ngrok-url/api/voice/status`, HTTP POST

### 4. Update .env

```env
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_token
TWILIO_PHONE_NUMBER=+15551234567
TWILIO_WEBHOOK_BASE_URL=https://your-ngrok-url.ngrok.io
CUSTOMER_SERVICE_PHONE=+15559876543  # Your personal phone for escalation testing
```

### 5. Test

1. Start the app: `docker-compose up -d`
2. Call your Twilio number
3. Watch the dashboard at http://localhost:5173

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

## Future Improvements

1. **Streaming LLM Responses**: Use streaming for faster perceived latency
2. **LangGraph Native Checkpointing**: Use Redis checkpointer when mature
3. **Better VAD**: Consider Silero VAD for more accurate speech detection
4. **Multiple Languages**: Add language detection and multilingual TTS
5. **Analytics**: Track conversation metrics, intents, completion rates
6. **Testing**: Add unit tests for agents and integration tests for full flow
7. **Monitoring**: Add Prometheus metrics and health dashboards
8. **Barge-in Support**: Allow user to interrupt AI while speaking

---

## Code Standards

- **Pydantic everywhere**: All data models use Pydantic for validation
- **Structured LLM output**: Use `llm.with_structured_output(PydanticModel)` for classification
- **Tool schemas**: All tools use explicit `args_schema` with `Field` descriptions
- **Async by default**: All I/O operations are async
- **Type hints**: Full type annotations with `Literal` for constrained values
- **Logging**: Use structlog for structured logging
- **Error handling**: Graceful fallbacks, don't crash on errors
