"""Cartesia Sonic WebSocket TTS. One warm socket per session; abort closes it."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import Awaitable, Callable
from uuid import uuid4

import websockets

logger = logging.getLogger(__name__)

CARTESIA_URL = "wss://api.cartesia.ai/tts/websocket?cartesia_version=2024-11-13"
CARTESIA_VERSION = "2024-11-13"

OnChunk = Callable[[bytes], Awaitable[None]]
EpochCheck = Callable[[], bool]


class TTSFailed(Exception):
    def __init__(self, message: str, recoverable: bool = True) -> None:
        super().__init__(message)
        self.recoverable = recoverable


class TTSAborted(Exception):
    pass


class _Handler:
    def __init__(self) -> None:
        self.queue: asyncio.Queue = asyncio.Queue()

    def feed(self, item: object) -> None:
        self.queue.put_nowait(item)


async def _connect(url: str, headers: dict[str, str]):
    try:
        return await websockets.connect(url, additional_headers=headers, open_timeout=8, max_size=8_000_000)
    except TypeError:
        return await websockets.connect(url, extra_headers=headers, open_timeout=8, max_size=8_000_000)


class CartesiaTTS:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._ws = None
        self._reader: asyncio.Task | None = None
        self._handlers: dict[str, _Handler] = {}
        self._order: list[str] = []
        self._send_lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()

    async def start(self) -> None:
        if not self.api_key:
            raise TTSFailed("CARTESIA_API_KEY is not set", recoverable=False)
        async with self._start_lock:
            if self._ws is not None:
                return
            ws = await _connect(
                CARTESIA_URL,
                {"X-API-Key": self.api_key, "Cartesia-Version": CARTESIA_VERSION},
            )
            self._ws = ws
            self._reader = asyncio.create_task(self._read(ws))

    async def synthesize(self, text: str, voice_id: str, on_chunk: OnChunk, epoch_check: EpochCheck) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        if not epoch_check():
            raise TTSAborted()
        if not self.api_key:
            raise TTSFailed("CARTESIA_API_KEY is not set", recoverable=False)
        try:
            await self.start()
        except TTSFailed:
            raise
        except Exception as exc:
            raise TTSFailed(f"Cartesia connection failed: {exc}") from exc

        context_id = str(uuid4())
        handler = _Handler()
        self._handlers[context_id] = handler
        self._order.append(context_id)
        payload = {
            "model_id": "sonic-2",
            "transcript": cleaned,
            "voice": {"mode": "id", "id": voice_id},
            "language": "en",
            "context_id": context_id,
            "output_format": {
                "container": "raw",
                "encoding": "pcm_s16le",
                "sample_rate": 24000,
            },
            "continue": False,
        }
        try:
            await self._send(payload)
            while True:
                if not epoch_check():
                    raise TTSAborted()
                try:
                    item = await asyncio.wait_for(handler.queue.get(), timeout=20)
                except TimeoutError as exc:
                    raise TTSFailed("Cartesia timed out") from exc
                if item is None:
                    return
                if isinstance(item, TTSAborted):
                    raise TTSAborted()
                if isinstance(item, Exception):
                    raise item
                if isinstance(item, bytes) and item:
                    await on_chunk(item)
        finally:
            self._handlers.pop(context_id, None)
            if context_id in self._order:
                self._order.remove(context_id)

    async def abort(self) -> None:
        handlers = list(self._handlers.values())
        self._handlers = {}
        self._order = []
        for handler in handlers:
            handler.feed(TTSAborted())
        ws = self._ws
        self._ws = None
        reader = self._reader
        self._reader = None
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                logger.debug("cartesia close failed", exc_info=True)
        if reader is not None:
            reader.cancel()

    async def _send(self, payload: dict) -> None:
        ws = self._ws
        if ws is None:
            raise TTSFailed("Cartesia socket is closed")
        async with self._send_lock:
            if self._ws is None:
                raise TTSFailed("Cartesia socket is closed")
            await self._ws.send(json.dumps(payload))

    async def _read(self, ws) -> None:
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    self._feed_bytes(raw)
                    continue
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                self._feed_message(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("cartesia reader ended: %s", exc)
            self._fail_all(TTSFailed(str(exc) or "Cartesia socket closed"))
        finally:
            if self._ws is ws:
                self._ws = None

    def _handler_for(self, context_id: str | None) -> _Handler | None:
        if context_id and context_id in self._handlers:
            return self._handlers[context_id]
        if len(self._handlers) == 1:
            return next(iter(self._handlers.values()))
        if self._order:
            return self._handlers.get(self._order[0])
        return None

    def _feed_bytes(self, raw: bytes) -> None:
        handler = self._handler_for(None)
        if handler is None:
            return
        if len(raw) % 2 == 1:
            raw = raw[:-1]
        if raw:
            handler.feed(raw)

    def _feed_message(self, message: dict) -> None:
        handler = self._handler_for(message.get("context_id"))
        if handler is None:
            return
        status = message.get("status_code")
        if message.get("type") == "error" or message.get("error") or (isinstance(status, int) and status >= 400):
            detail = message.get("error") or message.get("message") or "Cartesia error"
            handler.feed(TTSFailed(str(detail)))
            return
        data = message.get("data")
        if isinstance(data, str) and data:
            try:
                pcm = base64.b64decode(data)
            except Exception:
                pcm = b""
            if len(pcm) % 2 == 1:
                pcm = pcm[:-1]
            if pcm:
                handler.feed(pcm)
        if message.get("done") is True or message.get("type") == "done":
            handler.feed(None)

    def _fail_all(self, exc: Exception) -> None:
        handlers = list(self._handlers.values())
        self._handlers = {}
        self._order = []
        for handler in handlers:
            handler.feed(exc)
