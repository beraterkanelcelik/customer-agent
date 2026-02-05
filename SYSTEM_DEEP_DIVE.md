# Complete System Deep Dive — Customer Agent for Car Dealerships

## 1. HIGH-LEVEL ARCHITECTURE

The system has **5 major layers**:

```
┌──────────────────────────────────────────────────────────────┐
│                      CUSTOMER (Phone)                         │
└──────────┬───────────────────────────────────────────────────┘
           │ PSTN call
┌──────────▼───────────────────────────────────────────────────┐
│                      TWILIO CLOUD                             │
│  - Phone number receives calls                                │
│  - Sends webhooks to your server                              │
│  - Opens WebSocket for bidirectional audio (Media Streams)    │
│  - Makes outbound calls to sales when escalation needed       │
└──────────┬───────────────────────────────────────────────────┘
           │ HTTPS webhooks + WSS media stream
┌──────────▼───────────────────────────────────────────────────┐
│                    FASTAPI BACKEND                             │
│  ┌────────────┐  ┌──────────────┐  ┌───────────────────────┐ │
│  │ Voice      │  │ Conversation │  │ Background Worker     │ │
│  │ Routes     │  │ Service      │  │ (sales ring, email)   │ │
│  └─────┬──────┘  └──────┬───────┘  └───────────────────────┘ │
│        │                │                                     │
│  ┌─────▼──────┐  ┌──────▼───────┐  ┌───────────────────────┐ │
│  │ Twilio     │  │ LangGraph    │  │ State Store           │ │
│  │ Voice Svc  │  │ Agent        │  │ (Redis/memory)        │ │
│  └─────┬──────┘  └──────┬───────┘  └───────────────────────┘ │
│        │                │                                     │
│  ┌─────▼────────────────▼───────┐                             │
│  │ Audio Processor              │                             │
│  │ STT: Faster-Whisper (GPU)    │                             │
│  │ TTS: Kokoro-82M (GPU)        │                             │
│  └──────────────────────────────┘                             │
└──────────────────────────────────────────────────────────────┘
           │ WebSocket
┌──────────▼───────────────────────────────────────────────────┐
│            REACT DASHBOARD (Vite + TailwindCSS)               │
│  - Real-time transcript                                       │
│  - Agent state visualization                                  │
│  - Booking slots progress                                     │
│  - Escalation status                                          │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. INCOMING CALL FLOW — Step by Step

### Step 1: Customer dials your Twilio number

Twilio receives the PSTN call and sends an HTTP POST to your webhook:

**`POST /api/voice/incoming`** (`voice_routes.py`)

Parameters received: `CallSid`, `From` (caller's phone), `To` (your Twilio number)

### Step 2: Server registers the call and returns TwiML

```python
# Register the call in memory
twilio_voice.register_call(CallSid, session_id, from_number=From)

# Creates an ActiveCall object tracked by 3 maps:
#   _active_calls[call_sid] -> ActiveCall
#   _stream_to_call[stream_sid] -> call_sid
#   _session_to_call[session_id] -> call_sid
```

It also initializes `ConversationState` in Redis/memory via `state_store.get_or_create_state()`.

Then it returns TwiML that tells Twilio: **"open a WebSocket to my server"**:

```xml
<Response>
  <Connect>
    <Stream url="wss://your-ngrok.ngrok.io/api/voice/media-stream">
      <Parameter name="session_id" value="sess_abc123"/>
      <Parameter name="call_sid" value="CA..."/>
    </Stream>
  </Connect>
</Response>
```

### Step 3: Twilio opens a WebSocket (Media Stream)

Twilio connects to **`WS /api/voice/media-stream`** (`voice_routes.py`).

Events flow:

1. **`connected`** — WebSocket handshake done
2. **`start`** — Stream metadata arrives (streamSid, callSid, custom params)
3. **`media`** — Audio chunks (base64-encoded mu-law, 8kHz, 20ms frames)
4. **`stop`** — Stream ended

### Step 4: Welcome message (no hardcoded text!)

On the `start` event, for a new session:

```python
# Send [CALL_STARTED] marker to LangGraph agent
result = await conversation_service.process_voice_message(
    session_id=session_id,
    user_message="[CALL_STARTED]"  # Special marker
)
welcome_text = result.get("response", "")
```

The **AI agent** sees `[CALL_STARTED]` in its system prompt instruction and generates a natural greeting. This is a key design principle: **zero hardcoded spoken messages** — the LLM generates everything.

The welcome text then goes through TTS (Kokoro) -> WAV 24kHz -> mu-law 8kHz -> streamed back to Twilio in 20ms chunks.

### Step 5: Event poller starts

```python
# Background task that checks for proactive events
event_poller_task = asyncio.create_task(
    event_poller(websocket, stream_sid, session_id)
)
```

This polls every 1 second for events like escalation results that need to be proactively spoken to the customer without waiting for their input.

---

## 3. VOICE PROCESSING PIPELINE — Each Audio Chunk

For every `media` event (every ~20ms of audio):

### VAD (Voice Activity Detection) — `twilio_voice.py`

```
Audio chunk (base64 mu-law)
  -> decode base64
  -> convert mu-law to linear PCM (audioop.ulaw2lin)
  -> calculate RMS energy (audioop.rms)
  -> Compare against SILENCE_THRESHOLD = 500
```

**State machine:**

- Energy > 500 -> speech detected, buffer audio
- Energy < 500 for 30 consecutive frames (~600ms) -> end of utterance
- Minimum 5 frames (~100ms) of speech to count as real speech (filters noise)

**Barge-in:** If the system is playing audio (`is_playing_audio=True`) and the user starts speaking, it sets `barge_in_requested=True`. The `send_audio_to_stream` function checks this flag every chunk and sends a `clear` event to Twilio to stop buffered audio.

### STT — `audio_processor.py` + `twilio_voice.py`

```
mu-law 8kHz buffer
  -> audioop.ulaw2lin (to linear PCM)
  -> audioop.ratecv (8kHz -> 16kHz)
  -> WAV header prepended
  -> Faster-Whisper transcribes
```

Whisper is configured with:

- `beam_size=5`, `best_of=3` — accuracy over speed
- `vad_filter=True` — Whisper's own VAD as second pass
- Domain-specific `initial_prompt` with car dealership vocabulary

### LLM Processing — `conversation_service.py`

```
user_message (transcribed text)
  -> conversation_service.process_voice_message()
    -> state_store.get_state() with optimistic locking
    -> process_message() through LangGraph graph
    -> graph: preprocess -> agent -> (tools loop) -> postprocess
    -> state_store.set_state_if_version() (retry on conflict)
    -> return {response, needs_escalation, should_end, ...}
```

### TTS — `audio_processor.py`

```
AI response text
  -> Kokoro-82M generates float32 audio
  -> Convert to int16
  -> WAV 24kHz output
```

### Audio conversion and streaming — `voice_routes.py`

```
WAV 24kHz
  -> numpy array
  -> soxr high-quality resample to 8kHz
  -> normalize to prevent clipping
  -> audioop.lin2ulaw (PCM -> mu-law)
  -> base64 encode
  -> send in 160-byte chunks (20ms at 8kHz)
```

### Latency budget tracked per turn:

```
STT: ~500ms | LLM: ~2000ms | TTS: ~300ms | TOTAL: ~3s target
```

---

## 4. LANGGRAPH AGENT — The Brain

### Graph structure (`graph.py`):

```
preprocess -> agent -> [conditional] -> tools -> agent (loop)
                    -> postprocess -> END
```

### Single unified agent — WHY?

- No routing issues (can't lose context mid-booking)
- One state object, one conversation flow
- LLM decides everything via 15 tools
- Handles mixed intents naturally ("thanks, my name is John")

### The agent loop:

1. **Preprocess** — checks `notifications_queue` for background task results (escalation outcomes). Injects special markers like `[NOTIFICATION:human_available:John]`
2. **Agent** — builds full context (date, customer status, booking progress, escalation status), sends to GPT-4.1-mini with all tools bound
3. **Conditional** — if response has `tool_calls` -> go to tools node; otherwise -> postprocess
4. **Tools** — executes tool calls, injects `session_id` automatically
5. **Postprocess** — parses tool results, updates `booking_slots`, `customer`, `confirmed_appointment`, `escalation_in_progress`

### Context injection (`build_context()`):

Every turn, the agent gets injected context like:

```
INTERFACE: Voice call - Keep responses SHORT
TODAY: 2026-02-05 (Wednesday)
CUSTOMER: Not yet identified
BOOKING: No booking in progress
ESCALATION: In progress - Calling team member...
```

---

## 5. ESCALATION FLOW — Conference-based Call Forwarding

This is the core of Task 3. Here's exactly how it works:

### Phase 1: Customer requests human

Customer says "I want to talk to a real person" -> Whisper transcribes -> LLM sees this -> decides to call `request_human_agent` tool.

**`escalation_tools.py`** — The tool just returns a structured string:

```python
return f"ESCALATION_STARTED:task_id={task_id}|Call initiated to team member"
```

**`graph.py` postprocess** — Parses this and sets:

```python
updates["escalation_in_progress"] = True
updates["pending_tasks"] = [...new BackgroundTask...]
updates["waiting_for_background"] = True
```

### Phase 2: conversation_service detects escalation

**`conversation.py`** — After LangGraph returns:

```python
needs_escalation = chat_response.escalation_in_progress
```

### Phase 3: Twilio voice service starts the outbound call

**`twilio_voice.py`** — Back in `_process_utterance`:

```python
if needs_escalation and call.human_call_status == HumanCallStatus.NONE:
    asyncio.create_task(self._start_human_call_background(call, escalation_reason))
```

**KEY:** Customer stays talking to AI. The outbound call happens in background.

### Phase 4: Outbound call to sales (`twilio_voice.py`)

```python
human_call = self.client.calls.create(
    to=settings.customer_service_phone,     # Sales phone number
    from_=settings.twilio_phone_number,      # Your Twilio number
    url="/api/voice/human-answer?...",       # What to do when answered
    status_callback="/api/voice/human-status?...",  # Status updates
    status_callback_event=["initiated", "ringing", "answered", "completed"],
    timeout=45
)
```

A **watchdog task** (`_human_call_watchdog`) also starts — it polls the Twilio REST API every 5 seconds to catch missed callbacks.

### Phase 5: Status updates flow in real-time

**`POST /api/voice/human-status`** (`voice_routes.py`) receives:

- `initiated` -> `HumanCallStatus.CALLING`
- `ringing` -> `HumanCallStatus.RINGING`
- `in-progress` -> `HumanCallStatus.WAITING_CONFIRMATION` (NOT "answered" yet!)
- `busy/no-answer/failed` -> `HumanCallStatus.FAILED` + queue event for AI

Each update:

1. Updates in-memory `ActiveCall` state
2. Updates Redis `ConversationState` (so AI agent knows)
3. Sends WebSocket event to dashboard

When the call fails:

```python
self.queue_event(session_id, "escalation_failed", f"[ESCALATION_RETURNED:{status}]")
```

The **event poller** picks this up, sends it through LangGraph, and the AI tells the customer naturally.

### Phase 6: Call screening defeat (the clever part!)

**Problem:** When Twilio reports "answered", it might be call screening (Google Pixel, Samsung, etc.) — not a real human. If you bridge immediately, the customer hears silence or a robot.

**Solution: Two-step DTMF confirmation.**

**Step 1 — `/api/voice/human-answer`**:
When Twilio says "answered", return TwiML with `<Gather>`:

```xml
<Gather numDigits="1" action="/human-detected" timeout="10" finishOnKey="">
  <Say>Incoming customer call. Press any key to accept.</Say>
</Gather>
<Hangup/>  <!-- If no key pressed = call screening/voicemail -->
```

**Step 2 — `/api/voice/human-detected`**:
When ANY key is pressed (proves it's human, not call screening):

```xml
<Gather numDigits="1" action="/human-confirmed" timeout="10">
  <Say>You have an incoming customer call. [Name] needs help with [reason].
       Press 1 to accept, or any other key to decline.</Say>
</Gather>
```

**Step 3 — `/api/voice/human-confirmed`**:

- If `Digits == "1"` -> **ACCEPTED!** Transfer customer to conference
- Otherwise -> **DECLINED.** Hang up human, notify AI

### Phase 7: Conference bridge (customer transfer)

When human presses 1:

**`twilio_voice.py` -> `handle_human_confirmed()`:**

1. Sets `HumanCallStatus.CONFIRMED`
2. Updates Redis state
3. Starts `delayed_transfer()` (2s delay for "connecting you" to play)

**`twilio_voice.py` -> `transfer_customer_to_conference()`:**

```python
# Redirect customer's call leg to conference TwiML
self.client.calls(call.call_sid).update(
    url=f"/api/voice/escalate?session_id=...&conference=support_{session_id}",
    method="POST"
)
```

**`/api/voice/escalate`** returns:

```xml
<Dial>
  <Conference startConferenceOnEnter="true" endConferenceOnExit="true"
              waitUrl="hold-music-url">
    support_sess_abc123
  </Conference>
</Dial>
```

**Human joins the same conference** via `/human-confirmed` returning:

```xml
<Say>Connecting you to the customer now.</Say>
<Dial>
  <Conference startConferenceOnEnter="true" endConferenceOnExit="false">
    support_sess_abc123
  </Conference>
</Dial>
```

Note: `endConferenceOnExit=True` for customer, `False` for human. This means if the customer hangs up, conference ends. If the human hangs up, the conference ends too (because only the customer remains with `endConferenceOnExit=True`).

### Phase 8: Human hangs up -> return to AI

**`twilio_voice.py`** — When human call status = `completed` and was `IN_CONFERENCE`:

```python
await self.return_to_ai_conversation(session_id, reason="human_ended")
```

This redirects the customer's call to:

```
POST /api/voice/return-to-ai?session_id=...&reason=human_ended
```

Which returns TwiML that opens a **new media stream**:

```xml
<Connect>
  <Stream url="wss://...media-stream">
    <Parameter name="session_id" value="sess_abc123"/>
    <Parameter name="resumed" value="true"/>  <!-- KEY FLAG -->
  </Stream>
</Connect>
```

When the new stream starts with `resumed=true`:

```python
result = await conversation_service.process_voice_message(
    session_id=session_id,
    user_message=f"[ESCALATION_RETURNED:human_ended]"
)
```

The AI generates something like "The team member has left. Is there anything else I can help with?"

---

## 6. COMPLETE ESCALATION SEQUENCE DIAGRAM

```
CUSTOMER            TWILIO              YOUR SERVER           SALES PHONE
   │                  │                     │                     │
   │ "Transfer me"    │                     │                     │
   │ (via media WS)   │                     │                     │
   │ ────────────────>│ ───────────────────>│                     │
   │                  │                     │                     │
   │                  │    STT -> LLM calls │                     │
   │                  │    request_human_agent                    │
   │                  │                     │                     │
   │                  │    TTS: "I'm calling │                    │
   │ <────────────────│ <──a team member..." │                     │
   │                  │                     │                     │
   │  (customer stays │    calls.create()   │                     │
   │   talking to AI) │ <──────────────────│                     │
   │                  │                     │                     │
   │                  │ ────────────────────────────────────────>│
   │                  │                     │   Phone rings       │
   │                  │  status: ringing    │                     │
   │                  │ ───────────────────>│                     │
   │                  │                     │ -> dashboard WS     │
   │                  │                     │                     │
   │                  │                     │   Human answers     │
   │                  │ <────────────────────────────────────────│
   │                  │                     │                     │
   │                  │  TwiML: <Gather>    │                     │
   │                  │  "Press any key"    │                     │
   │                  │ ────────────────────────────────────────>│
   │                  │                     │                     │
   │                  │                     │   Presses key       │
   │                  │ <────────────────────────────────────────│
   │                  │                     │                     │
   │                  │  POST /human-detected                    │
   │                  │ ───────────────────>│                     │
   │                  │                     │                     │
   │                  │  TwiML: <Gather>    │                     │
   │                  │  "Press 1 to accept"│                     │
   │                  │ ────────────────────────────────────────>│
   │                  │                     │                     │
   │                  │                     │   Presses 1         │
   │                  │ <────────────────────────────────────────│
   │                  │                     │                     │
   │                  │  POST /human-confirmed                   │
   │                  │ ───────────────────>│                     │
   │                  │                     │ handle_human_confirmed()
   │                  │                     │                     │
   │                  │  Human TwiML:       │                     │
   │                  │  <Conference>       │                     │
   │                  │ ────────────────────────────────────────>│
   │                  │                     │   Human in conference│
   │                  │                     │                     │
   │                  │  2s delay...        │                     │
   │                  │                     │ transfer_customer()  │
   │                  │  calls(cust).update │                     │
   │                  │ <──────────────────│                     │
   │                  │                     │                     │
   │  Redirected to   │  /api/voice/escalate│                     │
   │  <Conference>    │ ───────────────────>│                     │
   │ ────────────────>│ <──TwiML: Conference│                     │
   │                  │                     │                     │
   │ ═══════════════════════════════════════════════════════════│
   │              CUSTOMER AND HUMAN NOW TALKING                 │
   │ ═══════════════════════════════════════════════════════════│
   │                  │                     │                     │
   │                  │                     │   Human hangs up    │
   │                  │ <────────────────────────────────────────│
   │                  │  status: completed  │                     │
   │                  │ ───────────────────>│                     │
   │                  │                     │ return_to_ai()      │
   │                  │  calls(cust).update │                     │
   │                  │ <──────────────────│                     │
   │                  │                     │                     │
   │  Redirected to   │  /return-to-ai      │                     │
   │  new <Stream>    │ ───────────────────>│                     │
   │ ────────────────>│ <──TwiML: new Stream│                     │
   │                  │                     │                     │
   │                  │  [ESCALATION_RETURNED:human_ended]        │
   │                  │ ───────────────────>│                     │
   │                  │                     │ AI generates response│
   │ <────────────────│ <──"Is there anything│                    │
   │  "anything else?"│    else I can help?" │                    │
   │                  │                     │                     │
```

---

## 7. STATE MANAGEMENT — Optimistic Locking

### The problem:

Background tasks (escalation) and the main conversation both update state concurrently.

### The solution:

**Optimistic locking** with version numbers (`state_store.py`):

```
1. get_state_with_version() -> state + version=5
2. Process through LangGraph (may take 2+ seconds)
3. set_state_if_version(state, expected_version=5)
   -> Redis WATCH key -> check version still 5 -> MULTI/SET -> EXEC
   -> If version changed (background updated it) -> retry (up to 3x)
```

### Atomic operations for background tasks:

To avoid conflicts, background tasks use **separate Redis keys**:

- `task:{session_id}:{task_id}` — task data
- `notifications:{session_id}` — notification queue (Redis LIST, atomic RPUSH)
- `delivered_notifications:{session_id}` — delivered tracking (Redis SET)

At the start of each turn, `sync_atomic_updates_to_state()` merges these back into the main state.

---

## 8. DASHBOARD REAL-TIME UPDATES

Every significant event sends a WebSocket message to the React dashboard:

| Event | Type | When |
|-------|------|------|
| `call_started` | New call | Incoming call webhook |
| `stream_started` | Audio connected | Media stream `start` event |
| `transcript` | User/AI message | After STT / after TTS |
| `state_update` | Full state | After each LLM turn |
| `human_status` | Escalation progress | calling/ringing/confirmed/failed |
| `latency` | Performance data | After each turn |
| `call_ended` | Call over | Hangup/disconnect |

Two WebSocket channels:

- `ws/{session_id}` — session-specific (used by per-call dashboard)
- `ws/sales` — sales staff dashboard (receives incoming call notifications, can accept/decline)

---

## 9. CALL STATE MACHINE

```
CONNECTING
    │
    ▼
AI_CONVERSATION  <──────────────────────────────────┐
    │                                                │
    ▼ (user speaks)                                  │
PROCESSING                                           │
    │                                                │
    ├── (normal response) ──> AI_CONVERSATION        │
    │                                                │
    ├── (needs_escalation) ──> ESCALATING            │
    │                              │                 │
    │                              ▼                 │
    │                         IN_CONFERENCE          │
    │                              │                 │
    │                              ▼ (human leaves)  │
    │                         return_to_ai() ────────┘
    │
    ├── (should_end) ──> ENDED
    │
    └── (error) ──> AI_CONVERSATION (retry)
```

### Human call status state machine:

```
NONE
  │
  ▼
CALLING ──> RINGING ──> WAITING_CONFIRMATION ──> CONFIRMED ──> IN_CONFERENCE ──> COMPLETED
  │            │              │                      │
  └────────────┴──────────────┴──────────────────────┘
              All can transition to FAILED
```

---

## 10. KEY DESIGN DECISIONS TO HIGHLIGHT IN INTERVIEW

1. **Zero hardcoded messages** — Every spoken word comes from the LLM via special markers (`[CALL_STARTED]`, `[ESCALATION_RETURNED:busy]`, etc.). This makes the system language-agnostic and tone-consistent.

2. **Customer never leaves platform control** — Unlike simple `<Dial>`, the customer stays in the media stream until the human is **confirmed** (pressed 1). Only then is the customer redirected to a conference.

3. **Two-step DTMF defeats call screening** — First keypress proves human presence, second keypress (1) confirms acceptance. Call screening and voicemail don't press keys.

4. **Local STT/TTS for latency and cost** — Faster-Whisper + Kokoro run on GPU locally. No API costs per call, no network latency for audio processing, better privacy.

5. **Barge-in support** — User can interrupt the AI mid-sentence. The system tracks `is_playing_audio` and sends Twilio `clear` events to stop buffered audio.

6. **Event poller for proactive AI** — Background escalation results are pushed to the customer without waiting for their next utterance. The AI speaks proactively.

7. **Watchdog for reliability** — If Twilio misses a status callback, the watchdog polls the REST API to detect stalled calls.

8. **Optimistic locking** — Concurrent state updates (main conversation + background tasks) are handled without locks using Redis WATCH + version numbers.

9. **Conference-based architecture** — Supports future extensions: warm transfers, multiple agent queues, supervisor barge/coach, per-participant recording.

10. **Single unified LangGraph agent** — No multi-agent routing complexity. One agent, 15 tools, the LLM decides everything. Handles mixed intents naturally ("thanks, also my name is John").

---

## 11. TECH STACK SUMMARY

| Component | Technology | Why |
|-----------|------------|-----|
| Backend | FastAPI | Async-first, WebSocket support, Pydantic integration |
| Agent Framework | LangGraph | Stateful agent with tool-calling loop, graph-based flow control |
| LLM | GPT-4.1-mini | Fast, cheap, good tool calling, good enough for voice |
| STT | Faster-Whisper (local GPU) | 4x faster than OpenAI Whisper, no API cost, ~500ms |
| TTS | Kokoro-82M (local GPU) | <2GB VRAM, high quality, ~300ms, no API cost |
| Voice Infra | Twilio Media Streams | Bidirectional audio WebSocket, conference support |
| State Store | Redis (memory fallback) | Sub-ms reads, atomic operations, TTL for cleanup |
| Database | SQLite (aiosqlite) | Simple, zero-config, async, good for single-server |
| Frontend | React 18 + Vite + Tailwind | Fast HMR, modern tooling, utility-first CSS |
| Containers | Docker Compose (3 services) | app + redis + frontend, single command deployment |

---

## 12. FILE REFERENCE

| File | What It Does |
|------|-------------|
| `app/agents/graph.py` | LangGraph workflow: preprocess -> agent -> tools -> postprocess |
| `app/services/twilio_voice.py` | All Twilio call management, VAD, escalation, conference |
| `app/services/audio_processor.py` | Faster-Whisper (STT) + Kokoro (TTS) local models |
| `app/services/conversation.py` | High-level conversation API with optimistic locking |
| `app/api/voice_routes.py` | All Twilio HTTP webhooks and WebSocket media stream |
| `app/api/websocket.py` | Dashboard WebSocket + Sales dashboard WebSocket |
| `app/background/state_store.py` | Redis/memory state with optimistic locking + atomic ops |
| `app/background/worker.py` | Background tasks (sales ring, email, callbacks) |
| `app/tools/escalation_tools.py` | `request_human_agent` tool for the LLM |
| `app/tools/call_tools.py` | `end_call` tool for the LLM |
| `app/tools/booking_tools.py` | Booking, rescheduling, cancellation tools |
| `app/tools/customer_tools.py` | Customer lookup and creation tools |
| `app/tools/faq_tools.py` | FAQ search and service listing tools |
| `app/tools/slot_tools.py` | Booking slot management tools |
| `app/schemas/state.py` | ConversationState — the single source of truth |
