"""In-memory rivalry lookup. Never touches the network."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "rivalries.json"
_TOKEN_RE = re.compile(r"[^a-z0-9\s]+")
_STOP_RE = re.compile(r"\b(fc|the)\b")


def normalize(value: str) -> str:
    text = value.lower().replace("'", "").replace("\u2019", "")
    text = _TOKEN_RE.sub(" ", text)
    text = _STOP_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


@lru_cache(maxsize=1)
def load_rows() -> list[dict]:
    return json.loads(_DATA_PATH.read_text(encoding="utf-8"))


def _labels(entity: dict) -> list[str]:
    return [entity.get("name", ""), entity.get("short", ""), *entity.get("aliases", [])]


def score_entity(query: str, entity: dict) -> int:
    q = normalize(query)
    if not q:
        return 0
    q_tokens = q.split()
    best = 0
    for label in _labels(entity):
        name = normalize(label)
        if not name:
            continue
        if name == q:
            best = max(best, 100)
            continue
        name_tokens = name.split()
        if q_tokens and name_tokens and set(q_tokens) == set(name_tokens):
            best = max(best, 100)
            continue
        if q_tokens and set(q_tokens) <= set(name_tokens):
            coverage = len(q_tokens) / len(name_tokens)
            best = max(best, int(40 + 50 * coverage))
            continue
        if name_tokens and set(name_tokens) <= set(q_tokens):
            best = max(best, 90)
    return best


def _assignment_score(row: dict, entity_a: str, entity_b: str) -> int:
    left_a = score_entity(entity_a, row["entity_a"])
    right_b = score_entity(entity_b, row["entity_b"])
    left_b = score_entity(entity_a, row["entity_b"])
    right_a = score_entity(entity_b, row["entity_a"])
    direct = left_a + right_b if left_a >= 60 and right_b >= 60 else 0
    swap = left_b + right_a if left_b >= 60 and right_a >= 60 else 0
    pair_score = _pair_alias_score(row, entity_a, entity_b)
    return max(direct, swap, pair_score)


def _pair_alias_score(row: dict, entity_a: str, entity_b: str) -> int:
    aliases = {normalize(alias) for alias in row.get("aliases", [])}
    a = normalize(entity_a)
    b = normalize(entity_b)
    candidates = {f"{a} {b}", f"{b} {a}", f"{a} vs {b}", f"{b} vs {a}"}
    if aliases & candidates:
        return 200
    return 0


def _entity_payload(entity: dict) -> dict:
    return {
        "name": entity["name"],
        "short": entity["short"],
        "accent": entity["accent"],
        "stats": entity["stats"],
    }


def _success(row: dict) -> dict:
    data = {
        "sport": row["sport"],
        "entity_a": _entity_payload(row["entity_a"]),
        "entity_b": _entity_payload(row["entity_b"]),
        "h2h": row["h2h"],
        "banter_hook": row["banter_hook"],
        "matched": True,
    }
    facts = row.get("facts") or []
    if facts:
        data["facts"] = facts
    return data


def _miss(entity_a: str, entity_b: str, sport: str) -> dict:
    resolved = sport if sport in {"football", "cricket"} else "football"
    left = entity_a.strip() or "A"
    right = entity_b.strip() or "B"
    return {
        "sport": resolved,
        "entity_a": {
            "name": left,
            "short": left,
            "accent": "#78B6FF",
            "stats": {"Titles": "—", "Win rate": "—"},
        },
        "entity_b": {
            "name": right,
            "short": right,
            "accent": "#E8B923",
            "stats": {"Titles": "—", "Win rate": "—"},
        },
        "h2h": {
            "meetings": 0,
            "a_wins": 0,
            "b_wins": 0,
            "draws": 0,
            "label": "No archive row — mock split",
        },
        "banter_hook": "Archive's cold on this one, so treat these numbers as pub-math, not gospel.",
        "matched": False,
    }


def lookup_head_to_head(entity_a: str, entity_b: str, sport: str) -> dict:
    sports = ["football", "cricket"] if sport == "auto" else [sport]
    rows = load_rows()
    for sp in sports:
        best: dict | None = None
        best_score = 0
        for row in rows:
            if row.get("sport") != sp:
                continue
            score = _assignment_score(row, entity_a, entity_b)
            if score > best_score:
                best = row
                best_score = score
        if best is not None:
            return _success(best)
    return _miss(entity_a, entity_b, sport)
