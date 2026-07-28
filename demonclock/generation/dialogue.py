"""The Dialogue role (SPEC.md §6/§7, Step 10 Stage 3): live, per-conversation
NPC dialogue -- deliberately NOT batch-generated/pooled like Story/Quest/
Places/Flavor. Talking to an NPC is a rare, deliberate player action, same
bucket as narrator.narrate_combat_outcome's "an entire fight is already
rare relative to Move/Look" reasoning (SPEC.md §13's "most turns cost zero
AI calls" invariant is unaffected). Pre-generating dialogue for every NPC in
a batch's bounded context would also (a) waste calls on NPCs never spoken
to and (b) go stale between generation and the moment a conversation
actually happens -- neither problem this module has, since it only ever
runs at the moment the player initiates Talk.

Two entry points, mirroring the "deterministic menu, free-text escape
hatch" hybrid input model SPEC.md §6 already established for the player's
own actions, applied here to one NPC conversation:
  - `run_dialogue_opening`: ONE call producing a greeting plus a small set
    of suggested topics, each with its own pre-written in-character
    response already attached -- picking one costs no further AI call.
  - `run_dialogue_reply`: a SEPARATE call, made only if the player instead
    types free text -- an in-character reply to whatever they said.

v1 scope (a deliberate call, not an oversight -- see CLAUDE.md's Stage 3
bullet): EVERY dialogue path here is pure flavor. Neither a generated
option nor a free-text reply can grant a quest, change gold/items, or
shift faction standing -- there's no NPC-to-quest/faction linkage designed
yet for it to hook into, and letting either path mutate state now would
pull Stage 1/2/4's mechanics into what's supposed to be this stage's
foundation. Like narrator.py, both functions own their own try/except and
never raise -- a failure (or no `dialogue` role configured) just means
game.py falls back to a short generic line, same "unconfigured plays
identically to before this existed" posture as every other role here.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from ..llm.errors import LLMProviderError, MalformedGenerationError
from ..llm.registry import LLMRegistry, NoProviderConfiguredError
from ..models import NPC

_DEGRADE_ON = (LLMProviderError, MalformedGenerationError, NoProviderConfiguredError)

OPENING_SYSTEM_PROMPT = (
    "You are voicing an NPC in a text RPG for one short conversation. Given "
    "the NPC's name, description, and tags, and optionally the player's "
    "derived_role_hint, write a short in-character greeting and 2-3 topics "
    "the player could ask about, each with the NPC's own in-character "
    "response already written out. This is flavor ONLY -- never invent a "
    "quest, item, gold amount, or promise that implies the game engine will "
    "actually grant something; you are coloring the world, not changing it."
)

OPENING_SCHEMA = {
    "type": "object",
    "properties": {
        "greeting": {"type": "string"},
        "options": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "response": {"type": "string"},
                },
                "required": ["label", "response"],
            },
        },
    },
    "required": ["greeting", "options"],
}

REPLY_SYSTEM_PROMPT = (
    "You are voicing an NPC in a text RPG. The player has said something to "
    "you in free text during a conversation. Reply briefly (1-3 sentences), "
    "in character, given the NPC's name/description/tags. This is flavor "
    "ONLY -- never invent a quest, item, gold amount, or promise that "
    "implies the game engine will actually grant something."
)

REPLY_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
}


@dataclass
class DialogueOption:
    label: str
    response: str


@dataclass
class DialogueOpening:
    greeting: str
    options: list[DialogueOption]


def _npc_payload(npc: NPC, derived_role_hint: str | None) -> dict:
    payload = {"npc": {"name": npc.name, "description": npc.description, "tags": npc.tags}}
    if derived_role_hint:
        payload["player_role_hint"] = derived_role_hint
    return payload


def run_dialogue_opening(
    registry: LLMRegistry | None, npc: NPC, derived_role_hint: str | None = None,
) -> DialogueOpening | None:
    """Returns None whenever `registry` is None, disabled, has no
    `dialogue` chain configured, the call fails for any reason, or the
    reply's own `options` list comes back empty -- callers should fall back
    to a short generic line in every None case."""
    if registry is None or not registry.enabled:
        return None

    payload = _npc_payload(npc, derived_role_hint)
    try:
        data = registry.generate("dialogue", OPENING_SYSTEM_PROMPT, json.dumps(payload), OPENING_SCHEMA)
    except _DEGRADE_ON:
        return None

    options = [DialogueOption(label=o["label"], response=o["response"]) for o in data.get("options", [])]
    if not options:
        return None
    return DialogueOpening(greeting=data.get("greeting", ""), options=options)


def run_dialogue_reply(
    registry: LLMRegistry | None, npc: NPC, message: str, derived_role_hint: str | None = None,
) -> str | None:
    """Returns None whenever unconfigured, the call fails, or the reply is
    blank -- never a placeholder string."""
    if registry is None or not registry.enabled:
        return None

    payload = _npc_payload(npc, derived_role_hint)
    payload["player_message"] = message
    try:
        data = registry.generate("dialogue", REPLY_SYSTEM_PROMPT, json.dumps(payload), REPLY_SCHEMA)
    except _DEGRADE_ON:
        return None

    text = data.get("text")
    return text if isinstance(text, str) and text.strip() else None
