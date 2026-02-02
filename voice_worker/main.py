import asyncio
import logging
import sys

from livekit import rtc
from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli

from .agent import DealershipVoiceAgent
from .config import get_voice_settings
from .stt import stt

settings = get_voice_settings()

# Kokoro TTS
from .tts_kokoro import kokoro_tts_instance as tts

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("voice_worker")


async def entrypoint(ctx: JobContext):
    """
    Main entrypoint for the voice agent.

    This follows the 0.8+ pattern:
    1. Register event handlers BEFORE connecting
    2. Call ctx.connect() to initiate connection
    3. Run agent logic after connection
    """
    logger.info(f"Agent job started for room: {ctx.room.name}")

    # Create agent instance
    agent = DealershipVoiceAgent()

    # Initialize agent (load models if not preloaded)
    await agent.initialize()

    # Register event handlers BEFORE connecting to avoid race conditions
    @ctx.room.on("track_subscribed")
    def on_track_subscribed(
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant
    ):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            # Only process audio from users, not from other agents
            if participant.identity.startswith("user_"):
                logger.info(f"Subscribed to audio from user: {participant.identity}")
                asyncio.create_task(agent.process_audio_track(track))
            else:
                logger.info(f"Ignoring audio from non-user: {participant.identity}")

    @ctx.room.on("participant_connected")
    def on_participant_connected(participant: rtc.RemoteParticipant):
        logger.info(f"Participant connected: {participant.identity}")

    @ctx.room.on("participant_disconnected")
    def on_participant_disconnected(participant: rtc.RemoteParticipant):
        logger.info(f"Participant disconnected: {participant.identity}")

    @ctx.room.on("disconnected")
    def on_disconnected():
        logger.info("Room disconnected")
        agent.stop()

    # Register shutdown callback for cleanup
    async def shutdown_callback():
        logger.info("Shutdown callback triggered")
        await agent.cleanup()

    ctx.add_shutdown_callback(shutdown_callback)

    # Connect to the room with auto-subscribe for audio only
    logger.info("Connecting to room...")
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    logger.info(f"Connected to room: {ctx.room.name}")

    # Run the agent
    try:
        await agent.run(ctx)
    except Exception as e:
        logger.error(f"Agent error: {e}", exc_info=True)
    finally:
        await agent.cleanup()
        logger.info("Agent job completed")


def update_status_in_redis(status: dict):
    """Update voice worker status in Redis."""
    import redis
    try:
        r = redis.from_url(settings.redis_url)
        import json
        r.set("voice_worker:status", json.dumps(status), ex=300)
        r.close()
    except Exception as e:
        logger.warning(f"Failed to update Redis status: {e}")


def preload_models():
    """Preload ML models at startup for faster first response."""
    logger.info("Preloading models...")

    status = {"ready": False, "stt_loaded": False, "tts_loaded": False}
    update_status_in_redis(status)

    try:
        stt.load_model()
        status["stt_loaded"] = True
        update_status_in_redis(status)
        logger.info("STT model loaded")
    except Exception as e:
        logger.error(f"Failed to load STT model: {e}")

    try:
        tts.load_model()
        status["tts_loaded"] = True
        update_status_in_redis(status)
        logger.info("TTS model loaded")
    except Exception as e:
        logger.error(f"Failed to load TTS model: {e}")

    status["ready"] = status["stt_loaded"] and status["tts_loaded"]
    update_status_in_redis(status)
    logger.info("Model preloading complete")


if __name__ == "__main__":
    logger.info("Starting Voice Worker...")
    logger.info(f"LiveKit URL: {settings.livekit_url}")
    logger.info(f"App API URL: {settings.app_api_url}")
    logger.info(f"Whisper model: {settings.whisper_model} (device: {settings.whisper_device})")
    logger.info(f"Kokoro TTS voice: {settings.kokoro_voice}")

    # Preload models
    preload_models()

    logger.info("Starting LiveKit agent worker...")

    # Add 'start' command if not provided
    if len(sys.argv) == 1:
        sys.argv.append("start")

    # Use the new 0.8+ pattern with entrypoint_fnc
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
            ws_url=settings.livekit_url,
        )
    )
