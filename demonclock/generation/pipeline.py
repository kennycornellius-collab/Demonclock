"""The orchestrator `sim._run_batch` delegates to (SPEC.md §4/§13: exactly
ONE coalesced call per elapsed-time span, regardless of how many days
elapsed -- enforced by `sim.advance_time` calling `_run_batch` exactly once,
unchanged since Chunk B). Chunk C wires in Story + Quest: each of the two
generation streams (SPEC.md §7's "avoid the echo chamber") produces one
Situation -> one Quest, committed to `state.world.content_pool` via the
existing, canon-gated `pool.commit_or_repair` -- nothing new to plumb into
Step 4's machinery, just a new caller of it. Chunk D adds Places.

Any single generation-role failure degrades gracefully rather than raising
out of a player's turn: a failed Director call skips the WHOLE batch (there's
no intent to hand the rest of the pipeline); a failed Story/Quest call skips
only ITS OWN stream (SPEC.md §1: the pool already absorbs the loss of any
single discarded item -- the other stream, and the next scheduled batch,
carry on unaffected).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..llm.errors import LLMProviderError, MalformedGenerationError
from ..llm.registry import LLMRegistry, NoProviderConfiguredError
from ..pool import commit_or_repair
from .context import build_batch_context
from .director import DirectorIntent, run_director
from .quest import run_quest, run_quest_repair
from .story import run_story

if TYPE_CHECKING:
    from ..canon import RequirementResult
    from ..pool import GeneratedItem
    from ..state import GameState

# Anything a generation-role call can raise that should degrade gracefully
# rather than propagate out of advance_time.
_DEGRADE_ON = (LLMProviderError, MalformedGenerationError, NoProviderConfiguredError)

# Both requested every batch (SPEC.md §7): "responsive" keeps content
# connected to what the player's been doing, "world_driven" keeps the world
# moving independent of them -- neither stream is optional.
_STREAMS = ("responsive", "world_driven")


def run_batch(state: GameState, registry: LLMRegistry) -> DirectorIntent | None:
    """Returns the Director's intent, or None if generation is disabled or
    the Director itself failed -- unchanged contract from Chunk B. As a side
    effect, each stream's Story -> Quest output is committed to
    `state.world.content_pool` (new this chunk); nothing about that side
    effect is narrated to the player directly (generated content goes to the
    pool, not shown live, SPEC.md §7)."""
    if not registry.enabled:
        return None

    context = build_batch_context(state)
    try:
        intent = run_director(registry, context)
    except _DEGRADE_ON:
        return None

    for stream in _STREAMS:
        _generate_and_commit(state, registry, context, intent, stream)

    return intent


def _generate_and_commit(
    state: GameState, registry: LLMRegistry, context: dict, intent: DirectorIntent, stream: str,
) -> None:
    """One stream's Story -> Quest -> commit-or-repair. Swallows a
    generation failure for THIS stream only -- it must never cancel the
    other stream or the Director's already-returned intent."""
    try:
        situation = run_story(registry, context, intent, stream)
        item = run_quest(registry, context, situation)
    except _DEGRADE_ON:
        return

    def repair_fn(failing_item: GeneratedItem, failures: list[RequirementResult]) -> GeneratedItem | None:
        try:
            return run_quest_repair(registry, context, situation, failing_item, failures)
        except _DEGRADE_ON:
            return None

    commit_or_repair(state, state.world.content_pool, item, repair_fn=repair_fn)
