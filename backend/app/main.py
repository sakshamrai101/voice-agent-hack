"""BanterBox FastAPI app."""

from __future__ import annotations

import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.session import VoiceSession

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="BanterBox")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list or ["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.websocket("/ws/voice")
async def voice(websocket: WebSocket) -> None:
    await websocket.accept()
    session = VoiceSession(websocket)
    try:
        await session.run()
    except WebSocketDisconnect:
        logger.info("client disconnected")
    finally:
        await session.close()
