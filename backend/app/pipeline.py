"""LLM turn glue: sentence-flush TTS, tools, and first-byte metrics."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING

from app.config import settings
from app.audio_util import pcm16_to_b64
from app.llm.engine import LLMCallError, stream_turn
from app.llm.prompts import PROMPTS, temperature_for
from app.llm.tools import TOOLS
from app.protocol import AgentState, AudioOutput, AudioOutputEnd, ErrorFrame, Metrics, ModeChanged, ToolExecuted, TranscriptStream
from app.tools.registry import execute
from app.tts.cartesia import TTSAborted, TTSFailed

if TYPE_CHECKING:
    from app.metrics import TurnClock
    from app.session import VoiceSession

logger = logging.getLogger(__name__)

_CLAUSE = re.compile(r"[.!?](?=\s|$)")


class SentenceBuffer:
    """Flush on the first clause or 12 complete tokens. Incomplete tail stays buffered."""

    def __init__(self, token_limit: int = 12) -> None:
        self.buf = ""
        self.token_limit = token_limit

    def push(self, delta: str) -> list[str]:
        self.buf += delta
        flushed: list[str] = []
        while self.buf:
            match = _CLAUSE.search(self.buf)
            if match:
                sentence = self.buf[: match.end()].strip()
                self.buf = self.buf[match.end() :].lstrip()
                if sentence:
                    flushed.append(sentence)
                continue
            if self.buf[-1].isspace():
                words = self.buf.split()
                rest = ""
            else:
                parts = self.buf.split()
                if len(parts) <= 1:
                    break
                words = parts[:-1]
                rest = parts[-1]
            if len(words) >= self.token_limit:
                take = words[: self.token_limit]
                leftover = words[self.token_limit :]
                sentence = " ".join(take).strip()
                tail_words = leftover + ([rest] if rest else [])
                self.buf = " ".join(tail_words)
                if sentence:
                    flushed.append(sentence)
                continue
            break
        return flushed

    def flush(self) -> str | None:
        text = self.buf.strip()
        self.buf = ""
        return text or None


class _Speaker:
    def __init__(self) -> None:
        self._next = 0
        self._emit_at = 0
        self._cond = asyncio.Condition()

    def alloc(self) -> int:
        index = self._next
        self._next += 1
        return index

    async def wait_turn(self, index: int, still_ok) -> bool:
        async with self._cond:
            while self._emit_at != index:
                if not still_ok():
                    return False
                try:
                    await asyncio.wait_for(self._cond.wait(), timeout=0.2)
                except TimeoutError:
                    continue
            return still_ok()

    async def advance(self, index: int) -> None:
        async with self._cond:
            if self._emit_at == index:
                self._emit_at = index + 1
            self._cond.notify_all()


async def run_turn(session: VoiceSession, user_text: str, turn_id: str, epoch: int, clock: TurnClock) -> None:
    if session.turn_epoch != epoch:
        return

    buffer = SentenceBuffer()
    speaker = _Speaker()
    speak_tasks: list[asyncio.Task] = []
    parts: list[str] = []
    held: list[str] = []
    holding = {"tools": False}
    stop = asyncio.Event()
    audio_state = {"seq": 0, "sent": False}

    def epoch_ok() -> bool:
        return session.turn_epoch == epoch and not stop.is_set()

    async def emit_pcm(pcm: bytes) -> None:
        if not epoch_ok() or not pcm:
            return
        if not audio_state["sent"]:
            audio_state["sent"] = True
            clock.mark("tts_first")
            session.state = "SPEAKING"
            await session.emit_now(AgentState(state="speaking"))
            snapshot = clock.emit()
            await session.emit_now(Metrics(turn_id=turn_id, **snapshot))
        frame = AudioOutput(
            payload=pcm16_to_b64(pcm),
            sample_rate=24000,
            turn_id=turn_id,
            seq=audio_state["seq"],
        )
        audio_state["seq"] += 1
        await session.enqueue_audio(epoch, frame)

    async def speak(text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        index = speaker.alloc()
        queue: asyncio.Queue = asyncio.Queue()

        async def on_chunk(pcm: bytes) -> None:
            await queue.put(pcm)

        async def generate() -> None:
            try:
                voice = settings.voice_for(session.mode)
                await session.tts.synthesize(cleaned, voice, on_chunk, epoch_ok)
                await queue.put(None)
            except asyncio.CancelledError:
                await queue.put(TTSAborted())
                raise
            except TTSAborted:
                await queue.put(TTSAborted())
            except TTSFailed as exc:
                await queue.put(exc)
            except Exception as exc:
                await queue.put(TTSFailed(str(exc)))

        generated = asyncio.create_task(generate())
        try:
            ready = await speaker.wait_turn(index, epoch_ok)
            if not ready:
                return
            while True:
                if not epoch_ok():
                    return
                item = await queue.get()
                if item is None:
                    return
                if isinstance(item, TTSAborted):
                    return
                if isinstance(item, TTSFailed):
                    stop.set()
                    raise item
                if isinstance(item, Exception):
                    stop.set()
                    raise TTSFailed(str(item))
                await emit_pcm(item)
        finally:
            await speaker.advance(index)
            if not generated.done():
                generated.cancel()

    def schedule(delta: str) -> None:
        for sentence in buffer.push(delta):
            speak_tasks.append(asyncio.create_task(speak(sentence)))

    async def on_delta(delta: str) -> None:
        if not epoch_ok():
            return
        clock.mark("llm_first")
        parts.append(delta)
        await session.emit_now(TranscriptStream(role="agent", delta=delta, is_final=False, turn_id=turn_id))
        if holding["tools"]:
            held.append(delta)
            return
        schedule(delta)

    async def on_tools_started() -> None:
        holding["tools"] = True

    async def on_tool_calls(assembled: list[dict[str, str]], messages: list[dict]) -> None:
        for call in assembled:
            if not epoch_ok():
                return
            name = call.get("name") or ""
            raw_args = call.get("arguments") or "{}"
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError as exc:
                args = None
                error: Exception = exc
            else:
                error = None
            if error is None:
                try:
                    if not isinstance(args, dict):
                        raise ValueError("tool arguments must be an object")
                    data, new_mode = execute(name, args)
                except Exception as exc:
                    error = exc
            if error is not None:
                logger.exception("tool %s failed", name)
                await session.emit_now(
                    ErrorFrame(
                        code="TOOL_ERROR",
                        message=str(error),
                        recoverable=True,
                        turn_id=turn_id,
                    )
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps({"error": str(error)}),
                    }
                )
                continue
            await session.emit_now(ToolExecuted(tool_name=name, turn_id=turn_id, data=data))  # type: ignore[arg-type]
            if new_mode:
                session.mode = new_mode
                await session.emit_now(ModeChanged(mode=new_mode))  # type: ignore[arg-type]
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(data),
                }
            )
        prompt = PROMPTS.get(session.mode, PROMPTS["pub_sparring_partner"])
        messages[0] = {"role": "system", "content": prompt}
        holding["tools"] = False
        if held:
            schedule("".join(held))
            held.clear()

    messages = session.build_turn_messages(user_text)

    try:
        await stream_turn(
            messages,
            TOOLS,
            on_delta,
            on_tool_calls,
            epoch_ok,
            lambda: temperature_for(session.mode),
            on_tools_started,
        )
        if epoch_ok():
            rest = buffer.flush()
            if rest:
                speak_tasks.append(asyncio.create_task(speak(rest)))
        if speak_tasks:
            await asyncio.gather(*speak_tasks)
        if not epoch_ok():
            return
        spoken = "".join(parts).strip()
        if spoken:
            await session.emit_now(TranscriptStream(role="agent", delta="", is_final=True, turn_id=turn_id))
            session.remember_turn(user_text, spoken)
        if audio_state["sent"]:
            await session.emit_now(AudioOutputEnd(turn_id=turn_id))
        session.state = "IDLE"
        await session.emit_now(AgentState(state="listening"))
    except asyncio.CancelledError:
        stop.set()
        raise
    except TTSFailed as exc:
        stop.set()
        session._clear_audio_queue()
        logger.exception("tts failed")
        if session.turn_epoch == epoch:
            await session.emit_now(
                ErrorFrame(code="TTS_ERROR", message=str(exc), recoverable=exc.recoverable, turn_id=turn_id)
            )
            session.state = "IDLE"
            await session.emit_now(AgentState(state="listening"))
    except LLMCallError as exc:
        stop.set()
        session._clear_audio_queue()
        logger.exception("llm failed")
        if session.turn_epoch == epoch:
            await session.emit_now(
                ErrorFrame(code="LLM_ERROR", message=str(exc), recoverable=exc.recoverable, turn_id=turn_id)
            )
            session.state = "IDLE"
            await session.emit_now(AgentState(state="listening"))
    except Exception:
        stop.set()
        logger.exception("turn failed")
        if session.turn_epoch == epoch:
            await session.emit_now(
                ErrorFrame(code="LLM_ERROR", message="The reply failed", recoverable=True, turn_id=turn_id)
            )
            session.state = "IDLE"
            await session.emit_now(AgentState(state="listening"))
    finally:
        stop.set()
        for task in speak_tasks:
            if not task.done():
                task.cancel()
