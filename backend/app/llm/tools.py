"""OpenAI tool schemas. Execution lives in app.tools.registry."""

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "lookup_head_to_head",
            "description": "Fetch head-to-head records, trophies, and banter hooks for two players or clubs. Call whenever the user compares two entities, names a rivalry, or makes a biased claim that needs facts.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "entity_a": {"type": "string"},
                    "entity_b": {"type": "string"},
                    "sport": {"type": "string", "enum": ["football", "cricket", "auto"]},
                },
                "required": ["entity_a", "entity_b", "sport"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "trigger_stadium_audio",
            "description": "Play a client-side stadium stinger. Call for dramatic goals, controversial calls, cocky punchlines, or Ronaldo-style moments.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "effect": {
                        "type": "string",
                        "enum": ["stadium_roar", "referee_whistle", "boo_crowd", "siuuu_chant"],
                    }
                },
                "required": ["effect"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "switch_commentary_mode",
            "description": "Change persona and voice. Call when the user asks to commentate, debate, or wants dry stats.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["dramatic_commentator", "pub_sparring_partner", "data_analyst"],
                    }
                },
                "required": ["mode"],
            },
        },
    },
]
