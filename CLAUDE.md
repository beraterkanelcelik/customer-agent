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
- **Multi-agent LangGraph orchestration** (Router -> FAQ/Booking/Escalation)
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
| **Voice TTS** | Kokoro-82M (local GPU) / Edge TTS / Piper |
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
│   │   ├── router_agent.py   # Intent classification
│   │   ├── faq_agent.py      # FAQ handling
│   │   ├── booking_agent.py  # Appointment booking
│   │   ├── escalation_agent.py # Human transfer
│   │   └── response_generator.py
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
│   │   └── api.py            # Request/Response schemas
│   ├── services/
│   │   └── conversation.py   # High-level conversation API
│   └── tools/                # LangChain tools
│       ├── faq_tools.py
│       ├── customer_tools.py
│       ├── booking_tools.py
│       └── slot_tools.py
├── voice_worker/             # Voice processing service
│   ├── agent.py              # LiveKit voice agent
│   ├── stt.py                # Faster-Whisper wrapper
│   ├── tts.py                # Piper TTS wrapper
│   ├── tts_kokoro.py         # Kokoro TTS wrapper (default)
│   ├── tts_edge.py           # Edge TTS wrapper
│   └── main.py               # Entrypoint
├── frontend/                 # React dashboard
│   └── src/
│       ├── App.jsx
│       ├── components/       # UI components
│       └── hooks/            # useWebSocket, useLiveKit
├── docker/
│   ├── Dockerfile.app
│   ├── Dockerfile.voice
│   └── entrypoint.sh
├── data/                     # SQLite DB (generated)
├── models/                   # Whisper/Piper models
└── docs/                     # PRD documentation
```

---

## Key Files to Know

| File | Purpose |
|------|---------|
| `app/agents/graph.py` | LangGraph workflow definition - the heart of the AI |
| `app/schemas/state.py` | ConversationState - all state flows through this |
| `app/background/state_store.py` | Redis/memory state management |
| `voice_worker/agent.py` | LiveKit voice handling, VAD, barge-in |
| `app/config.py` | All configuration via Pydantic settings |
| `docker-compose.yml` | All 5 services orchestration |

---

## AI/ML Components Explained

### 1. LangGraph Multi-Agent Workflow

The conversation flows through this graph:

```
check_notifications -> router -> [faq_agent | booking_agent | escalation_agent] -> respond -> END
```

**Nodes:**
- `check_notifications`: Processes async background task results
- `router`: Classifies intent (FAQ, booking, escalation, greeting, etc.)
- `faq_agent`: Answers questions using FAQ database
- `booking_agent`: Collects slots for appointments
- `escalation_agent`: Starts async human check
- `respond`: Generates final response

**State Management:**
- Uses `ConversationState` (Pydantic model) as graph state
- `messages` field uses LangGraph's `add_messages` reducer for proper deduplication
- State is persisted to Redis between turns

### 2. Intent Classification (Router Agent)

Location: `app/agents/router_agent.py`

The router uses structured JSON output from the LLM to classify:
- **Intents**: faq, book_service, book_test_drive, reschedule, cancel, escalation, greeting, goodbye, general
- **Entities**: phone, name, email, service_type, date, time, vehicle info

The router also extracts entities from spoken input, handling STT quirks like:
- "one five five" -> "155"
- "john at gmail dot com" -> "john@gmail.com"

### 3. Booking Agent (Slot Filling)

Location: `app/agents/booking_agent.py`

Uses LangChain's `create_openai_tools_agent` with these tools:
- `update_booking_info`: Saves collected information
- `get_customer` / `create_customer`: Customer lookup/creation
- `check_availability` / `book_appointment`: Scheduling
- `list_inventory`: For test drives

The agent dynamically builds prompts showing current collected slots, so it knows what to ask for next.

### 4. Background Tasks (Escalation)

Location: `app/background/worker.py`

When user requests human assistance:
1. EscalationAgent spawns async task via `asyncio.create_task`
2. Task runs 5-25 seconds (simulating check)
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
8. TTS synthesis (Kokoro, Edge TTS, or Piper)
   - Returns WAV audio
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
| TTS | <300ms | Kokoro (local GPU), Edge (cloud), or Piper (CPU) |
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
    session_id: str
    messages: List[BaseMessage]  # LangGraph add_messages reducer
    current_agent: AgentType
    detected_intent: Optional[IntentType]
    customer: CustomerContext
    booking_slots: BookingSlots
    pending_tasks: List[BackgroundTask]
    notifications_queue: List[Notification]
    escalation_in_progress: bool
    human_agent_status: Optional[HumanAgentStatus]
    turn_count: int
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

# Voice - STT
WHISPER_MODEL=base|small|medium
WHISPER_DEVICE=cpu|cuda

# Voice - TTS
TTS_BACKEND=kokoro|edge|piper
KOKORO_VOICE=af_heart
KOKORO_LANG_CODE=a
EDGE_TTS_VOICE=en-US-JennyNeural
PIPER_VOICE=en_US-amy-medium

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

### Adding a New Agent

1. Create `app/agents/new_agent.py`
2. Add node function in `app/agents/graph.py`
3. Add to workflow edges
4. Update routing in `route_after_router()`

### Adding a New Tool

1. Create tool function with `@tool` decorator
2. Add to appropriate agent's `tools` list
3. Document in system prompt

### Modifying State

1. Update `ConversationState` in `app/schemas/state.py`
2. Handle serialization if needed
3. Update any nodes that use the new field

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
- **Async by default**: All I/O operations are async
- **Type hints**: Full type annotations
- **Logging**: Use structlog for structured logging
- **Error handling**: Graceful fallbacks, don't crash on errors
