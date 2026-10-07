"""Streaming chat completions with assembled tool calls."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
GEMINI_MODEL = "gemini-3.8-flash"

EpochCheck = Callable[[], bool]
OnDelta = Callable[[str], Awaitable[None]]
OnToolCalls = Callable[[list[dict[str, str]], list[dict]], Awaitable[None]]
OnToolsStarted = Callable[[], Awaitable[None]]
TemperatureFor = Callable[[], float]


class LLMCallError(Exception):
    def __init__(self, message: str, recoverable: bool = True) -> None:
        super().__init__(message)
        self.recoverable = recoverable


_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.gemini_api_key,
            base_url=GEMINI_BASE_URL,
            max_retries=0,
            timeout=8.0,
        )
    return _client


def _accumulate_tool_calls(tool_calls: dict[int, dict[str, Any]], deltas: list[Any]) -> None:
    for tc in deltas:
        idx = int(tc.index)
        slot = tool_calls.setdefault(
            idx,
            {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
        )
        dumped = tc.model_dump(exclude_none=True) if hasattr(tc, "model_dump") else {}
        if dumped.get("id"):
            slot["id"] = dumped["id"]
        if dumped.get("type"):
            slot["type"] = dumped["type"]
        function = dumped.get("function") or {}
        if function.get("name"):
            slot["function"]["name"] = function["name"]
        if function.get("arguments"):
            slot["function"]["arguments"] += function["arguments"]
        for key, value in dumped.items():
            if key not in {"id", "index", "type", "function"}:
                slot[key] = value


async def stream_turn(
    messages: list[dict],
    tools: list[dict],
    on_delta: OnDelta,
    on_tool_calls: OnToolCalls,
    epoch_check: EpochCheck,
    temperature_for: TemperatureFor,
    on_tools_started: OnToolsStarted | None = None,
) -> None:
    """Stream a turn. Tool rounds hand control to on_tool_calls, then continue."""
    if not settings.gemini_api_key:
        raise LLMCallError("GEMINI_API_KEY is not set", recoverable=False)

    client = get_client()
    for _round in range(4):
        if not epoch_check():
            return
        tool_calls: dict[int, dict[str, Any]] = {}
        content_parts: list[str] = []
        tools_signaled = False
        stream = None
        try:
            async with asyncio.timeout(8):
                stream = await client.chat.completions.create(
                    model=GEMINI_MODEL,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=temperature_for(),
                    max_tokens=512,
                    reasoning_effort="low",
                    stream=True,
                )
                async for chunk in stream:
                    if not epoch_check():
                        return
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    delta = choice.delta
                    if delta is None:
                        continue
                    if delta.tool_calls:
                        if not tools_signaled:
                            tools_signaled = True
                            if on_tools_started is not None:
                                await on_tools_started()
                        _accumulate_tool_calls(tool_calls, list(delta.tool_calls))
                    if delta.content:
                        content_parts.append(delta.content)
                        await on_delta(delta.content)
        except asyncio.CancelledError:
            raise
        except TimeoutError as exc:
            raise LLMCallError("Gemini stream timed out") from exc
        except LLMCallError:
            raise
        except Exception as exc:
            logger.exception("gemini stream failed")
            raise LLMCallError(str(exc)) from exc
        finally:
            if stream is not None:
                closer = getattr(stream, "close", None)
                if closer is not None:
                    try:
                        result = closer()
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception:
                        logger.debug("gemini stream close failed", exc_info=True)

        if not epoch_check():
            return
        if not tool_calls:
            return

        assembled = [tool_calls[idx] for idx in sorted(tool_calls)]
        wire_calls: list[dict[str, Any]] = []
        callback_calls: list[dict[str, str]] = []
        for idx, tc in enumerate(assembled):
            function = tc.get("function") or {}
            name = function.get("name") or ""
            arguments = function.get("arguments") or "{}"
            call_id = tc.get("id") or f"call_{idx}"
            tc["id"] = call_id
            tc["type"] = tc.get("type") or "function"
            tc["function"] = {"name": name, "arguments": arguments}
            wire_calls.append(tc)
            callback_calls.append({"id": call_id, "name": name, "arguments": arguments})
        messages.append(
            {
                "role": "assistant",
                "content": "".join(content_parts) or None,
                "tool_calls": wire_calls,
            }
        )
        await on_tool_calls(callback_calls, messages)
        if not epoch_check():
            return
    logger.info("stopped after max tool rounds")
