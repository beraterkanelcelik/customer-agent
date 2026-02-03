import asyncio
import json
import logging
from typing import Dict, Optional, Any, Tuple
from datetime import datetime
import redis.asyncio as redis
from redis.exceptions import WatchError

from app.config import get_settings
from app.schemas.state import ConversationState
from app.schemas.task import BackgroundTask, Notification
from app.schemas.enums import TaskStatus, TaskType

settings = get_settings()
logger = logging.getLogger("app.background.state_store")

# Maximum retries for optimistic locking
MAX_RETRIES = 3


class StateStore:
    """
    Shared state store for conversation sessions.

    Uses Redis for production, falls back to in-memory for development.
    """

    def __init__(self):
        self._memory_store: Dict[str, dict] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._redis: Optional[redis.Redis] = None
        self._use_redis = "redis://" in settings.redis_url

    async def connect(self):
        """Initialize Redis connection."""
        if self._use_redis:
            self._redis = redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            # Test connection
            try:
                await self._redis.ping()
                print("Connected to Redis")
            except Exception as e:
                print(f"Redis connection failed, using memory: {e}")
                self._use_redis = False

    async def disconnect(self):
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()

    def _get_lock(self, session_id: str) -> asyncio.Lock:
        """Get or create lock for session."""
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]

    async def get_state(self, session_id: str) -> Optional[ConversationState]:
        """Get conversation state for session."""
        if self._use_redis:
            data = await self._redis.get(f"session:{session_id}")
            if data:
                parsed = json.loads(data)
                msg_count = len(parsed.get("messages", []))
                logger.info(f"[{session_id}] Redis get: found {msg_count} messages in stored data")

                # Log customer data from stored JSON
                customer_json = parsed.get("customer", {})
                logger.info(f"[{session_id}] Redis customer JSON: id={customer_json.get('customer_id')}, name={customer_json.get('name')}, is_identified={customer_json.get('is_identified')}")

                # Log message structure for debugging
                for i, msg in enumerate(parsed.get("messages", [])[:3]):
                    logger.info(f"[{session_id}]   stored msg[{i}]: type={msg.get('type')}, content={str(msg.get('content', ''))[:30]}...")
                state = ConversationState(**parsed)
                logger.info(f"[{session_id}] After deserialization: {len(state.messages)} messages")

                # Log customer after deserialization
                logger.info(f"[{session_id}] After deser customer: id={state.customer.customer_id}, name={state.customer.name}, is_identified={state.customer.is_identified}")

                return state
            logger.info(f"[{session_id}] Redis get: no data found")
            return None
        else:
            async with self._get_lock(session_id):
                data = self._memory_store.get(session_id)
                if data:
                    msg_count = len(data.get("messages", []))
                    logger.info(f"[{session_id}] Memory get: found {msg_count} messages")
                    return ConversationState(**data)
                logger.info(f"[{session_id}] Memory get: no data found")
                return None

    async def get_state_with_version(self, session_id: str) -> Tuple[Optional[ConversationState], int]:
        """Get conversation state and its version for optimistic locking."""
        state = await self.get_state(session_id)
        if state:
            return state, state.version
        return None, 0

    async def get_or_create_state(self, session_id: str) -> ConversationState:
        """Get existing state or create a new one."""
        state = await self.get_state(session_id)
        if state:
            return state

        # Create new state
        state = ConversationState(session_id=session_id)
        await self.set_state(session_id, state)
        logger.info(f"[{session_id}] Created new conversation state")
        return state

    async def set_state(self, session_id: str, state: ConversationState):
        """Save conversation state."""
        state.last_updated = datetime.utcnow()
        data = state.model_dump(mode="json")
        msg_count = len(data.get("messages", []))
        logger.info(f"[{session_id}] Saving state with {msg_count} messages")

        # Log customer data for debugging
        customer_data = data.get("customer", {})
        logger.info(f"[{session_id}] Saving customer: id={customer_data.get('customer_id')}, name={customer_data.get('name')}, is_identified={customer_data.get('is_identified')}")

        # Log message structure for debugging
        for i, msg in enumerate(data.get("messages", [])[:3]):  # First 3 messages
            logger.info(f"[{session_id}]   serialized msg[{i}]: type={msg.get('type')}, content={str(msg.get('content', ''))[:30]}...")

        if self._use_redis:
            await self._redis.set(
                f"session:{session_id}",
                json.dumps(data, default=str),
                ex=settings.session_timeout_minutes * 60
            )
            logger.info(f"[{session_id}] Saved to Redis")
        else:
            async with self._get_lock(session_id):
                self._memory_store[session_id] = data
            logger.info(f"[{session_id}] Saved to memory")

    async def set_state_if_version(
        self,
        session_id: str,
        state: ConversationState,
        expected_version: int
    ) -> bool:
        """
        Save state only if version matches (optimistic locking).

        Returns True if save succeeded, False if version conflict.
        """
        key = f"session:{session_id}"

        if self._use_redis:
            try:
                async with self._redis.pipeline(transaction=True) as pipe:
                    await pipe.watch(key)
                    current_data = await self._redis.get(key)

                    if current_data:
                        current_version = json.loads(current_data).get("version", 0)
                        if current_version != expected_version:
                            await pipe.unwatch()
                            logger.warning(
                                f"[{session_id}] Version conflict: expected {expected_version}, "
                                f"found {current_version}"
                            )
                            return False

                    # Increment version and save
                    state.version = expected_version + 1
                    state.last_updated = datetime.utcnow()
                    data = state.model_dump(mode="json")

                    pipe.multi()
                    pipe.set(key, json.dumps(data, default=str), ex=settings.session_timeout_minutes * 60)
                    await pipe.execute()

                    logger.info(f"[{session_id}] Saved with version {state.version}")
                    return True

            except WatchError:
                logger.warning(f"[{session_id}] WatchError during save, version conflict")
                return False
        else:
            # Memory store with lock-based optimistic check
            async with self._get_lock(session_id):
                current_data = self._memory_store.get(session_id)
                if current_data:
                    current_version = current_data.get("version", 0)
                    if current_version != expected_version:
                        logger.warning(
                            f"[{session_id}] Version conflict: expected {expected_version}, "
                            f"found {current_version}"
                        )
                        return False

                state.version = expected_version + 1
                state.last_updated = datetime.utcnow()
                self._memory_store[session_id] = state.model_dump(mode="json")
                logger.info(f"[{session_id}] Saved with version {state.version}")
                return True

    async def update_state(self, session_id: str, updates: dict):
        """Partial update of state."""
        state = await self.get_state(session_id)
        if state:
            for key, value in updates.items():
                if hasattr(state, key):
                    setattr(state, key, value)
            await self.set_state(session_id, state)

    async def add_task(self, session_id: str, task: BackgroundTask):
        """Add a background task to session."""
        state = await self.get_state(session_id)
        if state:
            state.pending_tasks.append(task)
            await self.set_state(session_id, state)

    async def update_task(self, session_id: str, task_id: str, updates: dict):
        """Update a specific task."""
        state = await self.get_state(session_id)
        if state:
            for task in state.pending_tasks:
                if task.task_id == task_id:
                    for key, value in updates.items():
                        if hasattr(task, key):
                            setattr(task, key, value)
                    break
            await self.set_state(session_id, state)

    async def add_notification(self, session_id: str, notification: Notification):
        """Add notification to session queue."""
        state = await self.get_state(session_id)
        if state:
            state.notifications_queue.append(notification)
            await self.set_state(session_id, state)

    async def append_notification_atomic(self, session_id: str, notification: Notification) -> bool:
        """
        Atomically append notification using separate Redis key.

        This avoids race conditions with main state updates.
        """
        notif_key = f"notifications:{session_id}"
        notif_data = json.dumps(notification.model_dump(mode="json"), default=str)

        if self._use_redis:
            await self._redis.rpush(notif_key, notif_data)
            await self._redis.expire(notif_key, settings.session_timeout_minutes * 60)
            logger.info(f"[{session_id}] Appended notification atomically: {notification.notification_id}")
            return True
        else:
            # Fallback to regular method for memory store
            await self.add_notification(session_id, notification)
            return True

    async def mark_notification_delivered(self, session_id: str, notification_id: str) -> bool:
        """
        Mark a notification as delivered (sent via WebSocket callback).

        Uses a separate Redis SET to track delivered notification IDs.
        """
        delivered_key = f"delivered_notifications:{session_id}"

        if self._use_redis:
            await self._redis.sadd(delivered_key, notification_id)
            await self._redis.expire(delivered_key, settings.session_timeout_minutes * 60)
            logger.info(f"[{session_id}] Marked notification as delivered: {notification_id}")
            return True
        else:
            # For memory store, update the notification in state directly
            state = await self.get_state(session_id)
            if state:
                for notif in state.notifications_queue:
                    if notif.notification_id == notification_id:
                        notif.delivered = True
                        break
                await self.set_state(session_id, state)
            return True

    async def is_notification_delivered(self, session_id: str, notification_id: str) -> bool:
        """Check if a notification was already delivered via WebSocket."""
        delivered_key = f"delivered_notifications:{session_id}"

        if self._use_redis:
            return await self._redis.sismember(delivered_key, notification_id)
        else:
            state = await self.get_state(session_id)
            if state:
                for notif in state.notifications_queue:
                    if notif.notification_id == notification_id:
                        return notif.delivered
            return False

    async def get_pending_notifications(self, session_id: str) -> list[Notification]:
        """Get all pending notifications from atomic queue."""
        notif_key = f"notifications:{session_id}"

        if self._use_redis:
            notifications = []
            while True:
                data = await self._redis.lpop(notif_key)
                if not data:
                    break
                notif_dict = json.loads(data)
                notifications.append(Notification(**notif_dict))
            return notifications
        else:
            # For memory store, get from state
            state = await self.get_state(session_id)
            if state:
                undelivered = [n for n in state.notifications_queue if not n.delivered]
                return undelivered
            return []

    async def get_task_from_atomic(self, session_id: str, task_id: str) -> Optional[BackgroundTask]:
        """
        Get task from atomic storage (independent of main state).

        This allows broadcasting task updates even before the main state is saved.
        Falls back to main state if no atomic data exists.
        """
        if self._use_redis:
            task_key = f"task:{session_id}:{task_id}"
            task_data = await self._redis.get(task_key)
            if task_data:
                data = json.loads(task_data)
                return BackgroundTask(**data)

        # Fallback: try to get from main state
        state = await self.get_state(session_id)
        if state:
            for task in state.pending_tasks:
                if task.task_id == task_id:
                    return task

        return None

    async def init_task_atomic(
        self,
        session_id: str,
        task_id: str,
        task_type: TaskType
    ) -> bool:
        """
        Initialize a task in atomic storage with all required fields.

        This should be called at the start of a background task to ensure
        the task data exists in atomic storage before any updates.
        """

        task_key = f"task:{session_id}:{task_id}"

        task_data = {
            "task_id": task_id,
            "task_type": task_type.value if hasattr(task_type, 'value') else task_type,
            "status": TaskStatus.PENDING.value,
            "created_at": datetime.utcnow().isoformat(),
            "completed_at": None,
            "result": None,
            "human_available": None,
            "human_agent_id": None,
            "human_agent_name": None,
            "callback_scheduled": None
        }

        if self._use_redis:
            await self._redis.set(
                task_key,
                json.dumps(task_data, default=str),
                ex=settings.session_timeout_minutes * 60
            )
            logger.info(f"[{session_id}] Initialized task {task_id} in atomic storage")
            return True
        else:
            # For memory store, no special handling needed
            return True

    async def update_task_atomic(
        self,
        session_id: str,
        task_id: str,
        updates: dict
    ) -> bool:
        """
        Atomically update a task using separate Redis key.

        This stores task updates separately to avoid conflicts with main state.
        """
        task_key = f"task:{session_id}:{task_id}"

        if self._use_redis:
            # Get existing task data or create new
            existing = await self._redis.get(task_key)
            if existing:
                task_data = json.loads(existing)
            else:
                task_data = {"task_id": task_id}

            # Apply updates
            for key, value in updates.items():
                if hasattr(value, 'model_dump'):
                    task_data[key] = value.model_dump(mode="json")
                elif hasattr(value, 'value'):  # Enum
                    task_data[key] = value.value
                elif isinstance(value, datetime):
                    task_data[key] = value.isoformat()
                else:
                    task_data[key] = value

            await self._redis.set(
                task_key,
                json.dumps(task_data, default=str),
                ex=settings.session_timeout_minutes * 60
            )
            logger.info(f"[{session_id}] Updated task {task_id} atomically")
            return True
        else:
            # Fallback to regular update for memory store
            await self.update_task(session_id, task_id, updates)
            return True

    async def sync_atomic_updates_to_state(self, session_id: str) -> Optional[ConversationState]:
        """
        Merge atomic notifications and task updates back into main state.

        Call this at the start of a new turn to consolidate updates.
        """
        state, version = await self.get_state_with_version(session_id)
        if not state:
            return None

        modified = False

        # Merge pending notifications
        pending_notifs = await self.get_pending_notifications(session_id)
        if pending_notifs:
            # Check which notifications were already delivered via WebSocket
            for notif in pending_notifs:
                if await self.is_notification_delivered(session_id, notif.notification_id):
                    notif.delivered = True
                    logger.info(f"[{session_id}] Notification {notif.notification_id} already delivered via WebSocket")
            state.notifications_queue.extend(pending_notifs)
            modified = True
            logger.info(f"[{session_id}] Merged {len(pending_notifs)} notifications into state")

        # Merge task updates from atomic keys
        if self._use_redis:
            for task in state.pending_tasks:
                task_key = f"task:{session_id}:{task.task_id}"
                task_data = await self._redis.get(task_key)
                if task_data:
                    updates = json.loads(task_data)
                    for key, value in updates.items():
                        if key != "task_id" and hasattr(task, key):
                            setattr(task, key, value)
                    # Clear the atomic key
                    await self._redis.delete(task_key)
                    modified = True
                    logger.info(f"[{session_id}] Merged task {task.task_id} updates")

        if modified:
            # Save with version check
            success = await self.set_state_if_version(session_id, state, version)
            if success:
                return state
            else:
                # Retry on conflict
                return await self.sync_atomic_updates_to_state(session_id)

        return state

    async def delete_session(self, session_id: str):
        """Delete a session."""
        if self._use_redis:
            await self._redis.delete(f"session:{session_id}")
        else:
            async with self._get_lock(session_id):
                self._memory_store.pop(session_id, None)

    async def get_voice_worker_status(self) -> dict:
        """Get voice worker model loading status."""
        if self._use_redis:
            data = await self._redis.get("voice_worker:status")
            if data:
                return json.loads(data)
        return {"ready": False, "stt_loaded": False, "tts_loaded": False}

    async def set_voice_worker_status(self, status: dict):
        """Set voice worker model loading status."""
        if self._use_redis:
            await self._redis.set(
                "voice_worker:status",
                json.dumps(status),
                ex=300  # 5 minute expiry - worker should refresh
            )


# Global instance
state_store = StateStore()
