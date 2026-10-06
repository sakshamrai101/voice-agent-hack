"""PCM helpers. Server does not resample: 16 kHz in, 24 kHz out."""

from __future__ import annotations

import base64
import math
import struct

MAX_PCM_BYTES = 64 * 1024


def b64_to_pcm16(payload: str) -> bytes:
    try:
        raw = base64.b64decode(payload, validate=False)
    except Exception as exc:
        raise ValueError("invalid base64") from exc
    if len(raw) > MAX_PCM_BYTES:
        raise ValueError("payload too large")
    return raw


def pcm16_to_b64(pcm: bytes) -> str:
    return base64.b64encode(pcm).decode("ascii")


def pcm16_rms(pcm: bytes) -> float:
    if len(pcm) < 2:
        return 0.0
    count = len(pcm) // 2
    samples = struct.unpack("<" + "h" * count, pcm[: count * 2])
    total = 0.0
    for sample in samples:
        total += float(sample) * float(sample)
    return math.sqrt(total / count) / 32768.0
