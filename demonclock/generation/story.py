"""The Story/Situation agent (SPEC.md §7 step 3): given the Director's
intent (Chunk B) and the bounded batch context, produces ONE "situation" --
the tension that plausibly emerges *here* (village -> blight; noble cornering
the herb trade). Two streams keep the world from becoming an echo of the
player (SPEC.md §7's "avoid the echo chamber"):
  - "responsive": shaped by the player's own current node/behavior.
  - "world_driven": pushed by the simulation independent of the player
    (invasion/economy pressure already visible in the retrieved context).
`pipeline.py` attempts both every batch by default so the world isn't just a
mirror of player habits -- Step 7 Chunk D added the one exception, skipping
whichever stream the Director's own weight judged genuinely lopsided that
batch (see `pipeline.STREAM_SKIP_THRESHOLD`).

The Story agent never writes a precondition manifest or touches the content
pool -- it only describes a situation in plain fields. `quest.py` is what
turns a situation into a concrete, manifest-carrying task.

Step 7 Chunk D also made the player's `derived_role_hint` (already present
in `context["player"]`, gathered since Chunk B but never explicitly used for
anything until now) load-bearing for tone: the system prompt below tells the
agent to lean a "responsive" situation's SUBJECT AND tone toward it, but for
"world_driven" only its narrative TONE -- the subject must stay independent
of the player, or the two-stream split stops meaning anything.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from ..llm.registry import LLMRegistry
from .director import DirectorIntent

SYSTEM_PROMPT = (
    "You are the Story/Situation agent for a text RPG's content-generation "
    "batch. Given the Director's intent and a snapshot of the world near the "
    "player, invent ONE situation: a plausible tension emerging at a "
    "specific existing node, referenced by its id (never invent a new "
    "place -- only use node ids that appear in the context you were given). "
    "A 'responsive' situation should connect to the player's own recent "
    "behavior; a 'world_driven' situation should come from the simulation's "
    "own pressures (invasion, prices, ...) independent of anything the "
    "player has done. The context's player.derived_role_hint is a short "
    "phrase describing who the player is becoming (e.g. 'trade-focused, "
    "combat-averse'). For a 'responsive' situation, let it shape both WHAT "
    "the situation is about and its narrative tone. For a 'world_driven' "
    "situation, its SUBJECT must stay independent of the player -- do not "
    "let the hint change what's happening -- but its narrative TONE/word "
    "choice may still lean toward it, since the same player reads either "
    "stream. Do not write quest tasks or game-mechanical requirements "
    "yourself -- only describe the situation."
)

SITUATION_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "node_id": {"type": "string"},
    },
    "required": ["id", "title", "description", "node_id"],
}


@dataclass
class Situation:
    id: str
    title: str
    description: str
    node_id: str
    stream: str  # "responsive" | "world_driven" -- which stream produced this

    @staticmethod
    def from_dict(data: dict, stream: str) -> Situation:
        return Situation(
            id=data["id"], title=data["title"], description=data["description"],
            node_id=data["node_id"], stream=stream,
        )


def run_story(registry: LLMRegistry, context: dict, intent: DirectorIntent, stream: str) -> Situation:
    payload = {
        "stream": stream,
        "director_intent": {
            "pressure_level": intent.pressure_level,
            "salient_threads": intent.salient_threads,
        },
        "context": context,
    }
    data = registry.generate("story", SYSTEM_PROMPT, json.dumps(payload), SITUATION_SCHEMA)
    return Situation.from_dict(data, stream)
