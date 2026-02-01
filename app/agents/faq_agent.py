"""
FAQ Agent - Clean LLM-driven FAQ handling.

Uses direct LLM calls with tool binding, not AgentExecutor.
Full context injection via system prompt.
"""
import logging
from typing import List

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage, ToolMessage

from app.config import get_settings
from app.tools.faq_tools import search_faq, list_services

settings = get_settings()
logger = logging.getLogger("app.agents.faq")


FAQ_SYSTEM_PROMPT = """You are a helpful customer service agent for Springfield Auto dealership.

## CONVERSATION CONTEXT
{conversation_summary}

## YOUR ROLE
Answer customer questions using the FAQ knowledge base and service information.

## TOOLS AVAILABLE
- search_faq: Search the FAQ database by query and optional category
- list_services: List all available services with pricing

## GUIDELINES
1. Use search_faq to find accurate information before answering
2. Keep responses SHORT (2-3 sentences max) - this is for voice
3. Be friendly, professional, and concise
4. If info not found, offer to connect with a team member
5. Don't use bullet points or lists - use natural speech

## VOICE-FRIENDLY TIPS
- Numbers should be spoken naturally ("two thirty" not "2:30")
- Avoid technical jargon
- Use natural speech patterns

Now answer the customer's question."""


class FAQAgent:
    """
    Handles FAQ queries using direct LLM calls with tool binding.

    Key design:
    - No AgentExecutor (too complex, generic errors)
    - Direct tool binding to ChatOpenAI
    - Context injection via system prompt
    - Message filtering for cleaner history
    """

    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.openai_model,
            temperature=0.3,
            api_key=settings.openai_api_key
        )
        self.tools = [search_faq, list_services]
        self.llm_with_tools = self.llm.bind_tools(self.tools)

    def _build_conversation_summary(self, chat_history: List[BaseMessage]) -> str:
        """Build a concise summary of recent conversation."""
        if not chat_history:
            return "This is the start of the conversation."

        summary_lines = []
        count = 0
        for msg in reversed(chat_history):
            if count >= 4:  # Keep last 4 exchanges
                break
            if isinstance(msg, HumanMessage):
                summary_lines.insert(0, f"Customer: {msg.content}")
                count += 1
            elif isinstance(msg, AIMessage) and msg.content:
                if self._is_useful_message(msg.content):
                    summary_lines.insert(0, f"Agent: {msg.content}")
                    count += 1

        return "\n".join(summary_lines) if summary_lines else "Conversation just started."

    def _is_useful_message(self, content: str) -> bool:
        """Check if a message is useful (not an error message)."""
        if not content:
            return False
        unhelpful_phrases = [
            "issue with your message", "please repeat", "didn't catch",
            "error in your message", "please clarify", "try again"
        ]
        return not any(phrase in content.lower() for phrase in unhelpful_phrases)

    async def handle(
        self,
        user_message: str,
        chat_history: List[BaseMessage] = None
    ) -> str:
        """
        Process FAQ query using direct LLM with tools.

        The LLM receives full context and decides what to do.
        No fallback logic.
        """
        logger.info(f"[FAQ_AGENT] Processing: '{user_message}'")

        conversation_summary = self._build_conversation_summary(chat_history or [])

        system_prompt = FAQ_SYSTEM_PROMPT.format(
            conversation_summary=conversation_summary
        )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message)
        ]

        max_iterations = 3
        response = None

        for iteration in range(max_iterations):
            try:
                ai_response = await self.llm_with_tools.ainvoke(messages)
                logger.info(f"[FAQ_AGENT] LLM response (iter {iteration})")

                # Check for tool calls
                if hasattr(ai_response, 'tool_calls') and ai_response.tool_calls:
                    logger.info(f"[FAQ_AGENT] Tool calls: {[tc['name'] for tc in ai_response.tool_calls]}")

                    messages.append(ai_response)

                    for tool_call in ai_response.tool_calls:
                        tool_name = tool_call['name']
                        tool_args = tool_call['args']
                        tool_id = tool_call['id']

                        tool_result = await self._execute_tool(tool_name, tool_args)
                        messages.append(ToolMessage(
                            content=str(tool_result),
                            tool_call_id=tool_id
                        ))

                    continue

                # Final response
                response = ai_response.content
                logger.info(f"[FAQ_AGENT] Final response: '{response[:100] if response else 'empty'}...'")
                break

            except Exception as e:
                logger.error(f"[FAQ_AGENT] LLM error: {e}", exc_info=True)
                response = "I'd be happy to help answer your question. Could you tell me more about what you'd like to know?"
                break

        return response or "I'm sorry, I couldn't find that information. Would you like me to connect you with a team member?"

    async def _execute_tool(self, tool_name: str, tool_args: dict) -> str:
        """Execute a tool by name."""
        logger.info(f"[FAQ_AGENT] Executing tool: {tool_name} with args: {tool_args}")

        tool_map = {tool.name: tool for tool in self.tools}

        if tool_name not in tool_map:
            return f"Unknown tool: {tool_name}"

        try:
            result = await tool_map[tool_name].ainvoke(tool_args)
            logger.info(f"[FAQ_AGENT] Tool result: {str(result)[:200]}")
            return str(result)
        except Exception as e:
            logger.error(f"[FAQ_AGENT] Tool error: {e}")
            return f"Error searching: {str(e)}"
