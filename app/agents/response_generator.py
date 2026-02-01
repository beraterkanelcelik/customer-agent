"""
Response Generator - Clean LLM-driven response generation for simple intents.

Handles greetings, goodbyes, and general responses.
Full context injection via system prompt.
"""
import random
import logging

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from app.config import get_settings
from app.schemas.state import ConversationState

settings = get_settings()
logger = logging.getLogger("app.agents.response")


RESPONSE_SYSTEM_PROMPT = """You are a friendly voice agent for Springfield Auto dealership.

## CONVERSATION CONTEXT
{conversation_summary}

## CUSTOMER INFO
{customer_info}

## CURRENT INTENT
{intent}

## YOUR TASK
Generate a natural, helpful response to the customer's message.

## VOICE GUIDELINES
- Keep responses SHORT (1-3 sentences max)
- Use natural speech patterns
- Be warm and professional
- Don't use bullet points or lists
- Numbers should be spoken naturally ("two thirty" not "2:30")

## IMPORTANT
- If the customer seems to want something specific (test drive, service, info), offer to help
- Always be proactive - try to understand and address their needs
- Reference previous conversation context when relevant

Now respond to the customer naturally."""


GREETING_RESPONSES = [
    "Hello! Welcome to Springfield Auto. How can I help you today?",
    "Hi there! Thanks for calling Springfield Auto. What can I do for you?",
    "Good day! You've reached Springfield Auto. How may I assist you?",
]

GOODBYE_RESPONSES = [
    "Thank you for calling Springfield Auto! Have a great day!",
    "Thanks for reaching out! Take care and drive safe!",
    "It was my pleasure helping you. Goodbye!",
]


class ResponseGenerator:
    """
    Generates responses for simple intents (greeting, goodbye, general).

    Key design:
    - Full context injection via system prompt
    - No fallback logic - trust the LLM
    - Clean message history for context
    """

    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.openai_model,
            temperature=0.5,
            api_key=settings.openai_api_key
        )

    def _build_conversation_summary(self, state: ConversationState) -> str:
        """Build a clean conversation summary."""
        if not state.messages:
            return "This is the start of the conversation."

        # Get last 6 meaningful messages
        summary_lines = []
        count = 0
        for msg in reversed(state.messages):
            if count >= 6:
                break
            if isinstance(msg, HumanMessage):
                summary_lines.insert(0, f"Customer: {msg.content}")
                count += 1
            elif isinstance(msg, AIMessage) and msg.content:
                # Skip unhelpful responses
                if not self._is_unhelpful(msg.content):
                    summary_lines.insert(0, f"Agent: {msg.content}")
                    count += 1

        return "\n".join(summary_lines) if summary_lines else "Conversation just started."

    def _is_unhelpful(self, content: str) -> bool:
        """Check if a response is unhelpful."""
        if not content:
            return True
        unhelpful = ["issue with your message", "please repeat", "didn't catch", "error in your message"]
        return any(p in content.lower() for p in unhelpful)

    async def generate(
        self,
        user_message: str,
        state: ConversationState,
        agent_response: str = None
    ) -> str:
        """Generate response for simple intents."""

        # Get intent value
        intent = state.detected_intent
        intent_value = intent.value if hasattr(intent, 'value') else (intent or "general")

        logger.info(f"[RESPONSE_GEN] Processing: '{user_message}', intent: {intent_value}")

        # Handle simple intents directly
        if intent_value == "greeting":
            return random.choice(GREETING_RESPONSES)

        if intent_value == "goodbye":
            return random.choice(GOODBYE_RESPONSES)

        # If we have an agent response, use it
        if agent_response:
            return agent_response

        # Generate general response with full context
        customer_info = state.customer.to_summary() if state.customer.is_identified else "New customer (not identified)"
        conversation_summary = self._build_conversation_summary(state)

        system_prompt = RESPONSE_SYSTEM_PROMPT.format(
            conversation_summary=conversation_summary,
            customer_info=customer_info,
            intent=intent_value
        )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message)
        ]

        response = await self.llm.ainvoke(messages)
        logger.info(f"[RESPONSE_GEN] Generated: '{response.content[:50]}...'")

        return response.content
