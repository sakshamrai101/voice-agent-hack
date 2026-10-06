"""WebSocket frames. Unknown events are ignored by the parser; invalid known frames raise."""

from __future__ import annotations

import logging
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from app.audio_util import b64_to_pcm16

logger = logging.getLogger(__name__)

Mode = Literal["dramatic_commentator", "pub_sparring_partner", "data_analyst"]
AgentStateName = Literal["listening", "thinking", "speaking", "interrupted"]
ErrorCode = Literal[
    "STT_DISCONNECT",
    "LLM_ERROR",
    "TTS_ERROR",
    "BAD_FRAME",
    "TOOL_ERROR",
    "SESSION_FATAL",
]
ToolName = Literal["lookup_head_to_head", "trigger_stadium_audio", "switch_commentary_mode"]

KNOWN_CLIENT_EVENTS = {"audio_data", "user_interrupted", "ping", "client_ready"}


class AudioDataIn(BaseModel):
    event: Literal["audio_data"]
    payload: str
    seq: int = Field(ge=0)

    def pcm(self) -> bytes:
        return b64_to_pcm16(self.payload)


class UserInterruptedIn(BaseModel):
    event: Literal["user_interrupted"]
    reason: Literal["vad", "manual"]
    client_timestamp: int


class PingIn(BaseModel):
    event: Literal["ping"]
    client_timestamp: int


class ClientReadyIn(BaseModel):
    event: Literal["client_ready"]
    sample_rate_in: int
    sample_rate_out_preferred: int


ClientFrame = Annotated[
    Union[AudioDataIn, UserInterruptedIn, PingIn, ClientReadyIn],
    Field(discriminator="event"),
]
_client_adapter = TypeAdapter(ClientFrame)


class SessionReady(BaseModel):
    event: Literal["session_ready"] = "session_ready"
    session_id: str
    mode: Mode


class Pong(BaseModel):
    event: Literal["pong"] = "pong"
    client_timestamp: int
    server_timestamp: int


class AgentState(BaseModel):
    event: Literal["agent_state"] = "agent_state"
    state: AgentStateName


class TranscriptStream(BaseModel):
    event: Literal["transcript_stream"] = "transcript_stream"
    role: Literal["user", "agent"]
    delta: str
    is_final: bool
    turn_id: str


class ToolExecuted(BaseModel):
    event: Literal["tool_executed"] = "tool_executed"
    tool_name: ToolName
    turn_id: str
    data: dict


class AudioOutput(BaseModel):
    event: Literal["audio_output"] = "audio_output"
    payload: str
    sample_rate: int = 24000
    turn_id: str
    seq: int = Field(ge=0)


class AudioOutputEnd(BaseModel):
    event: Literal["audio_output_end"] = "audio_output_end"
    turn_id: str


class Metrics(BaseModel):
    event: Literal["metrics"] = "metrics"
    turn_id: str
    stt_final_ms: int
    llm_ttft_ms: int
    tts_ttfa_ms: int
    total_turnaround_ms: int


class ErrorFrame(BaseModel):
    event: Literal["error"] = "error"
    code: ErrorCode
    message: str
    recoverable: bool
    turn_id: str | None = None


class ModeChanged(BaseModel):
    event: Literal["mode_changed"] = "mode_changed"
    mode: Mode


ServerFrame = (
    SessionReady
    | Pong
    | AgentState
    | TranscriptStream
    | ToolExecuted
    | AudioOutput
    | AudioOutputEnd
    | Metrics
    | ErrorFrame
    | ModeChanged
)


def parse_client_message(data: object) -> AudioDataIn | UserInterruptedIn | PingIn | ClientReadyIn | None:
    """Return a frame, None if the event is unknown, or raise ValidationError / ValueError."""
    if not isinstance(data, dict):
        raise ValueError("frame must be an object")
    event = data.get("event")
    if not isinstance(event, str):
        raise ValueError("missing event")
    if event not in KNOWN_CLIENT_EVENTS:
        logger.info("ignoring unknown event %s", event)
        return None
    frame = _client_adapter.validate_python(data)
    if isinstance(frame, AudioDataIn):
        frame.pcm()
    return frame


__all__ = [
    "AgentState",
    "AudioDataIn",
    "AudioOutput",
    "AudioOutputEnd",
    "ClientReadyIn",
    "ErrorFrame",
    "Metrics",
    "ModeChanged",
    "PingIn",
    "Pong",
    "ServerFrame",
    "SessionReady",
    "ToolExecuted",
    "TranscriptStream",
    "UserInterruptedIn",
    "ValidationError",
    "parse_client_message",
]
