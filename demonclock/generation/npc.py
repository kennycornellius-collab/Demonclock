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
from ..npc_combat import NPCArchetype

if TYPE_CHECKING:
    from ..state import GameState
    from .story import Situation

SYSTEM_PROMPT = (
    "You are the NPC agent for a text RPG's content-generation batch. A "
    "quest needs an NPC that doesn't exist yet. Given a short hint and the "
    "node they should be found at, invent ONE new NPC: a short lowercase id "
    "with no spaces (e.g. 'old_miller'), a display name, a short "
    "description, a short list of flavor tags (e.g. 'retired', 'veteran' -- "
    "free text, NOT the archetype), and a combat archetype from the fixed "
    "list describing how tough they'd be in a fight, from weakest to "
    "strongest: civilian, merchant, guard, warrior. Pick the archetype that "
    "best matches the NPC's role and description -- a shopkeeper is "
    "usually 'merchant', a hardened fighter is usually 'warrior'."
)

NEW_NPC_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        # "Faction standing: combat trigger" (updates.md, resolved
        # 2026-07-31, Chunk C): a strict enum, never free text -- same
        # discipline skills.EffectKind/events.EventKind already enforce --
        # so a generated NPC can only ever land on a real npc_combat.
        # NPCArchetype, never a hallucinated combat-stat tier.
        "archetype": {"type": "string", "enum": [a.value for a in NPCArchetype]},
    },
    "required": ["id", "name", "description", "tags", "archetype"],
}


@dataclass
class NewNPC:
    id: str
    name: str
    description: str
    tags: list[str] = field(default_factory=list)
    archetype: NPCArchetype = NPCArchetype.CIVILIAN

    @staticmethod
    def from_dict(data: dict) -> NewNPC:
        return NewNPC(
            id=data["id"], name=data["name"],
            description=data["description"], tags=list(data.get("tags", [])),
            archetype=NPCArchetype(data["archetype"]),
        )


def run_npc(registry: LLMRegistry, context: dict, situation: Situation, npc_hint: str) -> NewNPC:
    payload = {"npc_hint": npc_hint, "node_id": situation.node_id, "context": context}
    data = registry.generate("npc", SYSTEM_PROMPT, json.dumps(payload), NEW_NPC_SCHEMA)
    return NewNPC.from_dict(data)


def materialize(state: GameState, node_id: str, new_npc: NewNPC) -> bool:
    """Adds `new_npc` to the live world via `world.add_npc`. Returns False
    (world untouched) if the id already exists or the anchor node doesn't --
    a bad proposal is silently absorbed, same treatment places.py's own
    materialize gives a rejected place.

    The archetype rides along as one more entry in `tags` (deduped) rather
    than a new NPC field -- npc_combat.archetype_for already resolves
    combat stats purely from `NPC.tags` (Chunk A), so a generated NPC needs
    zero special-casing to be exactly as fightable as a hand-seeded one."""
    world = state.world
    if new_npc.id in world.npcs or node_id not in world.nodes:
        return False

    tags = list(new_npc.tags)
    if new_npc.archetype.value not in tags:
        tags.append(new_npc.archetype.value)

    world.add_npc(NPC(
        id=new_npc.id, name=new_npc.name, location_id=node_id,
        description=new_npc.description, tags=tags,
    ))
    return True
