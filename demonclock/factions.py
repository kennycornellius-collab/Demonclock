"""Factions + standing (SPEC.md §8, Step 10 Stage 4). Data model + the canon
check only this pass -- no live trigger yet (what actually MOVES standing,
e.g. quest turn-in or combat outcomes, is an explicit future design
conversation, same "checker before real content wires through it" shape
canon.py's own Chunk A took before Step 5 existed to generate anything).

Standing is an ORDERED CATEGORICAL scale, not a numeric score -- SPEC.md
§8's own worked example (`faction_standing(merchants): >= neutral`) only
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
    STANDING_TIERS' ordering (SPEC.md §8's own `>= neutral` example)."""
    return STANDING_TIERS.index(standing_of(player, faction_id)) >= STANDING_TIERS.index(tier)
