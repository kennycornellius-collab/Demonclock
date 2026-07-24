"""The World/Places agent (SPEC.md §7 step 5) -- the last stage in the
Director -> Story -> Quest -> Places pipeline, and the one that closes
Step 5. Extends the graph *only as needed*: it's invoked only when a
committed quest's payload itself signals it wants a place that doesn't
exist yet (`needs_new_place`/`place_hint`, see quest.py) -- an ordinary quest
anchored to an existing node never triggers this agent at all.

The new place is added to the live graph EXCLUSIVELY through the engine's
own constructors (`world.add_node`/`world.add_link`), never a raw row write
(SPEC.md §0 pillar 6) -- `add_link` is what makes the new link
bidirectional-by-construction and enforces `travel_days >= 1`, exactly the
same guarantee every hand-authored link in `seed.py` gets. A proposal the
constructor rejects (an unrecognized direction with no known opposite, a bad
travel_days) is discarded the same way any other malformed generated content
is -- the quest is still committed, just without the new place.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..llm.registry import LLMRegistry
from ..models import Node
from ..world import WorldError

if TYPE_CHECKING:
    from ..state import GameState
    from .story import Situation

SYSTEM_PROMPT = (
    "You are the Places agent for a text RPG's content-generation batch. A "
    "quest needs a place that doesn't exist on the map yet. Given a short "
    "hint and the existing node it should connect from, invent ONE new "
    "place: a short lowercase id with no spaces (e.g. 'abandoned_mine'), a "
    "display name, a short type/tag, a travel direction FROM the anchor node "
    "(one of: north, south, east, west, up, down, in, out), and how many "
    "days it takes to travel there (an integer, at least 1 -- fast-travel "
    "always costs time, instant teleport is never allowed)."
)

NEW_PLACE_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "type": {"type": "string"},
        "direction": {"type": "string"},
        "travel_days": {"type": "integer"},
    },
    "required": ["id", "name", "type", "direction", "travel_days"],
}


@dataclass
class NewPlace:
    id: str
    name: str
    type: str
    direction: str
    travel_days: int

    @staticmethod
    def from_dict(data: dict) -> NewPlace:
        return NewPlace(
            id=data["id"], name=data["name"], type=data["type"],
            direction=data["direction"], travel_days=data["travel_days"],
        )


def run_places(registry: LLMRegistry, context: dict, situation: Situation, place_hint: str) -> NewPlace:
    payload = {
        "place_hint": place_hint,
        "anchor_node_id": situation.node_id,
        "context": context,
    }
    data = registry.generate("places", SYSTEM_PROMPT, json.dumps(payload), NEW_PLACE_SCHEMA)
    return NewPlace.from_dict(data)


def materialize(state: GameState, anchor_node_id: str, new_place: NewPlace) -> bool:
    """Adds `new_place` to the live graph via `world.add_node`/`add_link`.
    Returns False (and leaves the world untouched) if the id already exists,
    the anchor doesn't, or the constructor itself rejects the direction/
    travel_days/direction-collision -- a bad proposal is silently absorbed,
    same as any other discarded generated item, never a crash. `add_link`
    itself now rejects a direction that `anchor_node_id` already has an
    outgoing link in (world.py's own invariant), so that case reaches this
    function as a `WorldError` exactly like a bad direction/travel_days
    already did -- the `except WorldError` below rolls the node back the
    same way for all three."""
    world = state.world
    if new_place.id in world.nodes or anchor_node_id not in world.nodes:
        return False

    world.add_node(Node(id=new_place.id, name=new_place.name, type=new_place.type))
    try:
        world.add_link(anchor_node_id, new_place.id, new_place.direction, travel_days=new_place.travel_days)
    except WorldError:
        # Roll back the node so a rejected proposal never leaves an
        # orphaned, unreachable node sitting in the graph.
        del world.nodes[new_place.id]
        return False
    return True
