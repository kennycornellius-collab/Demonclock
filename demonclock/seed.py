"""Tiny hand-authored starter graph so the loop is walkable without any
generators (those come in a later part). Not meant to be balanced content —
just enough nodes to prove Move/Look/Rest and pathfinding work end to end.
"""
from __future__ import annotations

from .events import EventKind, ScheduledEvent
from .models import NPC, Faction, Node
from .world import World

START_NODE_ID = "village"

# Which recurring wild foe(s) (see enemies.py) a "dangerous"-tagged node
# offers via Interact -> Fight. A real encounter/spawn system is a later
# part; this is just enough to make combat playable
# now. node_id -> list[enemy_id] (Step 10 Stage 6 — a single-enemy node is
# just a one-item list; "wilds" seeds a real pack of two wolves so ordinary
# multi-enemy combat (combat.run_group_combat) has real seeded content to
# exercise, not just tests).
WILD_ENEMY_BY_NODE: dict[str, list[str]] = {
    "wilds": ["bramblewood_wolf", "bramblewood_wolf"],
}


def new_default_world() -> World:
    world = World()
    # "workshop" (Step 10 Stage 5): gates Interact -> Craft the same way
    # WILD_ENEMY_BY_NODE gates Fight — Hana the Miller's grain mill (see
    # the NPC seeded below) makes village the natural home for Bake Bread.
    world.add_node(Node(id="village", name="Millhaven Village", type="village", tags=["trade-hub", "workshop"]))
    # Seeded with tracked prices (world-sim Stage 3: price shifts)
    # — the only trade-hub node with tracked prices this stage. Wool/iron_ore
    # (added alongside grain as the "economy depth" follow-up)
    # feed crafting.RECIPES' spin_cloth/smelt_iron the same way grain feeds
    # bake_bread — buy the raw good here, craft it at the village workshop.
    world.add_node(Node(
        id="market", name="Millhaven Market", type="market", tags=["trade-hub"],
        prices={"grain": 10, "wool": 8, "iron_ore": 15},
        # "Faction standing: trade trigger" (resolved
        # 2026-07-31, Chunk D): trade.buy/sell nudges standing with
        # whichever faction (if any) a node is affiliated with -- market is
        # the one node seeded that way, matching Warden Oskar's own guard
        # presence here and Hana's merchants affiliation at the mill.
        faction_id="merchants",
    ))
    world.add_node(Node(id="road", name="Old North Road", type="road"))
    # Starts "occupied" — it borders demon-king territory (world-sim
    # Stage 2: invasion-as-graph-spread). No bootstrap event needed for this;
    # the OBSERVABLE spread (other nodes falling, links cutting off) still
    # only happens later, on the invasion's own timer below.
    world.add_node(Node(id="wilds", name="Bramblewood Wilds", type="wilds", tags=["dangerous"], state="occupied"))

    world.add_link("village", "market", "east", travel_days=1)
    world.add_link("village", "road", "north", travel_days=1)
    world.add_link("road", "wilds", "north", travel_days=2)

    # Step 10 Stage 4 follow-up: one hand-seeded faction, matching the
    # design's own worked example ("faction_standing(merchants): >= neutral")
    # literally by id -- previously the whole faction system (factions.py,
    # canon.RequirementKind.FACTION_STANDING_AT_LEAST, Player.
    # faction_standing) was unreachable content, since nothing ever created
    # a real Faction for anything to check standing against. No generator
    # creates factions yet (same "hand-authored, small by design" status as
    # WILD_ENEMY_BY_NODE), which is also why generation/context.py can
    # afford to include ALL of world.factions in every batch's bounded slice.
    world.add_faction(Faction(
        id="merchants", name="The Merchants' Guild",
        description="Millhaven's trade guild -- millers, traders, and the market warden's watch.",
    ))

    # Step 10 Stage 3: a couple of hand-seeded starter NPCs (same
    # "immediately playable, no generator required" role as
    # WILD_ENEMY_BY_NODE above) alongside generation/npc.py's later,
    # quest-triggered agent.
    world.add_npc(NPC(
        id="miller_hana", name="Hana the Miller", location_id="village",
        description="Runs Millhaven's grain mill, flour dust in her hair.",
        tags=["villager", "merchant"], faction_id="merchants",
    ))
    world.add_npc(NPC(
        id="market_warden_oskar", name="Warden Oskar", location_id="market",
        description="Keeps the peace at Millhaven Market, eyes always on the road north.",
        tags=["guard"],
    ))

    # "Bosses as situations, not HP checks," Chunk B:
    # wilds is where the invasion originates (see the "occupied" comment
    # below), so it's also where sim._reveal_demon_king retags the node
    # "demon_king" once the whole graph has fallen — see boss.py for the
    # actual encounter, game.handle_interact for the trigger.
    world.invasion_origin_id = "wilds"

    # Demo scheduled events (world-sim Stage 1: timers & scheduled
    # events) — proves the world moves on its own timer
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

    # The demon-king invasion (world-sim Stage 2) — an ambient
    # pressure source ticking regardless of what the player
    # does. First attempt at day 15, comfortably after the blizzard above
    # fully resolves (day 9), so their shared road<->wilds link isn't fought
    # over by two systems in the same window. sim._apply_invasion_spread
    # reschedules itself every INVASION_SPREAD_INTERVAL_DAYS until the whole
    # reachable graph falls — on this 4-node line that's day 15 (road),
    # day 20 (village), day 25 (market), then it stops.
    world.schedule_event(ScheduledEvent(due_day=15, kind=EventKind.INVASION_SPREAD))

    # Price volatility (world-sim Stage 3) — an ongoing ambient
    # pressure source that, unlike the invasion, never stops
    # rescheduling. First attempt at day 3, before the blizzard, so it's
    # background noise from early on. Grain at Millhaven Market holds steady
    # until the invasion's approach (village falling day 20, market itself
    # day 25) starts pushing its price up — the "grain prices
    # spike (economy tell)" made real.
    world.schedule_event(ScheduledEvent(due_day=3, kind=EventKind.PRICE_SHIFT))

    return world
