"""Quest completion / turn-in (Step 10 Stage 2). The existing
`canon.RequirementKind` vocabulary + `check_manifest` checker were built
(Step 4) purely as a pre-commit/pre-pull "still valid to OFFER" gate --
nothing about the checker itself is offer-specific, so the same machinery
doubles as a post-acceptance "objective actually met" check with zero
changes beyond adding one new quantity-aware RequirementKind (canon.py).

An accepted quest is a flattened `dict` on `Player.accepted_quests` (Step 6
Chunk B), not a dataclass -- its own `manifest` (the precondition) is
already dropped and never re-validated once accepted. A `completion` key,
if present (generation/quest.py's QUEST_SCHEMA now always includes one; a
hand-built quest in a test may omit it), holds a SECOND, separate
precondition-manifest-shaped dict -- the actual objective, checked only
here, never at accept time.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from . import factions, journal
from .canon import CheckResult, PreconditionManifest, check_manifest

if TYPE_CHECKING:
    from .state import GameState

# A quest with no "completion" key (e.g. a hand-built quest from before this
# stage) has no objective to check -- treated as trivially complete rather
# than permanently unturnable-in.
_EMPTY_MANIFEST: dict = {"requirements": []}


def check_completion(state: GameState, quest: dict) -> CheckResult:
    manifest = PreconditionManifest.from_dict(quest.get("completion", _EMPTY_MANIFEST))
    return check_manifest(state, manifest)


def turn_in(state: GameState, quest: dict) -> list[str]:
    """Never mutates state on failure (completion requirements not yet met).
    On success: grants reward_gold, applies an optional faction_standing_delta
    (generation/quest.py's schema, Step 10 Stage 4 follow-up -- the first
    live trigger that actually moves standing), and removes the quest from
    Player.accepted_quests -- no location requirement (no NPC to return to
    exists yet)."""
    result = check_completion(state, quest)
    if not result.passed:
        reasons = "; ".join(failure.reason for failure in result.failures)
        return [f"Not finished yet: {reasons}."]

    reward = quest.get("reward_gold", 0)
    state.player.gold += reward
    title = quest.get("title", quest.get("id", "quest"))
    lines = [f"Quest complete: {title}! You receive {reward} gold."]
    journal.record(state.player.journal, state.clock.current_day, f"Completed quest: {title} (+{reward} gold).")

    delta = quest.get("faction_standing_delta")
    if isinstance(delta, dict):
        lines.extend(_apply_faction_standing_delta(state, delta))

    state.player.accepted_quests.remove(quest)
    return lines


def _apply_faction_standing_delta(state: GameState, delta: dict) -> list[str]:
    """A dangling/malformed faction_standing_delta (unknown faction_id, or a
    non-numeric tiers -- both possible from an AI-generated quest payload
    that was never canon-checked, unlike the two manifests) is silently
    skipped rather than failing the whole turn-in -- same "never crash on a
    dangling AI-proposed reference" posture as canon.py's own checks, just
    applied here since this field isn't part of either PreconditionManifest."""
    faction_id, tiers = delta.get("faction_id"), delta.get("tiers")
    if faction_id not in state.world.factions:
        return []
    if not isinstance(tiers, (int, float)) or isinstance(tiers, bool) or tiers == 0:
        return []
    new_tier = factions.adjust_standing(state.player, faction_id, int(tiers))
    faction_name = state.world.factions[faction_id].name
    return [f"Your standing with {faction_name} is now {new_tier}."]
