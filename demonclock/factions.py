"""Factions + standing (Step 10 Stage 4). Data model + canon
check shipped this stage; `adjust_standing` (a 2026-07-30 follow-up) is the
first live trigger that actually MOVES standing, called from
`quests.turn_in` via a quest's optional `faction_standing_delta` payload
(generation/quest.py). Combat outcomes / trade affiliation as additional
triggers remain an explicit future design conversation.

Standing is an ORDERED CATEGORICAL scale, not a numeric score -- the
design's own worked example (`faction_standing(merchants): >= neutral`) only
makes clean sense against named tiers and an ordering comparison, so this
follows the spec's own wording literally rather than inventing a numeric
range with nothing yet to calibrate it against.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Player

STANDING_TIERS = ("hostile", "unfriendly", "neutral", "friendly", "allied")

# A faction the player has no recorded standing with defaults here --
# Player.faction_standing only ever holds an entry once something has
# actually moved it off the default, same "absent means the neutral
# default" convention knowledge.NodeBelief-less nodes and behavior's
# zeroed counters already use elsewhere in this codebase.
DEFAULT_STANDING = "neutral"


def standing_of(player: Player, faction_id: str) -> str:
    return player.faction_standing.get(faction_id, DEFAULT_STANDING)


def meets_standing(player: Player, faction_id: str, tier: str) -> bool:
    """True if the player's standing with faction_id is AT LEAST `tier` on
    STANDING_TIERS' ordering (the design's own `>= neutral` example)."""
    return STANDING_TIERS.index(standing_of(player, faction_id)) >= STANDING_TIERS.index(tier)


def adjust_standing(player: Player, faction_id: str, tiers: int) -> str:
    """The first live trigger that actually moves standing (Step 10 Stage 4
    shipped the data model + checker only; this closes the "no live trigger
    moves standing yet" gap the module docstring flagged, called from
    quests.turn_in). Shifts `tiers` STEPS along STANDING_TIERS' ordering --
    positive moves toward friendlier tiers, negative toward more hostile --
    clamped to the scale's own bounds rather than raising on an
    out-of-range shift (e.g. +5 from "neutral" just lands on "allied", the
    top of the scale, same "never crash on an extreme input" posture as
    every other engine-enforced mutation in this codebase). Writes the
    result to Player.faction_standing and returns the new tier."""
    current_index = STANDING_TIERS.index(standing_of(player, faction_id))
    new_index = max(0, min(len(STANDING_TIERS) - 1, current_index + tiers))
    new_tier = STANDING_TIERS[new_index]
    player.faction_standing[faction_id] = new_tier
    return new_tier
