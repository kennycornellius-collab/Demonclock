"""BehaviorProfile (SPEC.md §5, world-sim Stage 4): pure-code action counters
with exponential decay, feeding a derived_role_hint string. The engine only
*watches* here — no AI. The Director (not yet built, SPEC.md §7) will be the
first actual reader of this data at batch-generation time; until then it's
background bookkeeping, surfaced to the player only as a minor inventory-screen
flavor line.

Only combat_actions and recent_locations are wired to real gameplay this
stage, since trade/dialogue/crafting have no systems yet (no buy/sell, no NPC
dialogue, no crafting) — their counters and record_* functions exist now so
those future systems just call in, rather than needing this module reworked.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# SPEC.md §5: "start with ×0.97/day, half-life ~= 23 in-game days; tune in
# play" — same "start rough, calibrate by feel" status as combat.py's
# DOT_DURATION etc. and skills.py's fair-cost constants (SPEC.md §11).
DECAY_FACTOR = 0.97

# Below this, a decaying counter is treated as fully cooled off rather than
# asymptotically approaching zero forever — keeps saved data and the role-hint
# threshold check clean.
DECAY_FLOOR = 0.01

RECENT_LOCATIONS_MAX = 5

ROLE_HINT_THRESHOLD = 3.0


@dataclass
class BehaviorProfile:
    trade_actions: float = 0.0
    combat_actions: float = 0.0
    dialogue_actions: float = 0.0
    crafting_actions: float = 0.0
    last_gold: int = 0
    gold_trend: str = "flat"  # rising|flat|falling
    recent_locations: list[str] = field(default_factory=list)


def record_combat_action(profile: BehaviorProfile) -> None:
    profile.combat_actions += 1.0


def record_trade_action(profile: BehaviorProfile) -> None:
    profile.trade_actions += 1.0


def record_dialogue_action(profile: BehaviorProfile) -> None:
    profile.dialogue_actions += 1.0


def record_crafting_action(profile: BehaviorProfile) -> None:
    profile.crafting_actions += 1.0


def record_location(profile: BehaviorProfile, location_id: str) -> None:
    """Appends location_id unless it's already the most recent entry (so
    resting in place doesn't pad the list), keeping only the most recent
    RECENT_LOCATIONS_MAX."""
    if profile.recent_locations and profile.recent_locations[-1] == location_id:
        return
    profile.recent_locations.append(location_id)
    del profile.recent_locations[:-RECENT_LOCATIONS_MAX]


def _decay(value: float) -> float:
    decayed = value * DECAY_FACTOR
    return 0.0 if decayed < DECAY_FLOOR else decayed


def tick(profile: BehaviorProfile, current_gold: int) -> None:
    """Runs once per elapsed in-game day (called from sim.advance_time,
    alongside the other Step 2 systems) — decays every action counter and
    refreshes gold_trend by comparing against the gold seen on the last tick."""
    profile.trade_actions = _decay(profile.trade_actions)
    profile.combat_actions = _decay(profile.combat_actions)
    profile.dialogue_actions = _decay(profile.dialogue_actions)
    profile.crafting_actions = _decay(profile.crafting_actions)

    if current_gold > profile.last_gold:
        profile.gold_trend = "rising"
    elif current_gold < profile.last_gold:
        profile.gold_trend = "falling"
    else:
        profile.gold_trend = "flat"
    profile.last_gold = current_gold


def derived_role_hint(profile: BehaviorProfile) -> str:
    """Simple threshold tags over the decayed counters (SPEC.md §5's own
    example: "trade-focused, combat-averse, socially active") — deliberately
    not a fixed/negative label for systems that don't exist yet (trade/
    dialogue/crafting sitting at 0 forever until those systems land isn't
    "averse", it's untested, so untested counters simply produce no tag)."""
    tags: list[str] = []
    if profile.combat_actions >= ROLE_HINT_THRESHOLD:
        tags.append("combat-focused")
    if profile.trade_actions >= ROLE_HINT_THRESHOLD:
        tags.append("trade-focused")
    if profile.dialogue_actions >= ROLE_HINT_THRESHOLD:
        tags.append("socially active")
    if profile.crafting_actions >= ROLE_HINT_THRESHOLD:
        tags.append("crafting-focused")
    if profile.gold_trend == "rising":
        tags.append("prospering")
    elif profile.gold_trend == "falling":
        tags.append("financially strained")
    return ", ".join(tags) if tags else "still finding their way"
