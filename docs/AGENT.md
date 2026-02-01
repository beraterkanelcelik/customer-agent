# AGENT.md - Project Build Guide
## Car Dealership Voice Agent - Build Instructions for Claude Code

---

# IMPORTANT: READ THIS FIRST

You are building a **Car Dealership Voice Agent** (CARA8-style) from a 6-part PRD. This file guides you through the entire build process.

## Key Rules

1. **Always check `progress.md` first** - See what's already done
2. **Update `progress.md` after each task** - Track your progress
3. **Follow the PRD parts in order** - They build on each other
4. **Test after each phase** - Don't move on if something is broken
5. **Keep sessions resumable** - User will close/reopen sessions

---

# PROJECT OVERVIEW

## What We're Building

A real-time voice customer service agent for car dealerships with:
- Multi-agent LangGraph orchestration (Router → FAQ/Booking/Escalation)
- Async background tasks (human escalation doesn't block conversation)
- Voice via LiveKit + Faster-Whisper (STT) + Piper (TTS)
- React dashboard showing real-time agent state
- SQLite database with customers, appointments, FAQ

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | FastAPI + LangGraph + SQLAlchemy |
| Voice | LiveKit + Faster-Whisper + Piper |
| Frontend | React + Vite + TailwindCSS |
| Database | SQLite (async) |
| State | Redis (or in-memory) |
| Containers | Docker Compose (5 services) |

---

# PROGRESS TRACKING

## First Task: Create progress.md

If `progress.md` doesn't exist, create it with this template:

```markdown
# Project Progress Tracker

## Current Status
Phase: NOT_STARTED
Last Updated: [timestamp]
Last Task Completed: None

## Phase Checklist

### Phase 1: Project Setup & Docker [NOT_STARTED]
- [ ] Create directory structure
- [ ] Create docker-compose.yml
- [ ] Create Dockerfile.app
- [ ] Create Dockerfile.voice
- [ ] Create frontend/Dockerfile
- [ ] Create requirements.txt
- [ ] Create requirements-voice.txt
- [ ] Create .env.example
- [ ] Create docker/entrypoint.sh
- [ ] Verify: `docker-compose config` works

### Phase 2: Database & Schemas [NOT_STARTED]
- [ ] Create app/config.py
- [ ] Create app/schemas/enums.py
- [ ] Create app/schemas/customer.py
- [ ] Create app/schemas/appointment.py
- [ ] Create app/schemas/task.py
- [ ] Create app/schemas/state.py
- [ ] Create app/schemas/api.py
- [ ] Create app/database/models.py
- [ ] Create app/database/connection.py
- [ ] Verify: Database initializes with seed data

### Phase 3: LangGraph Agents [NOT_STARTED]
- [ ] Create app/agents/router_agent.py
- [ ] Create app/agents/faq_agent.py
- [ ] Create app/agents/booking_agent.py
- [ ] Create app/agents/escalation_agent.py
- [ ] Create app/agents/response_generator.py
- [ ] Create app/agents/graph.py
- [ ] Create app/agents/__init__.py
- [ ] Verify: Graph compiles without errors

### Phase 4: Tools & Background Tasks [NOT_STARTED]
- [ ] Create app/tools/faq_tools.py
- [ ] Create app/tools/customer_tools.py
- [ ] Create app/tools/booking_tools.py
- [ ] Create app/tools/__init__.py
- [ ] Create app/background/state_store.py
- [ ] Create app/background/worker.py
- [ ] Create app/background/__init__.py
- [ ] Create app/services/conversation.py
- [ ] Verify: Tools work with test queries

### Phase 5: FastAPI Application [NOT_STARTED]
- [ ] Create app/api/deps.py
- [ ] Create app/api/routes.py
- [ ] Create app/api/websocket.py
- [ ] Create app/main.py
- [ ] Verify: API starts and /health returns 200

### Phase 6: Voice Worker [NOT_STARTED]
- [ ] Create voice_worker/config.py
- [ ] Create voice_worker/stt.py
- [ ] Create voice_worker/tts.py
- [ ] Create voice_worker/agent.py
- [ ] Create voice_worker/main.py
- [ ] Create voice_worker/__init__.py
- [ ] Verify: Voice worker starts without errors

### Phase 7: Frontend Dashboard [NOT_STARTED]
- [ ] Create frontend/package.json
- [ ] Create frontend/vite.config.js
- [ ] Create frontend/tailwind.config.js
- [ ] Create frontend/index.html
- [ ] Create frontend/src/main.jsx
- [ ] Create frontend/src/App.jsx
- [ ] Create frontend/src/styles/main.css
- [ ] Create all components (6 files)
- [ ] Create hooks (2 files)
- [ ] Verify: Frontend builds and displays

### Phase 8: Integration & Testing [NOT_STARTED]
- [ ] Docker compose up works
- [ ] All services healthy
- [ ] Chat API works end-to-end
- [ ] WebSocket updates work
- [ ] Voice call connects
- [ ] Demo scenarios pass

## Session Log
| Session | Date | Tasks Completed |
|---------|------|-----------------|
| 1 | | |

## Notes
(Add any issues, blockers, or decisions here)
```

---

# BUILD PHASES

## Phase 1: Project Setup & Docker

**PRD Reference:** Part 1

**Tasks:**
1. Create the directory structure:
```
car-dealership-voice-agent/
├── docker/
├── app/
│   ├── api/
│   ├── database/
│   ├── schemas/
│   ├── agents/
│   ├── tools/
│   ├── background/
│   └── services/
├── voice_worker/
├── frontend/
│   └── src/
│       ├── components/
│       ├── hooks/
│       └── styles/
├── data/
├── models/
└── logs/
```

2. Create Docker files from PRD Part 1:
   - `docker-compose.yml`
   - `docker/Dockerfile.app`
   - `docker/Dockerfile.voice`
   - `docker/entrypoint.sh`
   - `frontend/Dockerfile`
   - `frontend/nginx.conf`

3. Create dependency files:
   - `requirements.txt`
   - `requirements-voice.txt`
   - `.env.example`

**Verification:**
```bash
docker-compose config  # Should show valid config
```

**Update progress.md when done!**

---

## Phase 2: Database & Schemas

**PRD Reference:** Part 2

**Tasks:**
1. Create `app/__init__.py` (empty)
2. Create `app/config.py` - Pydantic settings
3. Create all schema files:
   - `app/schemas/__init__.py`
   - `app/schemas/enums.py`
   - `app/schemas/customer.py`
   - `app/schemas/appointment.py`
   - `app/schemas/task.py`
   - `app/schemas/state.py` (LangGraph state)
   - `app/schemas/api.py`

4. Create database files:
   - `app/database/__init__.py`
   - `app/database/models.py` (SQLAlchemy)
   - `app/database/connection.py` (with init_db & seed)

**Verification:**
```python
# Test script
from app.database.connection import init_db
init_db()
print("Database initialized!")
```

**Update progress.md when done!**

---

## Phase 3: LangGraph Agents

**PRD Reference:** Part 3

**Tasks:**
1. Create agent files:
   - `app/agents/__init__.py`
   - `app/agents/router_agent.py`
   - `app/agents/faq_agent.py`
   - `app/agents/booking_agent.py`
   - `app/agents/escalation_agent.py`
   - `app/agents/response_generator.py`
   - `app/agents/graph.py` (main graph definition)

**Verification:**
```python
# Test script
from app.agents.graph import conversation_graph
print("Graph nodes:", conversation_graph.nodes)
print("Graph compiled successfully!")
```

**Update progress.md when done!**

---

## Phase 4: Tools & Background Tasks

**PRD Reference:** Part 4

**Tasks:**
1. Create tool files:
   - `app/tools/__init__.py`
   - `app/tools/faq_tools.py`
   - `app/tools/customer_tools.py`
   - `app/tools/booking_tools.py`

2. Create background task files:
   - `app/background/__init__.py`
   - `app/background/state_store.py`
   - `app/background/worker.py`

3. Create service files:
   - `app/services/__init__.py`
   - `app/services/conversation.py`

**Verification:**
```python
# Test tools
from app.tools.faq_tools import search_faq
result = await search_faq("hours")
print(result)
```

**Update progress.md when done!**

---

## Phase 5: FastAPI Application

**PRD Reference:** Part 6 (Section 1)

**Tasks:**
1. Create API files:
   - `app/api/__init__.py`
   - `app/api/deps.py`
   - `app/api/routes.py`
   - `app/api/websocket.py`

2. Create main app:
   - `app/main.py`

**Verification:**
```bash
# Start the app
uvicorn app.main:app --reload

# Test health
curl http://localhost:8000/health
```

**Update progress.md when done!**

---

## Phase 6: Voice Worker

**PRD Reference:** Part 5

**Tasks:**
1. Create voice worker files:
   - `voice_worker/__init__.py`
   - `voice_worker/config.py`
   - `voice_worker/stt.py`
   - `voice_worker/tts.py`
   - `voice_worker/agent.py`
   - `voice_worker/main.py`

**Verification:**
```python
# Test TTS
from voice_worker.tts import tts
tts.load_model()
audio = tts.synthesize("Hello, this is a test.")
print(f"Generated {len(audio)} bytes of audio")
```

**Update progress.md when done!**

---

## Phase 7: Frontend Dashboard

**PRD Reference:** Part 6 (Sections 2-4)

**Tasks:**
1. Create config files:
   - `frontend/package.json`
   - `frontend/vite.config.js`
   - `frontend/tailwind.config.js`
   - `frontend/postcss.config.js`
   - `frontend/index.html`

2. Create React app:
   - `frontend/src/main.jsx`
   - `frontend/src/App.jsx`
   - `frontend/src/styles/main.css`

3. Create components:
   - `frontend/src/components/CallButton.jsx`
   - `frontend/src/components/Transcript.jsx`
   - `frontend/src/components/AgentState.jsx`
   - `frontend/src/components/BookingSlots.jsx`
   - `frontend/src/components/TaskMonitor.jsx`
   - `frontend/src/components/CustomerInfo.jsx`

4. Create hooks:
   - `frontend/src/hooks/useWebSocket.js`
   - `frontend/src/hooks/useLiveKit.js`

**Verification:**
```bash
cd frontend
npm install
npm run dev
# Open http://localhost:5173
```

**Update progress.md when done!**

---

## Phase 8: Integration & Testing

**Tasks:**
1. Start all services:
```bash
docker-compose up -d
docker-compose ps  # All should be healthy
```

2. Test each component:
   - [ ] Health check: `curl localhost:8000/health`
   - [ ] Create session: `POST /api/sessions`
   - [ ] Chat: `POST /api/chat`
   - [ ] WebSocket: Connect to `/ws/{session_id}`
   - [ ] Frontend: Opens and displays correctly
   - [ ] Voice: Can start call and hear agent

3. Run demo scenarios:
   - [ ] FAQ: "What are your hours?"
   - [ ] Booking: "I need an oil change tomorrow"
   - [ ] Escalation: "I want to speak to someone"

**Update progress.md with COMPLETED status!**

---

# SESSION MANAGEMENT

## Starting a New Session

When the user opens a new chat session:

1. **Read progress.md** to understand current state
2. **Announce what's next**: "Based on progress.md, we're on Phase X. Next task is..."
3. **Continue from where we left off**

## Ending a Session

Before the user closes the session:

1. **Update progress.md** with completed tasks
2. **Add session to the log table**
3. **Note any blockers or issues**

## Example Session Start Message

```
I've checked progress.md. Here's where we are:

**Current Phase:** Phase 3 - LangGraph Agents
**Completed:** 
- ✅ Phase 1: Project Setup & Docker
- ✅ Phase 2: Database & Schemas
**In Progress:**
- router_agent.py ✅
- faq_agent.py ✅
- booking_agent.py ⏳ (next)

Let me continue with booking_agent.py...
```

---

# TROUBLESHOOTING

## Common Issues

### Docker Issues
```bash
# Reset everything
docker-compose down -v
rm -rf data/dealership.db
docker-compose up -d --build
```

### Database Issues
```python
# Reinitialize
from app.database.connection import init_db
init_db()
```

### Import Errors
- Check `__init__.py` files exist
- Check relative imports use correct paths
- Verify all dependencies in requirements.txt

### LangGraph Issues
- Ensure state schema matches node return types
- Check all edges are defined
- Verify conditional routing returns valid node names

---

# QUICK REFERENCE

## File Locations by PRD Part

| PRD Part | Creates These Files |
|----------|---------------------|
| Part 1 | docker/, requirements.txt, .env.example |
| Part 2 | app/config.py, app/schemas/*, app/database/* |
| Part 3 | app/agents/* |
| Part 4 | app/tools/*, app/background/*, app/services/* |
| Part 5 | voice_worker/* |
| Part 6 | app/api/*, app/main.py, frontend/* |

## Key Commands

```bash
# Build & start
docker-compose up -d --build

# View logs
docker-compose logs -f app
docker-compose logs -f voice-worker

# Restart service
docker-compose restart app

# Shell into container
docker-compose exec app bash

# Run Python in container
docker-compose exec app python -c "from app.database.connection import init_db; init_db()"
```

---

# FINAL NOTES

1. **Quality over speed** - Make sure each phase works before moving on
2. **Copy code exactly** - PRD has tested, working code
3. **Update progress.md** - This is critical for session continuity
4. **Test incrementally** - Don't wait until the end to test
5. **Ask if stuck** - User can provide clarification

Good luck! 🚀
