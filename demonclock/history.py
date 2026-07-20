"""Append-only history/consequence log (SPEC.md §9 subset — third of Step 3's
four stages, and the prerequisite Stage 4's rumor propagation needs).

SPEC.md §9 draws two distinct stores: the live world/entity DB (pruned,
mutated in place — Node.state, Link.status, ...) and this log, small facts
that are NEVER deleted ("the permanent memory that makes the world feel
like it remembers the player"). Nothing reads this log yet — that's
Stage 4's job. This stage only builds the write side and proves real world
events land in it, same shape as world-sim Stage 1 (timers) preceding the
invasion payoff.

`kind` reuses `events.EventKind` rather than a parallel string enum — same
"enumerated vocabulary, never free text" discipline as everywhere else in
the project (SPEC.md §13).
"""
from __future__ import annotations

from dataclasses import dataclass

from .events import EventKind


@dataclass
class LogEntry:
    day: int
    node_id: str
    kind: EventKind
    description: str

    def to_dict(self) -> dict:
        return {
            "day": self.day,
            "node_id": self.node_id,
            "kind": self.kind.value,
            "description": self.description,
        }

    @staticmethod
    def from_dict(data: dict) -> LogEntry:
        return LogEntry(
            day=data["day"],
            node_id=data["node_id"],
            kind=EventKind(data["kind"]),
            description=data["description"],
        )


def record(log: list[LogEntry], day: int, node_id: str, kind: EventKind, description: str) -> None:
    """Append one fact. The ONLY way an entry enters the log — never removed,
    never edited (SPEC.md §9: "append-only, never deleted")."""
    log.append(LogEntry(day=day, node_id=node_id, kind=kind, description=description))
