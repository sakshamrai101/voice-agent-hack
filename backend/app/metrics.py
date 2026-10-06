"""Per-turn latency marks. All stamps are time.perf_counter() seconds."""

from __future__ import annotations

import time


class TurnClock:
    def __init__(self) -> None:
        self.marks: dict[str, float] = {}

    def mark(self, name: str) -> None:
        if name not in self.marks:
            self.marks[name] = time.perf_counter()

    def emit(self) -> dict[str, int]:
        def ms(start: str, end: str) -> int:
            if start not in self.marks or end not in self.marks:
                return 0
            return max(0, int(round((self.marks[end] - self.marks[start]) * 1000)))

        return {
            "stt_final_ms": ms("user_end", "stt_final"),
            "llm_ttft_ms": ms("stt_final", "llm_first"),
            "tts_ttfa_ms": ms("llm_first", "tts_first"),
            "total_turnaround_ms": ms("user_end", "tts_first"),
        }
