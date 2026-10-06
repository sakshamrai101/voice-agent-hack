"""Deepgram Nova-2 streaming client."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

import websockets

logger = logging.getLogger(__name__)

DEEPGRAM_URL = (
    "wss://api.deepgram.com/v1/listen"
    "?model=nova-2&encoding=linear16&sample_rate=16000&channels=1"
    "&interim_results=true&vad_events=true&utterance_end_ms=1000&endpointing=300"
)


class STTUnavailable(Exception):
    def __init__(self, message: str, recoverable: bool = True) -> None:
        super().__init__(message)
        self.recoverable = recoverable


async def _connect(url: str, headers: dict[str, str]):
    try:
        return await websockets.connect(url, additional_headers=headers, open_timeout=8, max_size=8_000_000)
    except TypeError:
        return await websockets.connect(url, extra_headers=headers, open_timeout=8, max_size=8_000_000)


class DeepgramStream:
    def __init__(
        self,
        api_key: str,
        on_interim: Callable[[str], Awaitable[None]],
        on_final: Callable[[str], Awaitable[None]],
        on_speech_started: Callable[[], Awaitable[None]],
        on_utterance_end: Callable[[], Awaitable[None]],
        on_error: Callable[[str], Awaitable[None]],
    ) -> None:
        self.api_key = api_key
        self._on_interim = on_interim
        self._on_final = on_final
        self._on_speech_started = on_speech_started
        self._on_utterance_end = on_utterance_end
        self._on_error = on_error
        self._ws = None
        self._reader: asyncio.Task | None = None
        self._keepalive: asyncio.Task | None = None
        self._closed = False
        self._parts: list[str] = []

    async def start(self) -> None:
        if not self.api_key:
            raise STTUnavailable("DEEPGRAM_API_KEY is not set", recoverable=False)
        self._closed = False
        self._ws = await _connect(
            DEEPGRAM_URL,
            {"Authorization": f"Token {self.api_key}"},
        )
        self._reader = asyncio.create_task(self._read())
        self._keepalive = asyncio.create_task(self._keepalive_loop())

    async def send_pcm(self, pcm: bytes) -> None:
        ws = self._ws
        if ws is None or self._closed or not pcm:
            return
        await ws.send(pcm)

    async def close(self) -> None:
        self._closed = True
        if self._keepalive is not None:
            self._keepalive.cancel()
            self._keepalive = None
        ws = self._ws
        self._ws = None
        if ws is not None:
            try:
                await ws.send(json.dumps({"type": "CloseStream"}))
            except Exception:
                pass
            try:
                await ws.close()
            except Exception:
                pass
        if self._reader is not None:
            self._reader.cancel()
            self._reader = None

    async def _keepalive_loop(self) -> None:
        try:
            while not self._closed:
                await asyncio.sleep(8)
                ws = self._ws
                if ws is None or self._closed:
                    return
                await ws.send(json.dumps({"type": "KeepAlive"}))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self._closed:
                await self._emit_error(f"Deepgram keepalive failed: {exc}")

    async def _read(self) -> None:
        ws = self._ws
        if ws is None:
            return
        try:
            async for raw in ws:
                if self._closed:
                    return
                if isinstance(raw, bytes):
                    continue
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                await self._handle(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self._closed:
                await self._emit_error(str(exc) or "Deepgram socket closed")
        else:
            if not self._closed:
                await self._emit_error("Deepgram socket closed")

    async def _emit_error(self, message: str) -> None:
        try:
            await self._on_error(message)
        except Exception:
            logger.exception("deepgram error callback failed")

    async def _flush_final(self) -> None:
        text = " ".join(part for part in self._parts if part).strip()
        self._parts = []
        if text:
            await self._on_final(text)

    async def _handle(self, message: dict) -> None:
        kind = message.get("type")
        if kind == "Results":
            channel = message.get("channel") or {}
            alternatives = channel.get("alternatives") or [{}]
            transcript = ""
            if alternatives:
                transcript = (alternatives[0].get("transcript") or "").strip()
            is_final = bool(message.get("is_final"))
            speech_final = bool(message.get("speech_final"))
            if not is_final:
                if transcript:
                    shown = " ".join([*self._parts, transcript]).strip()
                    await self._on_interim(shown)
                return
            if transcript:
                self._parts.append(transcript)
            if speech_final:
                await self._flush_final()
            return
        if kind == "SpeechStarted":
            self._parts = []
            await self._on_speech_started()
            return
        if kind == "UtteranceEnd":
            await self._flush_final()
            await self._on_utterance_end()
            return
        if kind in {"Error", "error"}:
            description = message.get("description") or message.get("message") or message.get("error") or "Deepgram error"
            await self._emit_error(str(description))
