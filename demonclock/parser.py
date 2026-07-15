"""Deterministic verb parser (SPEC.md §6). Only runs inside the free-text box —
menus handle the common case without ever reaching this module.

Novel phrasing that doesn't match a verb returns UNRECOGNIZED rather than
guessing. There is deliberately no LLM fallback wired in this part of the
build (SPEC.md §12 step 1 is AI-free); that comes in a later part.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ActionType(str, Enum):
    MOVE = "move"
    LOOK = "look"
    INVENTORY = "inventory"
    REST = "rest"
    HELP = "help"
    UNRECOGNIZED = "unrecognized"


@dataclass
class Action:
    type: ActionType
    target: str | None = None
    raw_text: str = ""
    message: str | None = None  # set on UNRECOGNIZED


VERB_TABLE: dict[str, ActionType] = {
    "go": ActionType.MOVE,
    "move": ActionType.MOVE,
    "walk": ActionType.MOVE,
    "travel": ActionType.MOVE,
    "look": ActionType.LOOK,
    "l": ActionType.LOOK,
    "check": ActionType.LOOK,
    "inventory": ActionType.INVENTORY,
    "inv": ActionType.INVENTORY,
    "i": ActionType.INVENTORY,
    "rest": ActionType.REST,
    "sleep": ActionType.REST,
    "help": ActionType.HELP,
    "?": ActionType.HELP,
}


def parse(text: str) -> Action:
    raw = text.strip()
    if not raw:
        return Action(ActionType.UNRECOGNIZED, raw_text=raw, message="Say something.")

    words = raw.lower().split()
    verb = words[0]
    action_type = VERB_TABLE.get(verb)

    if action_type is None:
        # TODO(later part): LLM translation fallback maps novel prose -> a
        # structured Action here. Menus + this verb table keep that path rare
        # (SPEC.md §6, "most turns cost zero AI calls").
        return Action(
            ActionType.UNRECOGNIZED,
            raw_text=raw,
            message=f"I don't understand {verb!r}. Try: go <direction>, look, inventory, rest, help.",
        )

    target = " ".join(words[1:]) if len(words) > 1 else None
    return Action(action_type, target=target, raw_text=raw)
