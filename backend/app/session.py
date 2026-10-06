"""One VoiceSession per WebSocket. Owns the turn epoch, vendors, and barge-in."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.config import settings
from app.llm.prompts import build_messages
from app.metrics import TurnClock
from app.pipeline import run_turn
from app.protocol import (
    AgentState,
    AudioDataIn,
    ClientReadyIn,
    ErrorFrame,
    PingIn,
    Pong,
    ServerFrame,
    SessionReady,
    TranscriptStream,
    UserInterruptedIn,
    parse_client_message,
)
from app.stt.deepgram import STTUnavailable, DeepgramStream
from app.tts.cartesia import CartesiaTTS, TTSFailed

logger = logging.getLogger(__name__)

_PUBLIC_STATE = {
    "IDLE": "listening",
    "USER_SPEAKING": "listening",
    "THINKING": "thinking",
    "SPEAKING": "speaking",
    "INTERRUPTED": "interrupted",
}


class VoiceSession:
    def __init__(self, websocket: WebSocket) -> None:
        self.ws = websocket
        self.session_id = str(uuid4())
        self.mode = "pub_sparring_partner"
        self.state = "IDLE"
        self.turn_epoch = 0
        self.turn_id: str | None = None
        self.utterance_id: str | None = None
        self.history: list[dict] = []
        self.llm_task: asyncio.Task | None = None
        self.dg: DeepgramStream | None = None
        self.tts = CartesiaTTS(settings.cartesia_api_key)
        self.sample_rate_in = 16000
        self.sample_rate_out = 24000
        self.last_voice_at: float | None = None
        self.expected_seq: int | None = None
        self.stt_disabled = False
        self._stt_reconnecting = False
        self.stopping = False
        self.last_rx = time.monotonic()
        self.last_ping = time.monotonic()
        self.last_keepalive = 0.0
        self._send_lock = asyncio.Lock()
        self.turn_lock = asyncio.Lock()
        self._audio_queue: asyncio.Queue = asyncio.Queue()
        self._events: asyncio.Queue = asyncio.Queue()
        self._sender: asyncio.Task | None = None
        self._pump: asyncio.Task | None = None
        self._bg: set[asyncio.Task] = set()

    def build_turn_messages(self, user_text: str) -> list[dict]:
        return build_messages(self.mode, self.history, user_text)

    def remember_turn(self, user_text: str, assistant_text: str) -> None:
        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": assistant_text})
        if len(self.history) > 12:
            del self.history[:-12]

    async def run(self) -> None:
        self._sender = asyncio.create_task(self._send_audio_loop())
        self._pump = asyncio.create_task(self._pump_events())
        await self.emit_now(SessionReady(session_id=self.session_id, mode=self.mode))  # type: ignore[arg-type]
        await self.emit_now(AgentState(state="listening"))
        await self._warm_vendors()
        try:
            while not self.stopping:
                try:
                    incoming = await asyncio.wait_for(self.ws.receive(), timeout=1.0)
                except asyncio.TimeoutError:
                    if not await self._idle_check():
                        break
                    continue
                except WebSocketDisconnect:
                    break
                if incoming.get("type") == "websocket.disconnect":
                    break
                self.last_rx = time.monotonic()
                if not await self._idle_check():
                    break
                await self._handle_incoming(incoming)
        except WebSocketDisconnect:
            raise
        except Exception:
            logger.exception("session loop failed")
            await self.emit_now(
                ErrorFrame(code="SESSION_FATAL", message="Session failed", recoverable=False, turn_id=self.turn_id)
            )

    async def close(self) -> None:
        self.stopping = True
        self.turn_epoch += 1
        task = self.llm_task
        self.llm_task = None
        if task is not None and not task.done():
            task.cancel()
        self._clear_audio_queue()
        if self.dg is not None:
            try:
                await self.dg.close()
            except Exception:
                logger.debug("deepgram close failed", exc_info=True)
        try:
            await self.tts.abort()
        except Exception:
            logger.debug("tts abort failed", exc_info=True)
        await self._events.put(None)
        await self._audio_queue.put(None)
        for bg in list(self._bg):
            bg.cancel()
        if self._pump is not None:
            self._pump.cancel()
        if self._sender is not None:
            self._sender.cancel()

    async def emit_now(self, frame: ServerFrame) -> None:
        try:
            payload = frame.model_dump(mode="json")
            async with self._send_lock:
                await self.ws.send_text(json.dumps(payload))
        except Exception:
            logger.debug("send failed", exc_info=True)

    async def enqueue_audio(self, epoch: int, frame) -> None:
        if epoch != self.turn_epoch:
            return
        await self._audio_queue.put((epoch, frame))

    async def _send_audio_loop(self) -> None:
        try:
            while True:
                item = await self._audio_queue.get()
                if item is None:
                    return
                epoch, frame = item
                if epoch != self.turn_epoch:
                    continue
                await self.emit_now(frame)
        except asyncio.CancelledError:
            raise

    def _clear_audio_queue(self) -> None:
        while True:
            try:
                self._audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def _warm_vendors(self) -> None:
        self.dg = DeepgramStream(
            settings.deepgram_api_key,
            on_interim=self._queue_interim,
            on_final=self._queue_final,
            on_speech_started=self._queue_speech,
            on_utterance_end=self._queue_utterance,
            on_error=self._on_stt_error,
        )
        try:
            await self.dg.start()
        except STTUnavailable as exc:
            self.stt_disabled = not exc.recoverable
            await self.emit_now(
                ErrorFrame(
                    code="STT_DISCONNECT",
                    message=str(exc),
                    recoverable=exc.recoverable,
                    turn_id=None,
                )
            )
            if exc.recoverable:
                self._kick_reconnect(str(exc))
        except Exception as exc:
            logger.exception("deepgram start failed")
            self._kick_reconnect(str(exc) or "Deepgram connection failed")

        try:
            await self.tts.start()
        except TTSFailed as exc:
            await self.emit_now(
                ErrorFrame(code="TTS_ERROR", message=str(exc), recoverable=exc.recoverable, turn_id=None)
            )
        except Exception as exc:
            logger.exception("cartesia start failed")
            await self.emit_now(
                ErrorFrame(
                    code="TTS_ERROR",
                    message=str(exc) or "Cartesia connection failed",
                    recoverable=True,
                    turn_id=None,
                )
            )

    def _kick_reconnect(self, message: str) -> None:
        if self.stopping or self.stt_disabled or self._stt_reconnecting:
            return
        self._stt_reconnecting = True
        task = asyncio.create_task(self._reconnect_stt(message))
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    async def _on_stt_error(self, message: str) -> None:
        self._kick_reconnect(message)

    async def _reconnect_stt(self, message: str) -> None:
        try:
            await self.emit_now(
                ErrorFrame(
                    code="STT_DISCONNECT",
                    message=message or "Speech recognition disconnected",
                    recoverable=True,
                    turn_id=self.turn_id,
                )
            )
            delays = (0.2, 0.5, 1.0, 2.0, 2.0)
            for delay in delays:
                if self.stopping:
                    return
                await asyncio.sleep(delay)
                try:
                    if self.dg is not None:
                        await self.dg.close()
                    self.dg = DeepgramStream(
                        settings.deepgram_api_key,
                        on_interim=self._queue_interim,
                        on_final=self._queue_final,
                        on_speech_started=self._queue_speech,
                        on_utterance_end=self._queue_utterance,
                        on_error=self._on_stt_error,
                    )
                    await self.dg.start()
                    return
                except STTUnavailable as exc:
                    if not exc.recoverable:
                        self.stt_disabled = True
                        await self.emit_now(
                            ErrorFrame(code="STT_DISCONNECT", message=str(exc), recoverable=False, turn_id=self.turn_id)
                        )
                        return
                    logger.exception("deepgram reconnect failed")
                except Exception:
                    logger.exception("deepgram reconnect failed")
            await self.emit_now(
                ErrorFrame(
                    code="SESSION_FATAL",
                    message="Speech recognition unavailable",
                    recoverable=False,
                    turn_id=self.turn_id,
                )
            )
            try:
                await self.ws.close(code=1011)
            except Exception:
                logger.debug("fatal close failed", exc_info=True)
        finally:
            self._stt_reconnecting = False

    async def _queue_interim(self, text: str) -> None:
        self._events.put_nowait(("interim", text))

    async def _queue_final(self, text: str) -> None:
        self._events.put_nowait(("final", text))

    async def _queue_speech(self) -> None:
        self._events.put_nowait(("speech", None))

    async def _queue_utterance(self) -> None:
        self._events.put_nowait(("utt", None))

    async def _pump_events(self) -> None:
        try:
            while True:
                item = await self._events.get()
                if item is None:
                    return
                kind, payload = item
                try:
                    if kind == "interim":
                        await self._on_interim(payload)
                    elif kind == "final":
                        await self._on_final(payload)
                    elif kind == "speech":
                        await self._on_speech_started()
                    elif kind == "utt":
                        await self._on_utterance_end()
                except Exception:
                    logger.exception("event pump failed")
        except asyncio.CancelledError:
            raise

    async def _handle_incoming(self, incoming: dict) -> None:
        if incoming.get("type") != "websocket.receive":
            return
        if incoming.get("bytes") is not None:
            await self.emit_now(
                ErrorFrame(code="BAD_FRAME", message="Binary frames are not accepted", recoverable=True, turn_id=self.turn_id)
            )
            return
        text = incoming.get("text")
        if text is None:
            return
        try:
            data = json.loads(text)
            frame = parse_client_message(data)
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            logger.info("bad client frame: %s", exc)
            await self.emit_now(
                ErrorFrame(code="BAD_FRAME", message="Invalid frame", recoverable=True, turn_id=self.turn_id)
            )
            return
        if frame is None:
            return
        try:
            if isinstance(frame, AudioDataIn):
                await self._on_audio(frame)
            elif isinstance(frame, PingIn):
                await self._on_ping(frame)
            elif isinstance(frame, ClientReadyIn):
                self.sample_rate_in = frame.sample_rate_in
                self.sample_rate_out = frame.sample_rate_out_preferred
            elif isinstance(frame, UserInterruptedIn):
                task = asyncio.create_task(self._on_user_interrupted())
                self._bg.add(task)
                task.add_done_callback(self._bg.discard)
        except Exception:
            logger.exception("frame dispatch failed")

    async def _on_audio(self, frame: AudioDataIn) -> None:
        if self.expected_seq is None:
            self.expected_seq = frame.seq
        elif frame.seq != self.expected_seq:
            logger.info("audio seq gap expected %s got %s", self.expected_seq, frame.seq)
        self.expected_seq = frame.seq + 1
        if self.dg is None or self.stt_disabled:
            return
        try:
            await self.dg.send_pcm(frame.pcm())
        except Exception:
            logger.exception("failed to forward pcm")

    async def _on_ping(self, frame: PingIn) -> None:
        self.last_ping = time.monotonic()
        await self.emit_now(
            Pong(client_timestamp=frame.client_timestamp, server_timestamp=int(time.time() * 1000))
        )

    async def _idle_check(self) -> bool:
        now = time.monotonic()
        if now - self.last_rx >= 90:
            logger.info("closing idle session %s", self.session_id)
            try:
                await self.ws.close(code=1001)
            except Exception:
                logger.debug("idle close failed", exc_info=True)
            return False
        if now - self.last_ping >= 45 and now - self.last_keepalive >= 45:
            self.last_keepalive = now
            state = _PUBLIC_STATE.get(self.state, "listening")
            await self.emit_now(AgentState(state=state))  # type: ignore[arg-type]
        return True

    async def _on_interim(self, text: str) -> None:
        self.last_voice_at = time.perf_counter()
        cleaned = text.strip()
        if not cleaned:
            return
        if self.utterance_id is None:
            self.utterance_id = str(uuid4())
        if self.state == "IDLE":
            self.state = "USER_SPEAKING"
        await self.emit_now(
            TranscriptStream(role="user", delta=cleaned, is_final=False, turn_id=self.utterance_id)
        )

    async def _on_utterance_end(self) -> None:
        return

    async def _on_speech_started(self) -> None:
        async with self.turn_lock:
            if self.state in {"THINKING", "SPEAKING"}:
                await self._interrupt_unlocked()
            self.state = "USER_SPEAKING"
            self.utterance_id = str(uuid4())

    async def _on_final(self, text: str) -> None:
        cleaned = " ".join(text.split())
        if len(cleaned) < 2:
            return
        async with self.turn_lock:
            if self.state in {"THINKING", "SPEAKING"}:
                await self._interrupt_unlocked()
            self.turn_epoch += 1
            epoch = self.turn_epoch
            self.turn_id = self.utterance_id or str(uuid4())
            turn_id = self.turn_id
            self.state = "THINKING"
            clock = TurnClock()
            if self.last_voice_at is not None:
                clock.marks["user_end"] = self.last_voice_at
            else:
                clock.mark("user_end")
            clock.mark("stt_final")
            self.last_voice_at = None
            await self.emit_now(TranscriptStream(role="user", delta=cleaned, is_final=True, turn_id=turn_id))
            await self.emit_now(AgentState(state="thinking"))
            logger.info("user final: %s", cleaned)
            self.llm_task = asyncio.create_task(run_turn(self, cleaned, turn_id, epoch, clock))

    async def _on_user_interrupted(self) -> None:
        async with self.turn_lock:
            await self._interrupt_unlocked()

    async def _interrupt_unlocked(self) -> None:
        self.turn_epoch += 1
        task = self.llm_task
        self.llm_task = None
        self._clear_audio_queue()
        try:
            await self.tts.abort()
        except Exception:
            logger.exception("tts abort failed")
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self.state = "INTERRUPTED"
        await self.emit_now(AgentState(state="interrupted"))
        self.state = "IDLE"
        await self.emit_now(AgentState(state="listening"))
