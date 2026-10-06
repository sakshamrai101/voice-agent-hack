"""Streaming chat completions with assembled tool calls."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

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
        _client = AsyncOpenAI(api_key=settings.openai_api_key, max_retries=0, timeout=8.0)
    return _client


def _accumulate_tool_calls(tool_calls: dict[int, dict[str, str]], deltas: list[Any]) -> None:
    for tc in deltas:
        idx = int(tc.index)
        slot = tool_calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
        if tc.id:
            slot["id"] = tc.id
        function = tc.function
        if function is None:
            continue
        if function.name:
            slot["name"] = function.name
        if function.arguments:
            slot["arguments"] += function.arguments


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
    if not settings.openai_api_key:
        raise LLMCallError("OPENAI_API_KEY is not set", recoverable=False)

    client = get_client()
    for _round in range(4):
        if not epoch_check():
            return
        tool_calls: dict[int, dict[str, str]] = {}
        content_parts: list[str] = []
        tools_signaled = False
        stream = None
        try:
            async with asyncio.timeout(8):
                stream = await client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=temperature_for(),
                    max_tokens=120,
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
            raise LLMCallError("OpenAI stream timed out") from exc
        except LLMCallError:
            raise
        except Exception as exc:
            logger.exception("openai stream failed")
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
                        logger.debug("openai stream close failed", exc_info=True)

        if not epoch_check():
            return
        if not tool_calls:
            return

        assembled = [tool_calls[idx] for idx in sorted(tool_calls)]
        for idx, tc in enumerate(assembled):
            if not tc["id"]:
                tc["id"] = f"call_{idx}"
            if not tc["arguments"]:
                tc["arguments"] = "{}"
        messages.append(
            {
                "role": "assistant",
                "content": "".join(content_parts) or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]},
                    }
                    for tc in assembled
                ],
            }
        )
        await on_tool_calls(assembled, messages)
        if not epoch_check():
            return
    logger.info("stopped after max tool rounds")
