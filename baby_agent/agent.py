"""Manual Claude agentic loop with tool use and adaptive thinking."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import anthropic

from .config import settings
from .huckleberry import HuckleberryManager
from .prompts import build_system_prompt
from .tools import TOOL_DEFINITIONS, dispatch_tool

log = logging.getLogger(__name__)

_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

MODEL = settings.claude_model
MAX_ITERATIONS = 10


def _thinking_params(model: str) -> dict | None:
    """Return the appropriate thinking parameter for the given model, or None."""
    if "haiku" in model:
        return None
    if model == "claude-opus-4-6":
        return {"type": "adaptive"}
    return {"type": "enabled", "budget_tokens": 10000}


def _serialize_content_blocks(blocks: list[Any]) -> list[dict[str, Any]]:
    """Convert Anthropic SDK content block objects to plain dicts for storage.

    Preserves thinking / redacted_thinking blocks so they can be sent back
    in subsequent turns (required for multi-turn tool use with adaptive thinking).
    """
    serialized: list[dict[str, Any]] = []
    for block in blocks:
        if hasattr(block, "model_dump"):
            serialized.append(block.model_dump())
        elif hasattr(block, "__dict__"):
            serialized.append(dict(block.__dict__))
        else:
            serialized.append(block)
    return serialized


async def run_turn(
    user_message: str,
    history: list[dict[str, Any]],
    manager: HuckleberryManager,
) -> tuple[str, list[dict[str, Any]]]:
    """Run one conversational turn and return (reply_text, updated_history).

    Args:
        user_message: The raw text from the user/Siri.
        history: The full conversation history so far (mutated in place, also returned).
        manager: The HuckleberryManager singleton for tool execution.

    Returns:
        (reply_text, updated_history)
    """
    # Resolve primary child for system prompt context
    child_uid = manager.get_primary_child_uid() or "unknown"
    child_name = manager.get_child_name(child_uid)
    current_state = manager.summarize_current_state(child_uid)
    system_prompt = build_system_prompt(current_state, child_name, child_uid, settings.huckleberry_timezone)

    # Append user message to working history
    working_history = list(history)
    working_history.append({"role": "user", "content": user_message})

    reply_text = ""

    for iteration in range(MAX_ITERATIONS):
        log.debug("Agent iteration %d/%d", iteration + 1, MAX_ITERATIONS)

        thinking = _thinking_params(MODEL)
        response = await _client.messages.create(
            model=MODEL,
            max_tokens=16000,
            **({"thinking": thinking} if thinking else {}),
            system=system_prompt,
            tools=TOOL_DEFINITIONS,
            messages=working_history,
        )

        # Serialize full content block list (including thinking blocks)
        serialized_blocks = _serialize_content_blocks(response.content)
        working_history.append({"role": "assistant", "content": serialized_blocks})

        if response.stop_reason == "end_turn":
            # Extract text from response blocks
            text_parts: list[str] = []
            for block in response.content:
                if hasattr(block, "type") and block.type == "text":
                    text_parts.append(block.text)
                elif isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            reply_text = " ".join(text_parts).strip()
            break

        if response.stop_reason == "tool_use":
            # Collect all tool-use blocks
            tool_use_blocks = [
                b for b in response.content
                if (hasattr(b, "type") and b.type == "tool_use")
                or (isinstance(b, dict) and b.get("type") == "tool_use")
            ]

            # Execute all tool calls concurrently
            async def _execute(block) -> dict[str, Any]:
                if hasattr(block, "name"):
                    name, tool_id, inputs = block.name, block.id, block.input
                else:
                    name = block["name"]
                    tool_id = block["id"]
                    inputs = block.get("input", {})
                result = await dispatch_tool(name, inputs, manager)
                return {"type": "tool_result", "tool_use_id": tool_id, "content": str(result)}

            tool_results = await asyncio.gather(*[_execute(b) for b in tool_use_blocks])

            working_history.append({"role": "user", "content": list(tool_results)})
            continue

        # Unexpected stop reason — break to avoid infinite loop
        log.warning("Unexpected stop_reason: %s", response.stop_reason)
        break

    else:
        log.warning("Reached max iterations (%d) without end_turn.", MAX_ITERATIONS)
        reply_text = "I'm having trouble processing that right now. Please try again."

    return reply_text, working_history
