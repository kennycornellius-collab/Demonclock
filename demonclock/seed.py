"""Tiny hand-authored starter graph so the loop is walkable without any
generators (those come in a later part). Not meant to be balanced content —
just enough nodes to prove Move/Look/Rest and pathfinding work end to end.
"""
from __future__ import annotations

from .models import Node
from .world import World

START_NODE_ID = "village"

# Which recurring wild foe (see enemies.py) a "dangerous"-tagged node offers via
# Interact -> Fight. A real encounter/spawn system is a later part (SPEC.md §12
# steps 4-5); this is just enough to make combat playable now.
WILD_ENEMY_BY_NODE: dict[str, str] = {
    "wilds": "bramblewood_wolf",
}


def new_default_world() -> World:
    world = World()
    world.add_node(Node(id="village", name="Millhaven Village", type="village", tags=["trade-hub"]))
    world.add_node(Node(id="market", name="Millhaven Market", type="market", tags=["trade-hub"]))
    world.add_node(Node(id="road", name="Old North Road", type="road"))
    world.add_node(Node(id="wilds", name="Bramblewood Wilds", type="wilds", tags=["dangerous"]))

    world.add_link("village", "market", "east", travel_days=1)
    world.add_link("village", "road", "north", travel_days=1)
    world.add_link("road", "wilds", "north", travel_days=2)

    return world
