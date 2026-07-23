"""The push newspaper (SPEC.md §10, Step 6 Chunk A): a short wake-time summary
of info that LEAKED to the player's node while they slept.

Distinct from `game.handle_ask_around` (the pull-primary channel, which shows
EVERYTHING `rumors.rumors_reaching` currently returns): the newspaper is push
and precise — "leaked" means exactly the rumor objects that started reaching
the node BETWEEN falling asleep and waking up, not the full cumulative set.
Reuses `rumors.rumors_reaching` unchanged; this module only diffs two
snapshots of it and formats the result. Triggers ONLY from Rest (sleeping) —
SPEC.md §10 frames the newspaper specifically as "on wake," distinct from the
batch trigger itself, which already fires on any elapsed time (move, rest,
fast-travel alike, since Step 5 Chunk B).
"""
from __future__ import annotations

from . import rumors
from .generation.narrator import reword_rumor
from .llm.registry import LLMRegistry
from .rumors import Rumor
from .world import World


def leaked_since(world: World, node_id: str, day_before: int, day_after: int) -> list[Rumor]:
    """Rumors reaching `node_id` at `day_after` that were NOT already reaching
    it at `day_before` — a rumor's hops/confidence/text are pure functions of
    the graph's current topology and elapsed days (see rumors.py), so the
    pair `(origin_node_id, day_originated)` alone identifies "the same
    underlying fact" across both snapshots, regardless of any distortion
    template happening to differ between calls (it won't, by construction,
    but the key doesn't rely on that)."""
    before_keys = {
        (rumor.origin_node_id, rumor.day_originated)
        for rumor in rumors.rumors_reaching(world, node_id, day_before)
    }
    after = rumors.rumors_reaching(world, node_id, day_after)
    return [
        rumor for rumor in after
        if (rumor.origin_node_id, rumor.day_originated) not in before_keys
    ]


def format_newspaper(
    leaked: list[Rumor], registry: LLMRegistry | None = None, derived_role_hint: str | None = None,
) -> str | None:
    """None for an empty list — no awkward "nothing happened" newspaper on an
    ordinary quiet night. Otherwise a short block, one line per leaked rumor,
    same confidence formatting `handle_ask_around` already uses. `registry`
    is optional (Step 7 Chunk A) and, when configured, rewords each rumor's
    already-decided text via the `narrator` role — omitting it (the default)
    reproduces the exact plain template wording this function always
    produced, so every pre-Chunk-A caller/test keeps working unchanged.
    `derived_role_hint` (Step 7 Chunk D) is optional tone-only guidance
    passed straight through to `reword_rumor`."""
    if not leaked:
        return None
    lines = ["--- Word reached you while you slept ---"]
    lines += [
        f"  ({rumor.confidence:.0%} sure) {reword_rumor(registry, rumor.text, rumor.confidence, derived_role_hint)}"
        for rumor in leaked
    ]
    return "\n".join(lines)
