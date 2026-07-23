"""The Narrator agent (SPEC.md §2/§10, Step 7): the generation role that
touches presentation text rather than world content. It never decides
anything the engine hasn't already decided (SPEC.md §6's narration rule: "it
cannot change win/lose," generalized here to "it cannot change what
happened") -- every function below only dresses up a fact/log/result some
other module already fully computed.

Chunk A -- `reword_rumor`: rewords a rumor `rumors.py` has already fully
computed, per SPEC.md §10's "the AI's only role is wording a rumor, never
inventing one." `rumors.py` itself stays untouched and fully deterministic.
Wired into `game.handle_ask_around` and `newspaper.format_newspaper`.

Chunk B -- `narrate_combat_outcome`: summarizes one ALREADY-FINISHED fight's
deterministic turn-by-turn log (`combat.run_combat`/`boss.run_encounter`'s
own `log` return value) into a short prose recap. Called exactly ONCE per
whole fight, never per turn -- SPEC.md §13's "most turns cost zero AI calls"
invariant is about the daytime loop's per-action cost, and an entire combat
encounter is already a rare action relative to Move/Look, so one call per
fight stays well inside it. Wired into `game.handle_interact`'s wild-foe
branch and `game._handle_demon_king`.

Every function here is called from presentation code (`game.py`,
`newspaper.py`) with no `pipeline.py`-style batch-level catch above it, so
each one owns its own fallback and never raises: `reword_rumor` returns the
original text unchanged on any failure, and `narrate_combat_outcome` returns
`None` (the deterministic `log` it received is already a complete, playable
narration on its own -- nothing needs replacing, only optionally
supplementing). A day with no `GEMINI_API_KEY` configured plays identically
to one with the Narrator role wired in, same "no key configured, everything
still works" posture as every other generation role.
"""
from __future__ import annotations

import json

from ..llm.errors import LLMProviderError, MalformedGenerationError
from ..llm.registry import LLMRegistry, NoProviderConfiguredError

_DEGRADE_ON = (LLMProviderError, MalformedGenerationError, NoProviderConfiguredError)

REWORD_RUMOR_SYSTEM_PROMPT = (
    "You are the Narrator for a text RPG. You will be given a rumor's "
    "already-decided text and how confident the listener should sound "
    "repeating it. Reword it in a more vivid, in-world voice -- vary the "
    "phrasing, add atmosphere -- but you MUST NOT add, remove, or change any "
    "fact, name, place, or number it contains. If you cannot reword it "
    "without risking a factual change, return it unchanged."
)

REWORD_RUMOR_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
}


def reword_rumor(registry: LLMRegistry | None, text: str, confidence: float) -> str:
    """Rewords `text` (rumors.py's own deterministic template output) via the
    `narrator` role. Returns `text` unchanged whenever `registry` is None,
    disabled, has no `narrator` chain configured, or the call fails for any
    reason -- this function never raises. `confidence` is passed as flavor
    context only (lets the Narrator lean more hedging at low confidence);
    the engine never trusts anything the reply says back about it."""
    if registry is None or not registry.enabled:
        return text

    payload = {"rumor_text": text, "confidence": confidence}
    try:
        data = registry.generate(
            "narrator", REWORD_RUMOR_SYSTEM_PROMPT, json.dumps(payload), REWORD_RUMOR_SCHEMA,
        )
    except _DEGRADE_ON:
        return text

    reworded = data.get("text")
    return reworded if isinstance(reworded, str) and reworded.strip() else text


NARRATE_COMBAT_SYSTEM_PROMPT = (
    "You are the Narrator for a text RPG. You will be given the turn-by-turn "
    "log of a combat encounter that has ALREADY been fully resolved by the "
    "game engine, plus its final result (victory, defeat, or fled). Write a "
    "short (2-4 sentence), vivid summary of how the fight unfolded and "
    "concluded. You MUST NOT change the outcome, invent characters or events "
    "not implied by the log, or alter any number in it -- you are only "
    "dramatizing what already happened."
)

NARRATE_COMBAT_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
}


def narrate_combat_outcome(
    registry: LLMRegistry | None, opponent_name: str, result: str, log: list[str],
) -> str | None:
    """Narrates the ALREADY-DECIDED outcome of one whole fight. `result` is
    the plain string value ("victory"/"defeat"/"fled") rather than either of
    combat.py's/boss.py's own result enums -- keeps this module ignorant of
    combat internals, same as `reword_rumor` never importing `rumors.Rumor`.
    Returns `None` (never a placeholder string) whenever unconfigured or the
    call fails, so callers should only print something when this returns
    non-None."""
    if registry is None or not registry.enabled:
        return None

    payload = {"opponent": opponent_name, "result": result, "combat_log": log}
    try:
        data = registry.generate(
            "narrator", NARRATE_COMBAT_SYSTEM_PROMPT, json.dumps(payload), NARRATE_COMBAT_SCHEMA,
        )
    except _DEGRADE_ON:
        return None

    text = data.get("text")
    return text if isinstance(text, str) and text.strip() else None
