"""The NPC agent (SPEC.md §7, Step 10 Stage 3) -- mirrors places.py's shape
exactly. Invoked only when a committed quest's own payload signals it wants
an NPC that doesn't exist yet (`needs_new_npc`/`npc_hint`, extending
QUEST_SCHEMA the same way `needs_new_place`/`place_hint` already does for
Places); an ordinary quest anchored to existing content never triggers this
agent at all.

The new NPC is added to the live world EXCLUSIVELY through `world.add_npc`
(mirrors `world.add_node`), never a raw generated dict written straight
into state -- same "AI proposes, engine enforces" posture as places.py's
own use of `world.add_node`/`add_link`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..llm.registry import LLMRegistry
from ..models import NPC

if TYPE_CHECKING:
    from ..state import GameState
    from .story import Situation

SYSTEM_PROMPT = (
    "You are the NPC agent for a text RPG's content-generation batch. A "
    "quest needs an NPC that doesn't exist yet. Given a short hint and the "
    "node they should be found at, invent ONE new NPC: a short lowercase id "
    "with no spaces (e.g. 'old_miller'), a display name, a short "
    "description, and a short list of tags (e.g. 'merchant', 'guard')."
)

NEW_NPC_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["id", "name", "description", "tags"],
}


@dataclass
class NewNPC:
    id: str
    name: str
    description: str
    tags: list[str] = field(default_factory=list)

    @staticmethod
    def from_dict(data: dict) -> NewNPC:
        return NewNPC(
            id=data["id"], name=data["name"],
            description=data["description"], tags=list(data.get("tags", [])),
        )


def run_npc(registry: LLMRegistry, context: dict, situation: Situation, npc_hint: str) -> NewNPC:
    payload = {"npc_hint": npc_hint, "node_id": situation.node_id, "context": context}
    data = registry.generate("npc", SYSTEM_PROMPT, json.dumps(payload), NEW_NPC_SCHEMA)
    return NewNPC.from_dict(data)


def materialize(state: GameState, node_id: str, new_npc: NewNPC) -> bool:
    """Adds `new_npc` to the live world via `world.add_npc`. Returns False
    (world untouched) if the id already exists or the anchor node doesn't --
    a bad proposal is silently absorbed, same treatment places.py's own
    materialize gives a rejected place."""
    world = state.world
    if new_npc.id in world.npcs or node_id not in world.nodes:
        return False

    world.add_npc(NPC(
        id=new_npc.id, name=new_npc.name, location_id=node_id,
        description=new_npc.description, tags=new_npc.tags,
    ))
    return True
