"""Tiny hand-authored starter graph so the loop is walkable without any
generators (those come in a later part). Not meant to be balanced content —
just enough nodes to prove Move/Look/Rest and pathfinding work end to end.
"""
from __future__ import annotations

from .events import EventKind, ScheduledEvent
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
    # Starts "occupied" — it borders demon-king territory (SPEC.md §12 step 2,
    # Stage 2: invasion-as-graph-spread). No bootstrap event needed for this;
    # the OBSERVABLE spread (other nodes falling, links cutting off) still
    # only happens later, on the invasion's own timer below.
    world.add_node(Node(id="wilds", name="Bramblewood Wilds", type="wilds", tags=["dangerous"], state="occupied"))

    world.add_link("village", "market", "east", travel_days=1)
    world.add_link("village", "road", "north", travel_days=1)
    world.add_link("road", "wilds", "north", travel_days=2)

    # Demo scheduled events (SPEC.md §12 step 2, Stage 1: timers & scheduled
    # events) — proves the world moves on its own timer (SPEC.md §0 pillar 4)
    # even in a fresh game nobody has touched yet. A blizzard closes the
    # northern pass, then self-clears: demonstrates both the atomic
    # block/unblock invariant and a self-clearing timer in real play. The
    # pass reopens on its own, so the optional wilds encounter is only ever
    # temporarily gated — never a soft-lock.
    world.schedule_event(ScheduledEvent(
        due_day=4,
        kind=EventKind.BLOCK_LINK,
        payload={"from_id": "road", "to_id": "wilds", "reason": "snow"},
        description="A blizzard closes the northern pass.",
    ))
    world.schedule_event(ScheduledEvent(
        due_day=9,
        kind=EventKind.UNBLOCK_LINK,
        payload={"from_id": "road", "to_id": "wilds"},
        description="The blizzard clears; the northern pass is open again.",
    ))

    # The demon-king invasion (SPEC.md §12 step 2, Stage 2) — an ambient
    # pressure source (SPEC.md §4) ticking regardless of what the player
    # does. First attempt at day 15, comfortably after the blizzard above
    # fully resolves (day 9), so their shared road<->wilds link isn't fought
    # over by two systems in the same window. sim._apply_invasion_spread
    # reschedules itself every INVASION_SPREAD_INTERVAL_DAYS until the whole
    # reachable graph falls — on this 4-node line that's day 15 (road),
    # day 20 (village), day 25 (market), then it stops.
    world.schedule_event(ScheduledEvent(due_day=15, kind=EventKind.INVASION_SPREAD))

    return world
