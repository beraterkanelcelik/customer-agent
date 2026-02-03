# syntax=docker/dockerfile:1.5
# Use NVIDIA CUDA base image for GPU support (Faster-Whisper STT)
# Falls back gracefully to CPU if no GPU available
FROM nvidia/cuda:12.2.2-runtime-ubuntu22.04

# Install Python 3.11
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-venv \
    python3-pip \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# System dependencies
# - ffmpeg: audio conversion (MP3 to mulaw for Twilio)
# - espeak-ng: required by Kokoro TTS for phoneme generation
# - libsndfile1: audio file handling
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    espeak-ng \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies - use BuildKit cache for MUCH faster rebuilds
# ctranslate2 is already pulled by faster-whisper, no need to install separately
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Copy application (this layer changes often, but bind-mount overrides it in dev)
COPY app/ ./app/

# Create directories
RUN mkdir -p /app/data /app/logs /app/models

# Set CUDA environment
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility

# Entrypoint script
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
