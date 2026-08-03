"""A player-facing journal/recap (surfaced 2026-07-29): a small,
append-only, PLAYER-scoped log of the player's own story so far (places
first visited, fights won/lost, quests completed, captures/escapes),
distinct from `history.py`/`World.event_log` (which is world-wide, feeds
rumors/the newspaper, and is tightly coupled to `events.EventKind`'s
scheduled-event vocabulary -- each `EventKind` maps 1:1 to a `sim.
apply_event` handler for something FIRED by the tick engine, never
something the player does directly, so extending it with player-action
kinds like "quest_completed" would be a semantic misuse of that enum, not
a natural fit). This module is deliberately the simpler of the two: no
enum, no validation, no world truth -- just a flat chronological list of
short lines, mirroring `history.LogEntry`'s own append-only shape without
borrowing its coupling to `EventKind`.

Lives on `Player`, not `World` -- a player's own story is player state,
the same reasoning `Player.faction_standing`/`Player.beliefs` already
follow, not something other entities perceive the way `World.event_log`
(rumor-sourced) is.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class JournalEntry:
    day: int
    description: str

    def to_dict(self) -> dict:
        return {"day": self.day, "description": self.description}

    @staticmethod
    def from_dict(data: dict) -> JournalEntry:
        return JournalEntry(day=data["day"], description=data["description"])


def record(journal: list[JournalEntry], day: int, description: str) -> None:
    """Append one entry. The ONLY way an entry enters the journal — never
    removed, never edited, same append-only discipline as history.record."""
    journal.append(JournalEntry(day=day, description=description))
