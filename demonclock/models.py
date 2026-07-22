"""Core data shapes. Plain dataclasses — no behavior, no persistence here.

Attribute set is fixed per SPEC.md §5 / §13: pools (HP, MANA) and stats (STR, MAGIC,
AGILITY, DEFENSE, CHARISMA, PERCEPTION, LUCK) are named fields on Player, not a dict —
there is deliberately no API to add or remove an attribute.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .behavior import BehaviorProfile
from .knowledge import NodeBelief
from .skills import Skill

# Reverse-direction table for the bidirectional link constructor (SPEC.md §3).
OPPOSITE_DIRECTION = {
    "north": "south",
    "south": "north",
    "east": "west",
    "west": "east",
    "up": "down",
    "down": "up",
    "in": "out",
    "out": "in",
}


@dataclass
class Node:
    id: str
    name: str
    type: str = "wilds"
    state: str = "peaceful"
    tags: list[str] = field(default_factory=list)
    last_event_day: int = 0
    prices: dict[str, int] = field(default_factory=dict)  # good_id -> current price (SPEC §4/§10)


@dataclass
class Link:
    from_id: str
    to_id: str
    direction: str
    travel_days: int
    status: str = "open"  # open|blocked
    block_reason: str | None = None
    one_way: bool = False


@dataclass
class InventoryItem:
    item_id: str
    name: str
    quantity: int = 1


@dataclass
class Player:
    name: str
    location_id: str
    hp: int = 100
    hp_max: int = 100
    mana: int = 50
    mana_max: int = 50
    strength: int = 10
    magic: int = 10
    agility: int = 10
    defense: int = 10
    charisma: int = 10
    perception: int = 10
    luck: int = 10
    gold: int = 0
    inventory: list[InventoryItem] = field(default_factory=list)
    skills: list[Skill] = field(default_factory=list)
    # Set the moment a rule-breaking (fair-cost-undercutting) skill is CAST,
    # not when it's created (SPEC.md §6b) — see combat.run_combat.
    creative_mode_used: bool = False
    behavior: BehaviorProfile = field(default_factory=BehaviorProfile)
    # Setback state (SPEC.md §11.1): an ordinary lost fight captures the
    # player rather than ending the game — see setback.py. free_by_day is
    # None whenever not captured.
    captured: bool = False
    ransom_cost: int = 0
    free_by_day: int | None = None
    # Player belief layer (SPEC.md §10): node_id -> last-observed snapshot.
    # Written ONLY by knowledge.observe_node — never by the world-sim tick.
    beliefs: dict[str, NodeBelief] = field(default_factory=dict)
    # Step 6 Chunk B: quests the player accepted from the content pool
    # (SPEC §7/§8) via game.handle_quests. Each entry is a flattened
    # {"id": ..., **payload} dict — the manifest is deliberately dropped,
    # since an accepted quest is never re-validated here (completion/
    # turn-in tracking is explicitly a future step, not this one).
    accepted_quests: list[dict] = field(default_factory=list)
    # SPEC §11.1: true, PERMANENT game-over — reserved for the demon king /
    # designated bosses only (see boss.py), unlike `captured` above, which
    # is always recoverable. None while ongoing; "victory" or "defeat" once
    # boss.run_encounter resolves the demon-king fight (game.py owns the
    # actual ending flow).
    game_over: str | None = None
