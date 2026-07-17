"""Core data shapes. Plain dataclasses — no behavior, no persistence here.

Attribute set is fixed per SPEC.md §5 / §13: pools (HP, MANA) and stats (STR, MAGIC,
AGILITY, DEFENSE, CHARISMA, PERCEPTION, LUCK) are named fields on Player, not a dict —
there is deliberately no API to add or remove an attribute.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .behavior import BehaviorProfile
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
