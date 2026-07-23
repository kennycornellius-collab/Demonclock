"""The orchestrator `sim._run_batch` delegates to (SPEC.md §4/§13: exactly
ONE coalesced call per elapsed-time span, regardless of how many days
elapsed -- enforced by `sim.advance_time` calling `_run_batch` exactly once,
unchanged since Chunk B). Chunk C wired in Story + Quest: each of the two
generation streams (SPEC.md §7's "avoid the echo chamber") produces one
Situation -> one Quest, committed to `state.world.content_pool` via the
existing, canon-gated `pool.commit_or_repair`. Chunk D adds Places -- the
last stage, run only when a committed quest's own payload signals it wants a
place that doesn't exist yet (`quest.py`'s `needs_new_place`/`place_hint`) --
and closes Step 5.

Any single generation-role failure degrades gracefully rather than raising
out of a player's turn: a failed Director call skips the WHOLE batch (there's
no intent to hand the rest of the pipeline); a failed Story/Quest call skips
only ITS OWN stream; a failed/declined Places call just means the quest
commits without its requested new place (SPEC.md §1: the pool already
absorbs the loss of any single discarded item -- a missing "nice to have"
extension is an even smaller loss than that).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..llm.errors import LLMProviderError, MalformedGenerationError
from ..llm.registry import LLMRegistry, NoProviderConfiguredError
from ..pool import commit_or_repair
from .context import build_batch_context
from .director import DirectorIntent, run_director
from .flavor import run_flavor
from .places import materialize, run_places
from .quest import run_quest, run_quest_repair
from .story import run_story

if TYPE_CHECKING:
    from ..canon import RequirementResult
    from ..pool import GeneratedItem
    from ..state import GameState
    from .story import Situation

# Anything a generation-role call can raise that should degrade gracefully
# rather than propagate out of advance_time.
_DEGRADE_ON = (LLMProviderError, MalformedGenerationError, NoProviderConfiguredError)

# Both requested every batch (SPEC.md §7): "responsive" keeps content
# connected to what the player's been doing, "world_driven" keeps the world
# moving independent of them -- neither stream is optional.
_STREAMS = ("responsive", "world_driven")


def run_batch(state: GameState, registry: LLMRegistry) -> DirectorIntent | None:
    """Returns the Director's intent, or None if generation is disabled or
    the Director itself failed -- unchanged contract since Chunk B. As a
    side effect, each stream's Story -> Quest output is committed to
    `state.world.content_pool`, and (Chunk D) the graph is extended via
    `world.add_node`/`add_link` if a committed quest asked for a new place;
    nothing about either side effect is narrated to the player directly
    (generated content goes to the pool, not shown live, SPEC.md §7)."""
    if not registry.enabled:
        return None

    context = build_batch_context(state)
    try:
        intent = run_director(registry, context)
    except _DEGRADE_ON:
        return None

    for stream in _STREAMS:
        _generate_and_commit(state, registry, context, intent, stream)

    _generate_flavor(state, registry, context)

    return intent


def _generate_flavor(state: GameState, registry: LLMRegistry, context: dict) -> None:
    """Step 7 Chunk C: refreshes `state.world.node_flavor` for whichever
    nodes this batch's bounded context covered. Not stream-specific (flavor
    isn't responsive/world-driven content, just ambient color) and, like
    every other per-role failure in this pipeline, must never take down the
    Director's already-returned intent or either content stream's commits."""
    try:
        lines = run_flavor(registry, context)
    except _DEGRADE_ON:
        return
    state.world.node_flavor.update(lines)


def _generate_and_commit(
    state: GameState, registry: LLMRegistry, context: dict, intent: DirectorIntent, stream: str,
) -> None:
    """One stream's Story -> Quest -> (maybe) Places -> commit-or-repair.
    Swallows a generation failure for THIS stream only -- it must never
    cancel the other stream or the Director's already-returned intent."""
    try:
        situation = run_story(registry, context, intent, stream)
        item = run_quest(registry, context, situation)
    except _DEGRADE_ON:
        return

    _maybe_extend_world(state, registry, context, situation, item)

    def repair_fn(failing_item: GeneratedItem, failures: list[RequirementResult]) -> GeneratedItem | None:
        try:
            return run_quest_repair(registry, context, situation, failing_item, failures)
        except _DEGRADE_ON:
            return None

    commit_or_repair(state, state.world.content_pool, item, repair_fn=repair_fn)


def _maybe_extend_world(
    state: GameState, registry: LLMRegistry, context: dict, situation: Situation, item: GeneratedItem,
) -> None:
    """SPEC.md §7 step 5: Places runs LAST, and only when the quest itself
    signals it needs a place that doesn't exist yet. A failure here (no
    "places" role configured, a bad LLM proposal, an unresolvable direction)
    is silently absorbed -- the quest still commits without the new place,
    the same partial-shortfall handling used everywhere else in this
    pipeline."""
    if not item.payload.get("needs_new_place"):
        return

    place_hint = item.payload.get("place_hint", "")
    try:
        new_place = run_places(registry, context, situation, place_hint)
    except _DEGRADE_ON:
        return
    materialize(state, situation.node_id, new_place)
