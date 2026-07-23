"""The ambient-flavor agent (SPEC.md §2's `NARRATOR: describe the outcome`
step, generalized to "describe the place" — Step 7 Chunk C). Writes ONE
short, purely atmospheric line per node in the bounded batch context
(context.py's current node + immediate neighbors — the same slice every
other batch agent already reads from, so this adds no new "read the whole
graph" risk). Never a fact, quest, or anything the player could act on —
pure sensory/mood color, consistent with the node's own given state, which
is why this carries no precondition manifest (SPEC.md §8's canon check
exists to validate state-implying content; flavor never implies one).

Unlike `narrator.py`'s `reword_rumor`/`narrate_combat_outcome` (presentation-
layer calls owning their own try/except, invoked straight from `game.py`/
`newspaper.py`), `run_flavor` follows the SAME convention as
`director.py`/`story.py`/`quest.py`/`places.py`: it does not catch its own
errors — `pipeline.py`'s `_DEGRADE_ON` wraps the call, same graceful
per-stream degradation Story/Quest already have. The result is written into
`World.node_flavor` (a plain `dict[node_id, str]`, refreshed for whichever
nodes this batch's bounded context covered — a stale line for some other
node simply persists until a later batch's context happens to cover it
again, an accepted "start rough" simplification, same status as every other
placeholder tuning constant in this codebase) and PULLED, never pushed live —
`actions._resolve_look`/arrival narration just reads whatever's already
there, so Move/Look themselves never cost an AI call (SPEC.md §13).

Step 7 Chunk D added the player's `derived_role_hint` (already present in
`context["player"]`, just not previously threaded into this agent's own
payload) as optional word-choice/mood flavor -- never something that
changes what a location actually IS, which stays driven entirely by the
node's own truth.
"""
from __future__ import annotations

import json

from ..llm.registry import LLMRegistry

SYSTEM_PROMPT = (
    "You are the ambient-flavor writer for a text RPG. You will be given a "
    "list of existing locations (id, name, type, state, tags) and, "
    "optionally, the player's derived_role_hint -- a short phrase "
    "describing who the player is becoming (e.g. 'trade-focused, "
    "combat-averse'). Write ONE short (one sentence) piece of atmospheric "
    "color for EACH location, keyed by its exact id. Only use ids from the "
    "list you were given -- never invent a new location. Never state a new "
    "fact, event, quest, price, or anything the player could act on -- pure "
    "sensory/mood description only, consistent with the location's given "
    "state. If a derived_role_hint is given, you may let it subtly color "
    "word choice/mood (e.g. a trade-focused player might notice the market "
    "stalls first), but it must never change what a location actually is."
)

FLAVOR_SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["node_id", "text"],
            },
        },
    },
    "required": ["lines"],
}


def run_flavor(registry: LLMRegistry, context: dict) -> dict[str, str]:
    """One AI call, once per batch. Returns node_id -> flavor line, filtered
    to only the ids actually present in `context` (current_node + immediate
    neighbors) -- a hallucinated or stale id from a malformed reply is
    dropped rather than written into `World.node_flavor` for a place that
    may not exist, same "never let generation invent an entity it wasn't
    handed" posture `resolve.py`'s AI fallback enforces via its shortlist-
    only enum."""
    known_ids = {context["current_node"]["id"]} | {node["id"] for node in context["neighbor_nodes"]}
    payload = {
        "locations": [context["current_node"], *context["neighbor_nodes"]],
        "player_role_hint": context["player"]["derived_role_hint"],
    }
    data = registry.generate("flavor", SYSTEM_PROMPT, json.dumps(payload), FLAVOR_SCHEMA)
    return {
        entry["node_id"]: entry["text"]
        for entry in data["lines"]
        if entry["node_id"] in known_ids and entry["text"].strip()
    }
