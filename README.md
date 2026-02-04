# Customer Agent

A production-ready real-time voice AI customer service agent for car dealerships, powered by LangGraph and Twilio Media Streams.

## Overview

Customer Agent is an intelligent voice assistant that handles customer inquiries via phone calls. It can answer FAQs, book service appointments and test drives, look up customer information, and seamlessly escalate to human agents when needed.

### Key Features

- **Natural Voice Conversations** - Real-time speech-to-text (Faster-Whisper) and text-to-speech (Kokoro) for natural dialogue
- **Unified AI Agent** - Single LangGraph agent handles all conversation types (FAQ, booking, escalation)
- **Intelligent Booking** - Slot-filling workflow for scheduling service appointments and test drives
- **Human Escalation** - Seamless transfer to human agents via Twilio Conference when needed
- **Real-time Dashboard** - React frontend showing live transcripts, agent state, and booking progress
- **Barge-in Support** - Users can interrupt the AI while it's speaking

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│     Twilio      │────▶│    FastAPI      │────▶│     Redis       │
│  Media Streams  │     │    Backend      │     │   State Store   │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                               │
                               ▼
                        ┌─────────────────┐
                        │   LangGraph     │
                        │   Agent Loop    │
                        └─────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
       ┌───────────┐    ┌───────────┐    ┌───────────┐
       │  Faster   │    │   OpenAI  │    │   Kokoro  │
       │  Whisper  │    │ GPT-4.1   │    │    TTS    │
       │   (STT)   │    │   mini    │    │           │
       └───────────┘    └───────────┘    └───────────┘
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| **Backend** | FastAPI + LangGraph + SQLAlchemy (async) |
| **LLM** | OpenAI GPT-4.1-mini |
| **Voice STT** | Faster-Whisper (GPU-accelerated) |
| **Voice TTS** | Kokoro-82M |
| **Telephony** | Twilio Media Streams |
| **State Store** | Redis |
| **Database** | SQLite (aiosqlite) |
| **Frontend** | React 18 + Vite + TailwindCSS |
| **Containerization** | Docker Compose |

## Prerequisites

- **Docker** and **Docker Compose** (v2.0+)
- **NVIDIA GPU** with CUDA support (recommended for STT/TTS)
- **OpenAI API Key**
- **Twilio Account** with a phone number (for voice features)
- **ngrok** or similar tunnel (for local development with Twilio)

## Quick Start

### 1. Clone and Configure

```bash
git clone https://github.com/yourusername/customer-agent.git
cd customer-agent

# Copy environment template
cp .env.example .env
```

### 2. Set Environment Variables

Edit `.env` with your credentials:

```env
# Required - OpenAI
OPENAI_API_KEY=sk-your-api-key-here
OPENAI_MODEL=gpt-4.1-mini

# Required for Voice - Twilio
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_PHONE_NUMBER=+15551234567
TWILIO_WEBHOOK_BASE_URL=https://your-ngrok-url.ngrok.io
CUSTOMER_SERVICE_PHONE=+15559876543
```

### 3. Start Services

```bash
# Build and start all containers
docker-compose up -d --build

# Verify health
curl http://localhost:8000/health
```

### 4. Open Dashboard

Navigate to [http://localhost:5173](http://localhost:5173) to view the real-time dashboard.

### 5. Make a Test Call

Call your Twilio phone number to start a conversation with the AI agent.

---

## Twilio Setup Guide

### Step 1: Create Twilio Account

1. Sign up at [https://console.twilio.com](https://console.twilio.com)
2. Complete phone verification
3. Note your **Account SID** and **Auth Token** from the dashboard

### Step 2: Get a Phone Number

1. Go to **Phone Numbers** > **Manage** > **Buy a number**
2. Select a number with **Voice** capability
3. Purchase the number

### Step 3: Set Up ngrok (Local Development)

Twilio needs to reach your local server via HTTPS:

```bash
# Install ngrok
# macOS
brew install ngrok

# Windows (Chocolatey)
choco install ngrok

# Linux
snap install ngrok

# Start tunnel
ngrok http 8000
```

Copy the HTTPS URL (e.g., `https://abc123.ngrok-free.app`)

### Step 4: Configure Twilio Webhooks

In Twilio Console, go to **Phone Numbers** > **Manage** > **Active Numbers** > Select your number:

**Voice Configuration:**
| Setting | Value |
|---------|-------|
| Configure with | Webhook |
| A call comes in | `https://your-ngrok-url/api/voice/incoming` (HTTP POST) |
| Call status changes | `https://your-ngrok-url/api/voice/status` (HTTP POST) |

### Step 5: Update Environment

```env
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_PHONE_NUMBER=+15551234567
TWILIO_WEBHOOK_BASE_URL=https://your-ngrok-url.ngrok-free.app
CUSTOMER_SERVICE_PHONE=+15559876543  # Number for human escalation
```

### Step 6: Restart and Test

```bash
docker-compose restart app

# Call your Twilio number
# Watch the dashboard at http://localhost:5173
```

---

## Configuration Reference

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | Yes | - | OpenAI API key |
| `OPENAI_MODEL` | No | `gpt-4.1-mini` | OpenAI model to use |
| `TWILIO_ACCOUNT_SID` | For voice | - | Twilio Account SID |
| `TWILIO_AUTH_TOKEN` | For voice | - | Twilio Auth Token |
| `TWILIO_PHONE_NUMBER` | For voice | - | Your Twilio phone number |
| `TWILIO_WEBHOOK_BASE_URL` | For voice | - | Public URL for Twilio webhooks |
| `CUSTOMER_SERVICE_PHONE` | For escalation | - | Human agent phone number |
| `REDIS_URL` | No | `redis://redis:6379/0` | Redis connection URL |
| `DATABASE_URL` | No | `sqlite+aiosqlite:///./data/dealership.db` | Database URL |
| `WHISPER_MODEL` | No | `medium` | Whisper model size |
| `WHISPER_DEVICE` | No | `cuda` | STT device (cuda/cpu) |
| `WHISPER_COMPUTE_TYPE` | No | `int8` | Whisper compute type |
| `KOKORO_VOICE` | No | `af_heart` | TTS voice selection |
| `KOKORO_LANG` | No | `a` | TTS language (a=American) |
| `DEBUG` | No | `true` | Enable debug logging |
| `LOG_LEVEL` | No | `INFO` | Log level |

### Docker Services

| Service | Port | Description |
|---------|------|-------------|
| `app` | 8000 | FastAPI backend with GPU support |
| `frontend` | 5173 | React dashboard |
| `redis` | 6379 | State store |

---

## API Reference

### Session Management

```bash
# Create session
POST /api/sessions
Content-Type: application/json
{}

# Get session
GET /api/sessions/{session_id}

# End session
DELETE /api/sessions/{session_id}
```

### Chat (Text Mode)

```bash
# Send message
POST /api/chat
Content-Type: application/json
{
  "session_id": "sess_xxxx",
  "message": "What are your hours?"
}
```

### Voice Status

```bash
# Check STT/TTS model status
GET /api/voice/status
```

### Data Endpoints

```bash
GET /api/faq                    # List FAQ entries
GET /api/services               # List services
GET /api/inventory              # List vehicles
GET /api/availability           # Get appointment slots
GET /api/customers/{phone}      # Get customer by phone
GET /api/appointments           # List appointments
```

---

## Development

### Project Structure

```
customer-agent/
├── app/                    # FastAPI backend
│   ├── agents/             # LangGraph agent
│   ├── api/                # REST & WebSocket endpoints
│   ├── background/         # State store, async workers
│   ├── database/           # SQLAlchemy models
│   ├── schemas/            # Pydantic models
│   ├── services/           # Business logic
│   └── tools/              # LangChain tools
├── frontend/               # React dashboard
├── docker/                 # Dockerfiles
├── data/                   # SQLite database
├── models/                 # ML models (auto-downloaded)
├── cache/                  # Model caches
└── logs/                   # Application logs
```

### Running Locally (Without Docker)

```bash
# Backend
cd app
pip install -r ../requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Frontend
cd frontend
npm install
npm run dev
```

### Viewing Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f app
```

### Common Commands

```bash
# Rebuild after code changes
docker-compose up -d --build

# Restart specific service
docker-compose restart app

# Stop all services
docker-compose down

# Reset data (removes volumes)
docker-compose down -v
```

---

## Troubleshooting

### Voice Not Working

1. **Check ngrok is running**: `ngrok http 8000`
2. **Verify webhook URL** in Twilio Console matches your ngrok URL
3. **Check Twilio credentials** in `.env`
4. **View logs**: `docker-compose logs -f app`

### STT/TTS Models Not Loading

1. **Check GPU**: `nvidia-smi`
2. **If no GPU**, set `WHISPER_DEVICE=cpu` in `.env`
3. **Check model status**: `curl http://localhost:8000/api/voice/status`
4. Models download on first use (~2-3GB)

### Redis Connection Failed

- Falls back to in-memory automatically
- Check Redis is running: `docker-compose ps`

### Agent Not Responding

1. **Verify OpenAI API key** is valid
2. **Check logs**: `docker-compose logs -f app`
3. Look for LLM errors or rate limiting

---

## License

MIT

---

## Support

For issues and feature requests, please open an issue on GitHub.
