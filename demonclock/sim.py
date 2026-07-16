"""The world-simulation tick engine (SPEC.md §12 step 2, first of four
stages: timers & scheduled events). Grows across stages 2-4 (invasion spread,
price shifts, behavior-profile decay) as more per-day tick steps, but
`advance_time` stays the single choke point every elapsed-time call routes
through.

Zero AI here — pure code (SPEC.md §2's "golden rule": most turns cost zero AI
calls; the daytime engine tick is one of the free ones). `_run_batch` is a
no-op placeholder for the future AI batch so the "exactly ONE batch per
elapsed span, no matter how many days" invariant (SPEC.md §4/§13) is already
structurally true and tested before the batch is real.
"""
from __future__ import annotations

from .events import EventKind, ScheduledEvent
from .state import GameState


def apply_event(state: GameState, event: ScheduledEvent) -> list[str]:
    """Resolves one scheduled event's state change, always through World's
    existing atomic primitives (block_link/unblock_link) — never a direct row
    mutation (SPEC.md §0 pillar 6). Returns narration line(s)."""
    world = state.world
    payload = event.payload

    if event.kind is EventKind.BLOCK_LINK:
        world.block_link(
            payload["from_id"], payload["to_id"], payload["reason"],
            directional_block=payload.get("directional_block", False),
        )
        return [event.description or f"{payload['from_id']} -> {payload['to_id']} is now blocked ({payload['reason']})."]

    if event.kind is EventKind.UNBLOCK_LINK:
        world.unblock_link(
            payload["from_id"], payload["to_id"],
            directional_block=payload.get("directional_block", False),
        )
        return [event.description or f"{payload['from_id']} -> {payload['to_id']} is open again."]

    if event.kind is EventKind.SET_NODE_STATE:
        node = world.nodes[payload["node_id"]]
        node.state = payload["state"]
        return [event.description or f"{node.name} is now {payload['state']}."]

    raise ValueError(f"unhandled event kind: {event.kind!r}")  # unreachable given EventKind's closed enum


def tick_day(state: GameState) -> list[str]:
    """Fires every scheduled event due by the current day (due_day <= today,
    not ==, so an event stranded past-due by a save/load gap still fires
    rather than being silently skipped), in due_day order (ties preserve
    schedule order — Python's sort is stable). Fired events are removed;
    never re-fired."""
    world = state.world
    due = sorted(
        (e for e in world.scheduled_events if e.due_day <= state.clock.current_day),
        key=lambda e: e.due_day,
    )
    log: list[str] = []
    for event in due:
        log.extend(apply_event(state, event))
        world.scheduled_events.remove(event)
    return log


def _run_batch(state: GameState) -> None:
    """Placeholder for the future AI batch (Director -> Story -> Quest ->
    Places, SPEC.md §4/§7) — deliberately a no-op until that step is built."""


def advance_time(state: GameState, days: int) -> list[str]:
    """The coalesced choke point every elapsed-time call routes through
    (travel, rest — combat deliberately never calls this, SPEC.md §4/§6b
    Stage 1). Runs one engine tick per elapsed day (cheap, pure code) but
    calls the AI batch placeholder exactly ONCE regardless of how many days
    elapsed (SPEC.md §13) — a 12-day journey is 12 ticks + 1 batch, not 12."""
    if days < 0:
        raise ValueError("cannot advance a negative number of days")
    if days == 0:
        return []

    log: list[str] = []
    for _ in range(days):
        state.clock.advance(1)
        log.extend(tick_day(state))
    _run_batch(state)
    return log
