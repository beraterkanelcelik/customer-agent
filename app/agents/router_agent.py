from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from typing import Optional
import json

from app.config import get_settings
from app.schemas.enums import IntentType

settings = get_settings()


class RouterOutput(BaseModel):
    """Structured output from router."""
    intent: IntentType
    confidence: float = Field(ge=0.0, le=1.0)
    entities: dict = Field(default_factory=dict)
    reasoning: str


ROUTER_SYSTEM_PROMPT = """You are an intent classifier for Springfield Auto car dealership voice agent.

Analyze the user's message and classify it into exactly ONE intent.

=== INTENTS (in priority order) ===

1. book_test_drive: User wants to test drive, see a car, schedule test drive, book test drive
   - Examples: "I want to book a test drive", "test drive", "I'd like to see a car", "can I test drive"
   - Keywords: test drive, see a car, try a vehicle, check out a car

2. book_service: User wants to schedule service appointment (oil change, repairs, maintenance)
   - Examples: "I need an oil change", "my car needs service", "schedule maintenance"
   - Keywords: oil change, brake repair, service appointment, maintenance, inspection

3. faq: Questions about dealership (hours, location, services, pricing, financing)
   - Examples: "What are your hours?", "Do you have financing?", "Where are you located?"

4. reschedule: User wants to change/move an EXISTING appointment
   - Examples: "I need to reschedule", "can I change my appointment"

5. cancel: User wants to cancel an EXISTING appointment
   - Examples: "I need to cancel", "please cancel my appointment"

6. escalation: User explicitly asks for human, manager, or is frustrated
   - Examples: "Let me talk to a person", "I want to speak to a manager"

7. greeting: Simple hello/hi at conversation start
   - Examples: "Hello", "Hi there", "Good morning"

8. goodbye: Ending conversation
   - Examples: "Bye", "Thanks, that's all", "Goodbye"

9. general: ONLY use if message truly doesn't fit any above category
   - This should be RARE - most messages fit a category above

=== IMPORTANT ===
- "test drive" ALWAYS means book_test_drive intent
- Even with speech-to-text errors like "test driver" or "test drvie", classify as book_test_drive
- When in doubt between general and a specific intent, choose the specific intent

CRITICAL: EXTRACT ALL ENTITIES - even if the message is just providing info:
- phone: ANY sequence of numbers that could be a phone (e.g., "155 133 2123", "one five five one three three", "155-1332123")
  - Convert spoken numbers: "one"=1, "two"=2, "three"=3, "four"=4, "five"=5, "six"=6, "seven"=7, "eight"=8, "nine"=9, "zero"=0
  - Remove dashes, spaces, parentheses - just extract the digits
- name: Customer's name (e.g., "Berat Erkan", "my name is John Smith")
- email: Email address - watch for spoken format like "john at gmail dot com" -> "john@gmail.com"
  - Convert "at" to "@" and "dot" to "."
- service_type: "oil change", "brake repair", "tire rotation", etc.
- vehicle_make: "Toyota", "Honda", "Volkswagen", etc.
- vehicle_model: "Camry", "Civic", "Golf", etc.
- date: Any mentioned date
- time: Any mentioned time

IMPORTANT RULES:
1. If user provides phone/name/email, ALWAYS extract them even if intent is just "general"
2. For numbers spoken as words, convert to digits (e.g., "one five five" -> "155")
3. Phone numbers might be partial - extract whatever digits are provided
4. This is voice input from speech-to-text, so expect some transcription errors

Respond with valid JSON only:
{
  "intent": "<intent>",
  "confidence": <0.0-1.0>,
  "entities": {"key": "value"},
  "reasoning": "<brief explanation>"
}
"""


class RouterAgent:
    """Routes user messages to appropriate specialist agents."""

    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.openai_model,
            temperature=0,
            api_key=settings.openai_api_key
        )

    async def classify(
        self,
        user_message: str,
        conversation_history: str = ""
    ) -> RouterOutput:
        """Classify user intent and extract entities."""
        import logging
        logger = logging.getLogger("app.agents.router")

        logger.info(f"[ROUTER] Classifying message: '{user_message}'")

        # Quick keyword check for common intents (fallback safety)
        msg_lower = user_message.lower()
        keyword_intent = None
        if any(kw in msg_lower for kw in ["test drive", "test-drive", "testdrive", "try a car", "see a car"]):
            keyword_intent = IntentType.BOOK_TEST_DRIVE
        elif any(kw in msg_lower for kw in ["oil change", "service", "maintenance", "repair", "brake"]):
            keyword_intent = IntentType.BOOK_SERVICE
        elif any(kw in msg_lower for kw in ["reschedule", "change my appointment", "move my appointment"]):
            keyword_intent = IntentType.RESCHEDULE
        elif any(kw in msg_lower for kw in ["cancel", "cancel my"]):
            keyword_intent = IntentType.CANCEL

        context = ""
        if conversation_history:
            context = f"\n\nRecent conversation:\n{conversation_history}\n"

        messages = [
            SystemMessage(content=ROUTER_SYSTEM_PROMPT),
            HumanMessage(content=f"{context}User message: {user_message}")
        ]

        response = await self.llm.ainvoke(messages)
        logger.info(f"[ROUTER] LLM response: {response.content[:200]}...")

        try:
            # Parse JSON response
            content = response.content.strip()
            # Handle markdown code blocks
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]

            data = json.loads(content)
            intent = IntentType(data.get("intent", "general"))
            confidence = float(data.get("confidence", 0.5))

            logger.info(f"[ROUTER] Parsed intent: {intent.value}, confidence: {confidence}")

            # If LLM classified as general but we detected keyword, use keyword intent
            if intent == IntentType.GENERAL and keyword_intent is not None:
                logger.info(f"[ROUTER] Overriding 'general' with keyword-detected intent: {keyword_intent.value}")
                intent = keyword_intent
                confidence = 0.8

            return RouterOutput(
                intent=intent,
                confidence=confidence,
                entities=data.get("entities", {}),
                reasoning=data.get("reasoning", "")
            )
        except Exception as e:
            logger.error(f"[ROUTER] Parse error: {e}, response was: {response.content}")

            # Use keyword fallback if available
            if keyword_intent is not None:
                logger.info(f"[ROUTER] Using keyword fallback: {keyword_intent.value}")
                return RouterOutput(
                    intent=keyword_intent,
                    confidence=0.7,
                    entities={},
                    reasoning=f"Keyword detection fallback (parse error: {str(e)})"
                )

            # Default fallback
            return RouterOutput(
                intent=IntentType.GENERAL,
                confidence=0.3,
                entities={},
                reasoning=f"Parse error: {str(e)}"
            )

    def get_next_node(self, intent: IntentType) -> str:
        """Map intent to next graph node."""
        mapping = {
            IntentType.FAQ: "faq_agent",
            IntentType.BOOK_SERVICE: "booking_agent",
            IntentType.BOOK_TEST_DRIVE: "booking_agent",
            IntentType.RESCHEDULE: "booking_agent",
            IntentType.CANCEL: "booking_agent",
            IntentType.ESCALATION: "escalation_agent",
            IntentType.GREETING: "respond",
            IntentType.GOODBYE: "respond",
            IntentType.GENERAL: "respond",
        }
        return mapping.get(intent, "respond")
