"""Execute model tool calls. Successful results are what the client renders."""

from __future__ import annotations

from app.tools.lookup_h2h import lookup_head_to_head

EFFECTS = {"stadium_roar", "referee_whistle", "boo_crowd", "siuuu_chant"}
MODES = {"dramatic_commentator", "pub_sparring_partner", "data_analyst"}
SPORTS = {"football", "cricket", "auto"}


def execute(name: str, arguments: dict) -> tuple[dict, str | None]:
    """Return (data, new_mode). new_mode is set only for switch_commentary_mode. Raises on bad calls."""
    if not isinstance(arguments, dict):
        raise ValueError("tool arguments must be an object")

    if name == "lookup_head_to_head":
        entity_a = arguments.get("entity_a")
        entity_b = arguments.get("entity_b")
        sport = arguments.get("sport")
        if not isinstance(entity_a, str) or not isinstance(entity_b, str) or sport not in SPORTS:
            raise ValueError("lookup_head_to_head needs entity_a, entity_b, and sport")
        return lookup_head_to_head(entity_a, entity_b, sport), None

    if name == "trigger_stadium_audio":
        effect = arguments.get("effect")
        if effect not in EFFECTS:
            raise ValueError("unknown stadium effect")
        return {"effect": effect}, None

    if name == "switch_commentary_mode":
        mode = arguments.get("mode")
        if mode not in MODES:
            raise ValueError("unknown commentary mode")
        return {"mode": mode}, mode

    raise ValueError(f"unknown tool {name}")
