"""The free-text LLM parser fallback (parser.py's original
AI-free scope, reopened per "arguably the most important
item on this whole list") -- Chunk B of 3. Live, per-turn, NOT batch/pooled -- same family
as narrator.py/dialogue.py, not director/story/quest/places/flavor/npc.
Free text is already the rare "Something else..." escape hatch (the
"most turns cost zero AI calls" invariant is unaffected by this
existing), and this fallback specifically only ever runs once parser.py's
own deterministic VERB_TABLE has already failed to match -- an even rarer
path within an already-rare one.

This module has ZERO knowledge of World/Player/game state -- same
"entity-type-agnostic, caller narrows the context" discipline resolve.py's
own resolve_entity already established. The CALLER (game.py, Chunk C)
decides which ActionTypes are actually available right now (e.g. no FIGHT
option unless the current node has a wild enemy) and passes that list in;
this module's only job is picking WHICH of those available actions the raw
free text most likely means, plus extracting a raw `target` PHRASE for a
SEPARATE resolver (resolve.py's resolve_entity) to resolve into an actual
entity id/direction afterward -- this module never resolves WHO/WHERE
itself, only WHICH action, same division of labor Director/Story/Quest
already have from Places/NPC.

Schema-constrained the same way resolve.py's own AI fallback is:
the `action` enum is built FRESH each call from exactly the
caller-supplied `available_actions` list plus parser.ActionType.
UNRECOGNIZED's own value as the "none of these" sentinel -- a schema-valid
response structurally cannot name an action that isn't actually available
right now, the same "cannot fabricate" guarantee resolve_entity's own
shortlist-derived enum provides for entity ids.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from ..llm.errors import LLMProviderError, MalformedGenerationError
from ..llm.registry import LLMRegistry, NoProviderConfiguredError
from ..parser import ActionType

_DEGRADE_ON = (LLMProviderError, MalformedGenerationError, NoProviderConfiguredError)

SYSTEM_PROMPT = (
    "You are the fallback parser for a text RPG's free-text input box. The "
    "player's exact sentence is given, along with a list of the ONLY "
    "actions actually available to them right now (their own deterministic "
    "verb table already failed to match this sentence). Decide which ONE "
    "of those available actions the sentence most likely means. If you are "
    "not confident it matches exactly one of the given actions, answer "
    f'with "{ActionType.UNRECOGNIZED.value}" -- NEVER invent or choose an '
    "action outside the given list, even if the sentence describes "
    "something plausible-sounding the game just doesn't support right now. "
    "If the sentence names a specific person, place, direction, or thing "
    "the action should apply to (who to talk to, which direction/place to "
    "go), extract that exact phrase as `target`. Do NOT try to resolve it "
    "to an exact id or canonical name yourself -- just extract the raw "
    "phrase as the player wrote it; a separate step resolves it afterward."
)


@dataclass
class ParsedAction:
    action: ActionType
    target: str | None = None


def run_free_text_fallback(
    registry: LLMRegistry | None,
    raw_text: str,
    available_actions: list[ActionType],
) -> ParsedAction | None:
    """Returns None whenever `registry` is None/disabled, `available_actions`
    is empty, the call fails for any reason, or the model itself answers
    UNRECOGNIZED -- callers should fall back to parser.py's own honest "I
    don't understand" message in every None case, exactly as if this
    fallback had never been attempted."""
    if registry is None or not registry.enabled or not available_actions:
        return None

    action_values = [action.value for action in available_actions]
    schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": [*action_values, ActionType.UNRECOGNIZED.value]},
            "target": {"type": "string"},
        },
        "required": ["action"],
    }
    payload = {"text": raw_text, "available_actions": action_values}

    try:
        data = registry.generate("parser", SYSTEM_PROMPT, json.dumps(payload), schema)
    except _DEGRADE_ON:
        return None

    action_value = data.get("action")
    if action_value is None or action_value == ActionType.UNRECOGNIZED.value:
        return None
    try:
        action = ActionType(action_value)
    except ValueError:
        # Structurally shouldn't happen given the enum-constrained schema,
        # but never trust a parsed value blindly (same posture as every
        # other AI-output consumer in this codebase).
        return None

    target = data.get("target")
    target = target.strip() if isinstance(target, str) and target.strip() else None
    return ParsedAction(action=action, target=target)
