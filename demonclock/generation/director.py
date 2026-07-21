"""The Director agent (SPEC.md §7 step 2): the first real caller of the
llm/ client layer. Given the bounded batch context (context.py), produces
structured *intent* for this batch -- a responsive-vs-world-driven mix, a
pressure level, and a short list of salient threads -- never world content
itself. Chunk C's Story agent reads this intent; the Director never touches
`state.world`/`state.player` directly, so it can't accidentally become a
second place that mutates state outside a validated engine function (SPEC.md
§0 pillar 6).
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from ..llm.registry import LLMRegistry

SYSTEM_PROMPT = (
    "You are the Director for a text RPG's content-generation batch. Given a "
    "snapshot of the world and the player's recent behavior, decide this "
    "batch's intent: how much to focus on the player's own patterns "
    "(responsive) versus world-driven pressures that exist independent of the "
    "player (world-driven), how urgent things feel right now (pressure_level, "
    "0=calm to 3=critical), and a short list of salient threads worth the "
    "next agents' attention. You do not invent world facts or generate any "
    "content yourself -- only steer what happens next."
)

INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "responsive_weight": {"type": "number"},
        "world_driven_weight": {"type": "number"},
        "pressure_level": {"type": "integer"},
        "salient_threads": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "responsive_weight", "world_driven_weight", "pressure_level", "salient_threads",
    ],
}


@dataclass
class DirectorIntent:
    responsive_weight: float
    world_driven_weight: float
    pressure_level: int
    salient_threads: list[str]

    @staticmethod
    def from_dict(data: dict) -> DirectorIntent:
        return DirectorIntent(
            responsive_weight=data["responsive_weight"],
            world_driven_weight=data["world_driven_weight"],
            pressure_level=data["pressure_level"],
            salient_threads=list(data["salient_threads"]),
        )


def run_director(registry: LLMRegistry, context: dict) -> DirectorIntent:
    data = registry.generate("director", SYSTEM_PROMPT, json.dumps(context), INTENT_SCHEMA)
    return DirectorIntent.from_dict(data)
