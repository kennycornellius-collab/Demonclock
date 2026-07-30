"""Core data shapes. Plain dataclasses — no behavior, no persistence here.

Attribute set is fixed per SPEC.md §5 / §13: pools (HP, MANA) and stats (STR, MAGIC,
AGILITY, DEFENSE, CHARISMA, PERCEPTION, LUCK) are named fields on Player, not a dict —
there is deliberately no API to add or remove an attribute.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .behavior import BehaviorProfile
from .journal import JournalEntry
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
class NPC:
    """Step 10 Stage 3 (SPEC §6/§7): a talkable, non-combat entity. No HP/
    combat fields on purpose — an NPC is never a fight target, unlike
    enemies.py's Combatant-backed foes."""
    id: str
    name: str
    location_id: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    # Step 10 Stage 4: which Faction (if any) this NPC belongs to. None is a
    # perfectly ordinary, unaffiliated NPC — most of them, until Stage 4's
    # data model has a real trigger to actually assign one.
    faction_id: str | None = None


@dataclass
class Faction:
    """Step 10 Stage 4 (SPEC §8): id/name/description only — standing
    itself lives on Player.faction_standing, not here (a faction is a fixed
    piece of world content; a player's relationship to it is per-player
    state)."""
    id: str
    name: str
    description: str = ""


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
    # {"id": ..., **payload} dict — the precondition manifest is
    # deliberately dropped, since an accepted quest's OFFER validity is
    # never re-checked once accepted. A "completion" key (Step 10 Stage 2),
    # if present, is a second, separate manifest-shaped dict checked only at
    # turn-in — see quests.check_completion/quests.turn_in.
    accepted_quests: list[dict] = field(default_factory=list)
    # SPEC §11.1: true, PERMANENT game-over — reserved for the demon king /
    # designated bosses only (see boss.py), unlike `captured` above, which
    # is always recoverable. None while ongoing; "victory" or "defeat" once
    # boss.run_encounter resolves the demon-king fight (game.py owns the
    # actual ending flow).
    game_over: str | None = None
    # Step 10 Stage 4 (SPEC §8): faction_id -> one of factions.STANDING_TIERS.
    # An absent entry means "neutral" (factions.standing_of's default) --
    # this dict only ever holds a faction once something has actually moved
    # standing off that default (quest turn-in, via factions.adjust_standing --
    # a 2026-07-30 follow-up).
    faction_standing: dict[str, str] = field(default_factory=dict)
    # Player-facing journal/recap (updates.md, surfaced 2026-07-29): the
    # player's own story so far -- places first visited, fights won/lost,
    # quests completed, captures/escapes -- see journal.py for why this is
    # deliberately separate from World.event_log rather than reusing it.
    # Written ONLY by journal.record, from combat.py/setback.py/quests.py/
    # actions.py/game.py at the point each of those facts becomes true.
    journal: list[JournalEntry] = field(default_factory=list)
