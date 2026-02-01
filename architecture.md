# Architecture Documentation

## System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              DOCKER NETWORK: dealership-net                          │
│                                                                                      │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌────────────────┐    │
│  │   LiveKit    │    │    Redis     │    │   Frontend   │    │  Voice Worker  │    │
│  │    :7880     │    │    :6379     │    │    :5173     │    │  (no port)     │    │
│  │   (WebRTC)   │    │   (State)    │    │   (React)    │    │  (STT/TTS)     │    │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘    └───────┬────────┘    │
│         │                   │                   │                    │             │
│         │    ┌──────────────┴───────────────────┴────────────────────┘             │
│         │    │                                                                      │
│         ▼    ▼                                                                      │
│  ┌────────────────────────────────────────┐                                        │
│  │           FastAPI Application          │                                        │
│  │              :8000                      │                                        │
│  │  ┌──────────────────────────────────┐  │                                        │
│  │  │         LangGraph Agents         │  │                                        │
│  │  │  Router → FAQ/Booking/Escalation │  │                                        │
│  │  └──────────────────────────────────┘  │                                        │
│  └────────────────────┬───────────────────┘                                        │
│                       │                                                             │
│                       ▼                                                             │
│              ┌────────────────┐                                                     │
│              │     SQLite     │                                                     │
│              │    Database    │                                                     │
│              └────────────────┘                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Service Architecture

### 1. FastAPI Application (app)

**Port:** 8000
**Role:** Main backend API, LangGraph orchestration

**Responsibilities:**
- HTTP API for chat, sessions, voice tokens
- WebSocket for real-time updates
- LangGraph multi-agent orchestration
- Database operations
- Background task management

**Key Endpoints:**
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check |
| `/api/sessions` | POST | Create session |
| `/api/chat` | POST | Process message |
| `/api/voice/token` | POST | Get LiveKit token |
| `/ws/{session_id}` | WS | Real-time updates |

### 2. Voice Worker

**Port:** None (connects to LiveKit as agent)
**Role:** Speech-to-text, text-to-speech, audio handling

**Responsibilities:**
- Connect to LiveKit rooms as an agent
- Voice Activity Detection (VAD)
- Audio capture and resampling
- STT via Faster-Whisper
- TTS via Kokoro-82M (default), Edge TTS, or Piper
- Barge-in detection

**Audio Flow:**
```
User Mic (browser)
    → WebRTC (LiveKit)
    → Voice Worker (48kHz)
    → Resample (16kHz)
    → Whisper STT
    → Text to API
    → Response Text
    → TTS Audio
    → Resample (48kHz)
    → WebRTC (LiveKit)
    → User Speakers
```

### 3. LiveKit Server

**Ports:** 7880 (HTTP/WS), 7881 (RTC), 7882 (UDP)
**Role:** WebRTC infrastructure

**Responsibilities:**
- Real-time audio/video transport
- Room management
- Participant tracking
- Audio mixing

### 4. Redis

**Port:** 6379
**Role:** State persistence

**Responsibilities:**
- Session state storage
- Fast key-value access
- TTL-based session expiry

### 5. Frontend

**Port:** 5173 (mapped to nginx 80)
**Role:** User interface

**Responsibilities:**
- Voice call controls
- Live transcript display
- Agent state visualization
- Booking slots display
- Task monitoring

---

## LangGraph Agent Architecture

### State Flow Diagram

```
                                 ┌─────────────────┐
                                 │  User Message   │
                                 └────────┬────────┘
                                          │
                                          ▼
                              ┌───────────────────────┐
                              │  check_notifications  │
                              │  (process async task  │
                              │   results)            │
                              └───────────┬───────────┘
                                          │
                                          ▼
                              ┌───────────────────────┐
                              │       router          │
                              │  (classify intent)    │
                              └───────────┬───────────┘
                                          │
                ┌─────────────────────────┼─────────────────────────┐
                │                         │                         │
                ▼                         ▼                         ▼
     ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
     │    faq_agent     │    │  booking_agent   │    │ escalation_agent │
     │                  │    │                  │    │                  │
     │ - search_faq     │    │ - update_booking │    │ - spawn async    │
     │ - list_services  │    │ - get_customer   │    │   human check    │
     │                  │    │ - book_appt      │    │                  │
     └────────┬─────────┘    └────────┬─────────┘    └────────┬─────────┘
              │                       │                       │
              └───────────────────────┴───────────────────────┘
                                      │
                                      ▼
                              ┌───────────────────────┐
                              │       respond         │
                              │  (format response,    │
                              │   prepend notifs)     │
                              └───────────┬───────────┘
                                          │
                                          ▼
                                       [END]
```

### ConversationState Schema

```python
ConversationState:
├── session_id: str
├── messages: List[BaseMessage]         # Chat history (add_messages reducer)
├── current_agent: AgentType            # router/faq/booking/escalation/response
├── detected_intent: IntentType         # faq/book_service/escalation/etc.
├── confidence: float                   # 0.0-1.0
├── customer: CustomerContext
│   ├── customer_id: Optional[int]
│   ├── name: Optional[str]
│   ├── phone: Optional[str]
│   ├── email: Optional[str]
│   └── vehicles: List[dict]
├── booking_slots: BookingSlots
│   ├── appointment_type: Optional[enum]
│   ├── service_type: Optional[str]
│   ├── preferred_date: Optional[str]
│   ├── preferred_time: Optional[str]
│   ├── customer_name: Optional[str]
│   ├── customer_phone: Optional[str]
│   └── customer_email: Optional[str]
├── pending_tasks: List[BackgroundTask]
├── notifications_queue: List[Notification]
├── escalation_in_progress: bool
├── human_agent_status: Optional[enum]
├── turn_count: int
├── created_at: datetime
└── last_updated: datetime
```

---

## Database Schema

### Entity Relationship Diagram

```
┌─────────────────┐       ┌─────────────────┐
│    customers    │       │    vehicles     │
├─────────────────┤       ├─────────────────┤
│ id (PK)         │◄──┐   │ id (PK)         │
│ phone (unique)  │   └───│ customer_id (FK)│
│ name            │       │ make            │
│ email           │       │ model           │
│ created_at      │       │ year            │
│ updated_at      │       │ license_plate   │
└─────────────────┘       │ vin             │
        │                 └─────────────────┘
        │
        ▼
┌─────────────────┐       ┌─────────────────┐
│  appointments   │       │  service_types  │
├─────────────────┤       ├─────────────────┤
│ id (PK)         │       │ id (PK)         │
│ customer_id (FK)│───────│ name            │
│ appointment_type│       │ duration_min    │
│ service_type_id │───────│ price_min       │
│ vehicle_id (FK) │       │ price_max       │
│ inventory_id    │       └─────────────────┘
│ scheduled_date  │
│ scheduled_time  │       ┌─────────────────┐
│ duration_min    │       │    inventory    │
│ status          │       ├─────────────────┤
│ notes           │       │ id (PK)         │
└─────────────────┘       │ make            │
                          │ model           │
┌─────────────────┐       │ year            │
│      faq        │       │ color           │
├─────────────────┤       │ price           │
│ id (PK)         │       │ is_new          │
│ category        │       │ is_available    │
│ question        │       │ stock_number    │
│ answer          │       └─────────────────┘
│ keywords        │
└─────────────────┘
```

---

## Voice Processing Architecture

### STT Pipeline (Faster-Whisper)

```
Raw Audio (48kHz, 16-bit PCM)
         │
         ▼
┌─────────────────────────┐
│     Resample to 16kHz   │  (Linear interpolation)
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│    Convert to WAV       │  (wave module)
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│    Faster-Whisper       │
│    - model: base/small  │
│    - device: cpu/cuda   │
│    - compute: int8/fp16 │
└────────────┬────────────┘
             │
             ▼
         Text Output
```

### TTS Pipeline (Kokoro - Default)

```
Text Input
     │
     ▼
┌─────────────────────────┐
│   Kokoro-82M Pipeline   │  (StyleTTS 2 architecture)
│   - Voice: af_heart     │  (warm, friendly female)
│   - Lang: American Eng  │
│   - VRAM: <2GB          │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│   WAV Output (24kHz)    │  (direct, no conversion)
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│   Resample to 48kHz     │  (for LiveKit)
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│   Stream in 20ms frames │  (960 samples/frame)
└─────────────────────────┘
```

### TTS Pipeline (Edge TTS - Fallback)

```
Text Input
     │
     ▼
┌─────────────────────────┐
│   Edge TTS API Call     │  (Microsoft neural voices)
│   - Voice: JennyNeural  │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│     MP3 Response        │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│   Convert to WAV        │  (pydub or ffmpeg)
│   - 24kHz sample rate   │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│   Resample to 48kHz     │  (for LiveKit)
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│   Stream in 20ms frames │  (960 samples/frame)
└─────────────────────────┘
```

### Voice Activity Detection (VAD)

```python
VAD Parameters:
├── vad_threshold: 0.012      # RMS energy threshold
├── min_speech_frames: 5      # Frames to confirm speech start
├── min_silence_frames: 60    # Frames to confirm speech end (~1.2s)
└── barge_in_frames: 8        # Frames to trigger interruption

Frame Processing:
1. Calculate RMS energy: sqrt(mean(samples^2)) / 32768
2. If energy > threshold:
   - Increment speech_frames
   - If speaking + barge_in_frames exceeded: interrupt agent
   - If speech_frames >= min_speech_frames: start buffering
3. If energy <= threshold:
   - Increment silence_frames
   - If silence_frames >= min_silence_frames: process buffer
```

---

## State Management Deep Dive

### Redis State Structure

```
Key: session:{session_id}
TTL: 30 minutes (configurable)

Value (JSON):
{
  "session_id": "sess_abc123",
  "messages": [
    {"type": "human", "content": "Hello"},
    {"type": "ai", "content": "Welcome!"}
  ],
  "current_agent": "router",
  "detected_intent": "greeting",
  "confidence": 0.95,
  "customer": {
    "customer_id": null,
    "name": null,
    ...
  },
  "booking_slots": {...},
  "pending_tasks": [...],
  "turn_count": 1,
  ...
}
```

### Message Serialization

LangChain messages serialize as:
```json
{"type": "human", "content": "Hello"}
{"type": "ai", "content": "Welcome!"}
```

Deserialization (`deserialize_messages`):
```python
def deserialize_messages(messages):
    for msg in messages:
        if msg["type"] == "human":
            yield HumanMessage(content=msg["content"])
        elif msg["type"] == "ai":
            yield AIMessage(content=msg["content"])
```

### State Update Flow

```
1. API receives request
         │
         ▼
2. state_store.get_state(session_id)
   └── Redis GET session:{id}
   └── JSON parse
   └── ConversationState(**data)
   └── deserialize_messages()
         │
         ▼
3. LangGraph processes
   └── Nodes update state
   └── Tools may modify slots
         │
         ▼
4. state_store.set_state(session_id, state)
   └── state.model_dump(mode="json")
   └── JSON stringify
   └── Redis SET with TTL
```

---

## WebSocket Protocol

### Message Types

```typescript
// State Update
{
  "type": "state_update",
  "session_id": "sess_xxx",
  "current_agent": "booking",
  "intent": "book_service",
  "confidence": 0.92,
  "customer": {...},
  "booking_slots": {...},
  "pending_tasks": [...]
}

// Transcript Message
{
  "type": "transcript",
  "session_id": "sess_xxx",
  "role": "user" | "assistant",
  "content": "I need an oil change",
  "agent_type": "booking"
}

// Task Update
{
  "type": "task_update",
  "session_id": "sess_xxx",
  "task": {
    "task_id": "esc_xxx",
    "task_type": "human_escalation",
    "status": "completed",
    "human_available": true,
    "human_agent_name": "Sarah"
  }
}

// Notification (high priority)
{
  "type": "notification",
  "session_id": "sess_xxx",
  "notification_id": "notif_xxx",
  "message": "Great news! Sarah is available...",
  "priority": "interrupt"
}

// Latency Report
{
  "type": "latency",
  "data": {
    "stt_ms": 450,
    "llm_ms": 1200,
    "tts_ms": 380,
    "total_ms": 2100
  }
}

// Heartbeat
{"type": "ping"}
{"type": "pong"}
{"type": "heartbeat"}
```

---

## Background Task System

### Task Lifecycle

```
1. User requests escalation
         │
         ▼
2. EscalationAgent creates BackgroundTask
   ├── task_id: "esc_{session}_{timestamp}"
   ├── task_type: HUMAN_ESCALATION
   └── status: PENDING
         │
         ▼
3. asyncio.create_task() spawns worker
         │
         ▼
4. Worker updates status to RUNNING
         │
    ┌────┴────┐
    │ 5-25s   │  (simulated check)
    │  wait   │
    └────┬────┘
         │
         ▼
5. Worker creates Notification
   ├── priority: INTERRUPT (if available)
   └── priority: HIGH (if callback scheduled)
         │
         ▼
6. Notification added to state
         │
         ▼
7. Voice worker receives via WebSocket
   └── Speaks notification immediately
         │
         ▼
8. Next user turn: check_notifications
   └── Processes any remaining notifications
```

---

## Security Considerations

### Current Implementation

1. **CORS**: Currently allows all origins (`*`) - should be restricted in production
2. **LiveKit tokens**: Generated per-session with limited grants
3. **No authentication**: Sessions are anonymous - add auth for production
4. **SQL injection**: Protected by SQLAlchemy ORM
5. **Env secrets**: API keys in environment variables

### Production Recommendations

1. Restrict CORS to specific origins
2. Add user authentication (JWT, OAuth)
3. Rate limiting on API endpoints
4. HTTPS for all traffic
5. Network isolation for internal services
6. Secret management (Vault, AWS Secrets Manager)

---

## Performance Characteristics

### Latency Breakdown (Typical)

| Stage | Target | Actual (observed) |
|-------|--------|-------------------|
| VAD Detection | <100ms | ~50ms |
| STT (Whisper base) | <500ms | 300-800ms |
| LangGraph (with LLM) | <2000ms | 800-2500ms |
| TTS (Kokoro) | <300ms | 100-300ms |
| Audio Streaming | <100ms | ~50ms |
| **Total** | **<3s** | **1.5-4s** |

### Scaling Considerations

1. **LangGraph**: Stateless per request, scales horizontally
2. **Redis**: Single instance sufficient for moderate load
3. **Whisper**: GPU-bound, consider multiple workers for high concurrency
4. **LiveKit**: Supports many rooms, may need multiple servers for scale
5. **Database**: SQLite is single-writer, migrate to PostgreSQL for scale

---

## Monitoring & Observability

### Current Logging

- `structlog` for structured JSON logging
- Per-request logging with session_id
- Latency tracking per voice interaction
- Tool call tracing (when DEBUG=true)

### Recommended Additions

1. **Prometheus metrics**: Request latency, error rates
2. **Distributed tracing**: OpenTelemetry spans
3. **Alerting**: On error rate spikes, latency degradation
4. **Dashboards**: Grafana for visualization

---

## Known Issues & Technical Debt

### 1. State Serialization Complexity

**Issue**: Custom message serialization/deserialization needed
**Impact**: Added complexity, potential bugs
**Fix**: Consider LangGraph's native checkpointing or simpler state

### 2. Slot Update Side Effects

**Issue**: `slot_tools.py` uses module-level dict for pending updates
**Impact**: Not thread-safe, could leak between requests
**Fix**: Pass updates through return values or use request-scoped storage

### 3. No Request-Level Logging Correlation

**Issue**: Difficult to trace full request lifecycle
**Impact**: Debugging complex issues is challenging
**Fix**: Add request-id header, propagate through all services

### 4. TTS Fallback Missing

**Issue**: If Edge TTS fails, no fallback
**Impact**: Voice goes silent
**Fix**: Add fallback to Piper TTS on failure

### 5. No Graceful Shutdown

**Issue**: Voice worker doesn't gracefully drain
**Impact**: Calls may be interrupted on restart
**Fix**: Add SIGTERM handler, wait for active calls

---

## Development Workflow

### Local Development

```bash
# Start infrastructure only
docker-compose up -d livekit redis

# Run app locally
cd app && uvicorn app.main:app --reload

# Run voice worker locally
cd voice_worker && python -m voice_worker.main

# Run frontend locally
cd frontend && npm run dev
```

### Docker Development

```bash
# Full stack
docker-compose up -d --build

# View logs
docker-compose logs -f app voice-worker

# Restart single service
docker-compose restart app

# Rebuild single service
docker-compose up -d --build app
```

### Testing

```bash
# API health
curl http://localhost:8000/health

# Create and test session
SESSION=$(curl -s -X POST http://localhost:8000/api/sessions | jq -r '.session_id')
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"session_id\": \"$SESSION\", \"message\": \"Hello\"}"
```

---

## Deployment Checklist

- [ ] Set production OpenAI API key
- [ ] Configure proper CORS origins
- [ ] Set up HTTPS with valid certificates
- [ ] Configure Redis persistence
- [ ] Set appropriate log levels
- [ ] Review resource limits (CPU, memory, GPU)
- [ ] Set up monitoring and alerting
- [ ] Configure backup strategy
- [ ] Test failover scenarios
- [ ] Document runbooks for common issues
