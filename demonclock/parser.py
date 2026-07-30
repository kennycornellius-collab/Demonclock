"""Deterministic verb parser (SPEC.md §6). Only runs inside the free-text box —
menus handle the common case without ever reaching this module.

Novel phrasing that doesn't match a verb returns UNRECOGNIZED. The free-text
LLM parser fallback (SPEC.md §12 step 1's original AI-free scope, reopened
per updates.md) maps novel phrasing AND entirely novel action words to one
of these same ActionTypes -- this module itself stays 100% deterministic and
AI-free; the fallback is a separate later layer (game.handle_free_text) that
only ever runs once this module's own VERB_TABLE match has already failed.

Chunk A of that build (this module's own changes): extends ActionType/
VERB_TABLE to cover the actions that, before this, were ONLY reachable via
game.py's menus (Fight/Trade/Talk/Craft/Skills/Atlas/Quests/Ask around) --
recognized deterministically here for the subset of players who already
know the right word, but not yet WIRED into actions.resolve()/game.py
(that's Chunk C) -- same "prove the plumbing before it's wired up" posture
canon.py's/llm/'s own Chunk A took. Verb choices here are deliberately
conservative (a handful of unambiguous action-nouns/verbs, not every
plausible synonym) after this project's own hard-won lesson from the "i"/
Inventory collision bug: a common word that could plausibly start an
ordinary first-person sentence has no business being a bare deterministic
verb in a box whose whole point is accepting ordinary sentences. Looser
synonyms are exactly what the LLM fallback (which sees the WHOLE sentence,
not just the first word) is for.
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
    # Step 12 (free-text LLM parser fallback) Chunk A: previously reachable
    # only through game.py's menus (Interact's contextual sub-options, or a
    # dedicated top-level menu item). Recognized here deterministically for
    # players who already know the word; game.py's Chunk C wiring is what
    # actually dispatches them to the existing interactive handlers.
    FIGHT = "fight"
    TRADE = "trade"
    TALK = "talk"
    CRAFT = "craft"
    SKILLS = "skills"
    ATLAS = "atlas"
    QUESTS = "quests"
    ASK_AROUND = "ask_around"
    # Player-facing journal/recap (updates.md, surfaced 2026-07-29) — same
    # "menu-only until free text catches up" precedent as every other
    # Chunk A verb above.
    JOURNAL = "journal"
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
    # Deliberately NOT "i" -- this parser only ever sees the free-text box
    # (SPEC.md §6), where the single most common opening word of an
    # ordinary first-person sentence ("I attack the wolf", "I open the
    # door") is the pronoun "I". A bare single-letter shorthand for
    # Inventory silently swallowed every such sentence as an inventory
    # check, discarding the rest of the text -- confirmed via real play.
    # "inv"/"inventory" stay as the deterministic aliases.
    "rest": ActionType.REST,
    "sleep": ActionType.REST,
    "help": ActionType.HELP,
    "?": ActionType.HELP,
    # Step 12 Chunk A. Deliberately conservative -- see the module docstring
    # for why: only words that are inherently imperative/deliberate as a
    # sentence's very first word, never a common word that could plausibly
    # open an ordinary first-person sentence ("attack"/"fight" pass this
    # bar the same way "i" and "look"/"check" famously didn't).
    "fight": ActionType.FIGHT,
    "attack": ActionType.FIGHT,
    "trade": ActionType.TRADE,
    "buy": ActionType.TRADE,
    "sell": ActionType.TRADE,
    "talk": ActionType.TALK,
    "speak": ActionType.TALK,
    "craft": ActionType.CRAFT,
    "skills": ActionType.SKILLS,
    "atlas": ActionType.ATLAS,
    "map": ActionType.ATLAS,
    "quests": ActionType.QUESTS,
    "quest": ActionType.QUESTS,
    "rumors": ActionType.ASK_AROUND,
    "gossip": ActionType.ASK_AROUND,
    "journal": ActionType.JOURNAL,
    "recap": ActionType.JOURNAL,
}

# "look"/"l"/"check" (updates.md's "Open bugs": a smaller version of the
# "i"/Inventory collision) -- actions._resolve_look never reads a target at
# all, so unlike "go"/"talk" (which genuinely need trailing words), any text
# after one of these is either nothing (bare "look") or an ordinary
# sentence's discourse continuation ("Look, I really don't want to
# fight..."), never a real argument that would be lost by NOT matching.
# Unlike "i", there's no redundant full-word alias to simply drop (the
# module docstring's own reasoning for why they stayed as bare verbs despite
# not fully "passing the bar" other Chunk A verbs did) -- so instead, these
# three only match deterministically when they're the WHOLE input; any
# trailing word makes `parse` fall through to UNRECOGNIZED (and so to the
# free-text LLM fallback, if configured) exactly like any other novel
# phrasing, rather than the first word silently winning and the rest being
# discarded.
_EXACT_MATCH_ONLY = {"look", "l", "check"}


def parse(text: str) -> Action:
    raw = text.strip()
    if not raw:
        return Action(ActionType.UNRECOGNIZED, raw_text=raw, message="Say something.")

    words = raw.lower().split()
    verb = words[0]
    action_type = VERB_TABLE.get(verb)
    if verb in _EXACT_MATCH_ONLY and len(words) > 1:
        action_type = None

    if action_type is None:
        # Step 12 Chunk C (game.handle_free_text): tries the LLM parser
        # fallback next, only on this exact UNRECOGNIZED result -- this
        # module itself never calls out to an LLM, keeping it exactly as
        # deterministic/AI-free as it always was (SPEC.md §6, "most turns
        # cost zero AI calls"). Whether that later fallback resolves the
        # sentence or not, THIS message is only what's shown if it's not
        # even attempted (e.g. no registry configured).
        return Action(
            ActionType.UNRECOGNIZED,
            raw_text=raw,
            message=(
                f"I don't understand {verb!r}. Try: go <direction>, look, inventory, rest, "
                "fight, trade, talk, craft, skills, atlas, quests, rumors, journal, help."
            ),
        )

    target = " ".join(words[1:]) if len(words) > 1 else None
    return Action(action_type, target=target, raw_text=raw)
