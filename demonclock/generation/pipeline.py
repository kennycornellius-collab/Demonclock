"""The orchestrator `sim._run_batch` delegates to (SPEC.md §4/§13: exactly
ONE coalesced call per elapsed-time span, regardless of how many days
elapsed -- enforced by `sim.advance_time` calling `_run_batch` exactly once,
unchanged by this chunk). This chunk runs only the Director; Chunk C wires in
Story + Quest (committing generated items through the existing
`pool.commit_or_repair`), and Chunk D adds Places.

Any generation-role failure degrades the WHOLE batch to a no-op rather than
raising out of a player's turn -- a failed generation call just means the
content pool doesn't get filled this cycle (SPEC.md §1: the pool already
absorbs the loss of any single discarded item; a whole skipped batch is the
same idea at a larger grain), never a crash or a stuck game.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..llm.errors import LLMProviderError, MalformedGenerationError
from ..llm.registry import LLMRegistry, NoProviderConfiguredError
from .context import build_batch_context
from .director import DirectorIntent, run_director

if TYPE_CHECKING:
    from ..state import GameState

# Anything a generation-role call can raise that should degrade the batch to
# a no-op rather than propagate out of advance_time.
_DEGRADE_ON = (LLMProviderError, MalformedGenerationError, NoProviderConfiguredError)


def run_batch(state: GameState, registry: LLMRegistry) -> DirectorIntent | None:
    """Returns the Director's intent, or None if generation is disabled or
    degraded this cycle -- mostly for testability, since nothing about the
    pipeline's outcome is narrated to the player directly (generated content
    goes to the pool, not shown live, SPEC.md §7)."""
    if not registry.enabled:
        return None

    context = build_batch_context(state)
    try:
        return run_director(registry, context)
    except _DEGRADE_ON:
        return None
