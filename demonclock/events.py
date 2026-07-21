"""Scheduled world events (SPEC.md §3/§12 step 2) — the "timers" half of world
simulation. Same discipline as `skills.py`'s effects vocabulary: `kind` is a
FIXED enumerated set, never free text, never AI-adjudicated (SPEC.md §13).
Extend the enum deliberately per build stage (invasion/price-shift kinds land
in later stages) — never open it to arbitrary strings.

An event only ever *describes* a state change; `sim.apply_event` is what
actually performs it, always through World's existing atomic state-flip
primitives (`block_link`/`unblock_link`) — never a direct row mutation
(SPEC.md §0 pillar 6).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class EventKind(str, Enum):
    BLOCK_LINK = "block_link"
    UNBLOCK_LINK = "unblock_link"
    SET_NODE_STATE = "set_node_state"
    INVASION_SPREAD = "invasion_spread"  # Stage 2 (SPEC.md §3) — see sim.apply_event
    PRICE_SHIFT = "price_shift"  # Stage 3 (SPEC.md §4/§10) — see economy.apply_price_shift


# Required payload keys per kind — validate_event's structural boundary.
_REQUIRED_PAYLOAD_KEYS: dict[EventKind, tuple[str, ...]] = {
    EventKind.BLOCK_LINK: ("from_id", "to_id", "reason"),
    EventKind.UNBLOCK_LINK: ("from_id", "to_id"),
    EventKind.SET_NODE_STATE: ("node_id", "state"),
    EventKind.INVASION_SPREAD: (),  # derives everything from live world state at fire time
    EventKind.PRICE_SHIFT: (),  # ditto
}


@dataclass
class ScheduledEvent:
    due_day: int
    kind: EventKind
    payload: dict = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "due_day": self.due_day,
            "kind": self.kind.value,
            "payload": self.payload,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScheduledEvent":
        return cls(
            due_day=data["due_day"],
            kind=EventKind(data["kind"]),
            payload=data.get("payload", {}),
            description=data.get("description", ""),
        )


class EventError(ValueError):
    pass


def validate_event(event: ScheduledEvent) -> None:
    """Guards the enum boundary — a scheduled event's payload must carry the
    keys its kind needs to be resolvable by `sim.apply_event`. Not a
    world-state check (e.g. it does NOT verify the link exists yet); that's
    `apply_event`'s job at fire time, since the world may have changed
    between scheduling and firing.

    KNOWN SIMPLIFICATION (found in a caveat sweep, not yet fixed): this
    function is never actually called anywhere — not from
    `World.schedule_event`, not from `sim.apply_event`, not from any test.
    A malformed `ScheduledEvent` (missing a required payload key, e.g. from
    a future generation-authored event) currently fails at FIRE time as a
    raw `KeyError` inside `apply_event`'s payload dict access, not the clean
    `EventError` this function exists to raise. Revisit by calling this from
    `World.schedule_event` (or wherever a `ScheduledEvent` first gets
    constructed from untrusted/generated data)."""
    required = _REQUIRED_PAYLOAD_KEYS[event.kind]
    missing = [key for key in required if key not in event.payload]
    if missing:
        raise EventError(f"{event.kind.value} event missing payload keys: {missing}")
