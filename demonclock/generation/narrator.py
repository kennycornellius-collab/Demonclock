"""The Narrator agent (SPEC.md §2/§10, Step 7 Chunk A): the first generation
role that touches presentation text rather than world content. Its only
permitted job, per SPEC.md §10, is REWORDING a rumor that `rumors.py` has
already fully computed -- never inventing a fact, and never deciding
anything the engine hasn't already decided (SPEC.md §6's narration rule: "it
cannot change win/lose," generalized here to "it cannot change what
happened"). `rumors.py` itself stays untouched and fully deterministic --
`rumors_reaching` already produces a real, template-worded `Rumor.text` from
`history.LogEntry.description` with zero AI involvement, exactly as it did
before this chunk. This module only offers to reword THAT already-decided
string at the presentation boundary (`game.handle_ask_around`, `newspaper.
format_newspaper`), one call site smaller than the rest of `generation/`,
which produces new content rather than rewording existing text.

Unlike `director.py`/`story.py`/`quest.py`/`places.py`, which let a failure
propagate to `pipeline.py`'s single `_DEGRADE_ON` catch, `reword_rumor` is
called from presentation code with no equivalent batch-level catch above
it -- so it owns its own fallback here: any disabled/unconfigured/failed
call just returns the deterministic text unchanged, and the player never
sees a difference beyond plainer wording. A day with no `GEMINI_API_KEY`
configured reads and plays identically to one with the Narrator role wired
in, same "no key configured, everything still works" posture as every other
generation role.
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
