# Car Dealership Voice Agent - PRD Part 1 of 6
## Project Overview & Docker Setup

---

# SECTION 1: PROJECT OVERVIEW

## 1.1 What We're Building

A real-time voice customer service agent for car dealerships (CARA8-style) with:
- **FAQ answering** - Hours, location, services, financing
- **Appointment scheduling** - Service appointments & test drives  
- **Human escalation** - Async background task with callback
- **Real-time dashboard** - Shows agent state, transcript, tasks

## 1.2 Tech Stack

| Component | Technology |
|-----------|------------|
| LLM | OpenAI GPT-4 |
| Agent Framework | LangGraph 0.2.x |
| Backend API | FastAPI |
| Database | SQLite + SQLAlchemy (async) |
| State Store | Redis |
| Voice Infrastructure | LiveKit (self-hosted) |
| STT | Faster-Whisper |
| TTS | Piper |
| Frontend | React + Vite + TailwindCSS |
| Containerization | Docker Compose |

## 1.3 Key Architecture Decisions

1. **Multi-container setup** - Separate containers for app, voice-worker, frontend, livekit, redis
2. **Async background tasks** - Human escalation doesn't block conversation
3. **Pydantic everywhere** - All state, API, and config uses Pydantic models
4. **LangGraph for orchestration** - Multi-agent routing with shared state

---

# SECTION 2: DOCKER SETUP

## 2.1 Container Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                  Docker Network: dealership-net                  │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────┐  │
│  │ livekit  │  │  redis   │  │ frontend │  │  voice-worker  │  │
│  │  :7880   │  │  :6379   │  │  :5173   │  │  (no port)     │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └───────┬────────┘  │
│       │             │             │                │            │
│       └─────────────┴──────┬──────┴────────────────┘            │
│                            │                                     │
│                     ┌──────┴──────┐                             │
│                     │     app     │                             │
│                     │   :8000     │                             │
│                     │  (FastAPI)  │                             │
│                     └──────┬──────┘                             │
│                            │                                     │
│                     ┌──────┴──────┐                             │
│                     │   SQLite    │                             │
│                     │  (volume)   │                             │
│                     └─────────────┘                             │
└─────────────────────────────────────────────────────────────────┘
```

## 2.2 docker-compose.yml

```yaml
version: '3.8'

services:
  # ============================================
  # LiveKit Server - WebRTC Infrastructure
  # ============================================
  livekit:
    image: livekit/livekit-server:latest
    container_name: livekit
    restart: unless-stopped
    ports:
      - "7880:7880"
      - "7881:7881"
      - "7882:7882/udp"
    environment:
      - LIVEKIT_KEYS=devkey:secret
    command: --dev --bind 0.0.0.0
    networks:
      - dealership-net
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:7880"]
      interval: 10s
      timeout: 5s
      retries: 5

  # ============================================
  # Redis - Shared State Store
  # ============================================
  redis:
    image: redis:7-alpine
    container_name: redis
    restart: unless-stopped
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes
    networks:
      - dealership-net
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  # ============================================
  # FastAPI Application - Main Backend
  # ============================================
  app:
    build:
      context: .
      dockerfile: docker/Dockerfile.app
    container_name: app
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - LIVEKIT_URL=ws://livekit:7880
      - LIVEKIT_API_KEY=devkey
      - LIVEKIT_API_SECRET=secret
      - REDIS_URL=redis://redis:6379/0
      - DATABASE_URL=sqlite+aiosqlite:///./data/dealership.db
      - DEBUG=true
      - LOG_LEVEL=INFO
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    depends_on:
      livekit:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - dealership-net
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 5s
      retries: 5

  # ============================================
  # Voice Worker - STT/TTS + LiveKit Agent
  # ============================================
  voice-worker:
    build:
      context: .
      dockerfile: docker/Dockerfile.voice
    container_name: voice-worker
    restart: unless-stopped
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - LIVEKIT_URL=ws://livekit:7880
      - LIVEKIT_API_KEY=devkey
      - LIVEKIT_API_SECRET=secret
      - APP_API_URL=http://app:8000
      - REDIS_URL=redis://redis:6379/0
      - WHISPER_MODEL=base
      - WHISPER_DEVICE=cpu
      - PIPER_VOICE=en_US-amy-medium
    volumes:
      - ./models:/app/models
    depends_on:
      app:
        condition: service_healthy
      livekit:
        condition: service_healthy
    networks:
      - dealership-net

  # ============================================
  # Frontend - React Dashboard
  # ============================================
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: frontend
    restart: unless-stopped
    ports:
      - "5173:80"
    environment:
      - VITE_API_URL=http://localhost:8000
      - VITE_WS_URL=ws://localhost:8000
      - VITE_LIVEKIT_URL=ws://localhost:7880
    depends_on:
      - app
    networks:
      - dealership-net

networks:
  dealership-net:
    driver: bridge

volumes:
  redis_data:
```

## 2.3 docker/Dockerfile.app

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app/ ./app/
COPY database/ ./database/

# Create directories
RUN mkdir -p /app/data /app/logs

# Entrypoint script
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## 2.4 docker/Dockerfile.voice

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# System dependencies for audio
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements-voice.txt .
RUN pip install --no-cache-dir -r requirements-voice.txt

# Download Piper voice model
RUN mkdir -p /app/models/piper && \
    curl -L -o /app/models/piper/en_US-amy-medium.onnx \
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx" && \
    curl -L -o /app/models/piper/en_US-amy-medium.onnx.json \
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json"

# Copy application
COPY voice_worker/ ./voice_worker/

CMD ["python", "-m", "voice_worker.main"]
```

## 2.5 frontend/Dockerfile

```dockerfile
# Build stage
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Production stage
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

## 2.6 docker/entrypoint.sh

```bash
#!/bin/bash
set -e

echo "Starting Car Dealership Voice Agent..."

# Initialize database if needed
if [ ! -f /app/data/dealership.db ]; then
    echo "Initializing database..."
    python -c "from app.database.connection import init_db; init_db()"
    echo "Database initialized successfully."
fi

# Execute main command
exec "$@"
```

## 2.7 frontend/nginx.conf

```nginx
server {
    listen 80;
    server_name localhost;
    root /usr/share/nginx/html;
    index index.html;

    # SPA routing
    location / {
        try_files $uri $uri/ /index.html;
    }

    # API proxy (optional, for same-origin)
    location /api {
        proxy_pass http://app:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }

    # WebSocket proxy
    location /ws {
        proxy_pass http://app:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "Upgrade";
        proxy_set_header Host $host;
    }
}
```

## 2.8 requirements.txt (Main App)

```txt
# Web Framework
fastapi==0.109.0
uvicorn[standard]==0.27.0
python-multipart==0.0.6
websockets==12.0

# LangGraph & LangChain
langgraph==0.2.60
langchain==0.3.14
langchain-openai==0.3.0
langchain-core==0.3.29

# Database
sqlalchemy[asyncio]==2.0.25
aiosqlite==0.19.0

# Redis
redis==5.0.1

# Pydantic
pydantic==2.6.1
pydantic-settings==2.1.0

# HTTP
httpx==0.26.0
aiohttp==3.9.3

# Utils
python-dotenv==1.0.1
structlog==24.1.0
```

## 2.9 requirements-voice.txt

```txt
# LiveKit
livekit==0.11.1
livekit-agents==0.7.2

# STT
faster-whisper==1.0.1

# TTS
piper-tts==1.2.0

# HTTP
httpx==0.26.0
aiohttp==3.9.3

# Redis
redis==5.0.1

# Utils
python-dotenv==1.0.1
structlog==24.1.0
numpy==1.26.3
```

## 2.10 .env.example

```env
# Required
OPENAI_API_KEY=sk-your-key-here

# LiveKit
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret

# Database
DATABASE_URL=sqlite+aiosqlite:///./data/dealership.db

# Redis  
REDIS_URL=redis://localhost:6379/0

# Voice
WHISPER_MODEL=base
WHISPER_DEVICE=cpu
PIPER_VOICE=en_US-amy-medium

# App
DEBUG=true
LOG_LEVEL=INFO

# Background Tasks
HUMAN_CHECK_MIN_SECONDS=5
HUMAN_CHECK_MAX_SECONDS=10
HUMAN_AVAILABILITY_CHANCE=0.6
```

---

# SECTION 3: PROJECT STRUCTURE

```
car-dealership-voice-agent/
├── docker-compose.yml
├── .env.example
├── .env
├── requirements.txt
├── requirements-voice.txt
├── docker/
│   ├── Dockerfile.app
│   ├── Dockerfile.voice
│   └── entrypoint.sh
├── data/                    # SQLite DB (gitignored)
├── models/                  # Voice models (gitignored)
├── logs/                    # Logs (gitignored)
├── database/
│   └── schema.sql
├── app/                     # FastAPI app (Part 2-4)
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── api/
│   ├── database/
│   ├── schemas/
│   ├── agents/
│   ├── tools/
│   ├── background/
│   └── services/
├── voice_worker/            # Voice processing (Part 5)
│   ├── __init__.py
│   ├── main.py
│   ├── agent.py
│   ├── stt.py
│   └── tts.py
├── frontend/                # React dashboard (Part 6)
│   ├── Dockerfile
│   ├── nginx.conf
│   ├── package.json
│   └── src/
└── tests/
```

---

**END OF PART 1**

Say "continue" to get Part 2: Pydantic Schemas & Database Models
