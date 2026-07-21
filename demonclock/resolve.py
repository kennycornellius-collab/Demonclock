"""Entity resolution (SPEC.md §8, third of Step 4's three chunks): mapping
a text reference (e.g. "the old lord") to an existing entity's ID against
a small, caller-retrieved shortlist — NEVER the whole DB (SPEC.md §8's
"bounded context" invariant, reused here: "the checker loads only the
handful of entities the manifest names — never 500").

Deterministic matching runs first — an exact pass, then a stopword-filtered
TOKEN-SUBSET pass (e.g. "the wilds" -> {wilds}, a subset of "Bramblewood
Wilds" -> {bramblewood, wilds}, so it resolves even though neither string
contains the other character-for-character). A reference still ambiguous
after both passes falls to a small AI call (Step 5 Chunk D) ONLY if a
`registry` was supplied — the exact two-tier "deterministic match first, LLM
fallback only on genuine ambiguity" shape `parser.py` already established
for player input (SPEC.md §6) — most resolutions cost zero AI calls, same as
most turns. Passing no `registry` (the default) keeps this module's pure
zero-AI behavior exactly as it always was.

Identity is always an id, never a name (SPEC.md §8) — `resolve_entity`
returns an id or `None`, and NEVER fabricates a new entity for a reference
it can't confidently place: "if the entity resolver finds no confident
match on the shortlist, the item goes to repair or is rejected... It must
NEVER implicitly create a new entity to satisfy a dangling reference." The
AI fallback enforces this structurally, not just by convention: its response
schema restricts the resolved id to an enum of exactly the shortlist's ids
plus one explicit "no match" sentinel — there is no way for a schema-valid
response to name anything else.

This module has zero knowledge of `World`/`Node`/any concrete entity type
— the shortlist shape (`list[(id, name)]`) is entity-type-agnostic on
purpose, so NPCs (a future part) can reuse this completely unchanged.
Narrowing the shortlist (never handing the whole DB) is the CALLER's job.
"""
from __future__ import annotations

import json

from .llm.errors import LLMProviderError, MalformedGenerationError
from .llm.registry import LLMRegistry, NoProviderConfiguredError

# Small, closed list — same "start small, extend deliberately" posture as
# every other enumerated/fixed vocabulary in this codebase. These carry no
# identifying content on their own, so stripping them before a token-subset
# comparison only removes noise, never a candidate's real distinguishing word.
_STOPWORDS = frozenset({"the", "a", "an", "of", "to", "in", "at", "on"})

# The one value a schema-valid AI response can use to mean "none of these" --
# distinct from any real id, so the enum below can never accidentally permit
# a fabricated entity through.
NO_MATCH = "__no_match__"

_SYSTEM_PROMPT = (
    "You resolve a text reference against a small shortlist of known "
    "entities for a text RPG's canon check. Given the reference and a list "
    "of (id, name) candidates, decide which id the reference means. If you "
    "are not confident it names exactly one candidate, answer with "
    f'"{NO_MATCH}" -- NEVER answer with anything other than one of the '
    "given ids or that exact sentinel."
)


def resolve_entity(
    reference_text: str,
    shortlist: list[tuple[str, str]],
    registry: LLMRegistry | None = None,
) -> str | None:
    """Returns the matched id, or None on no match / genuine ambiguity —
    never guesses, never creates. `shortlist` must already be a small,
    retrieved set of (id, name) candidates. `registry`, if given, is tried
    ONLY after both deterministic passes fail to confidently resolve —
    passing None (the default) keeps this function's classic zero-AI
    behavior unchanged."""
    normalized_ref = _normalize(reference_text)
    if not normalized_ref:
        return None

    exact = [entity_id for entity_id, name in shortlist if _normalize(name) == normalized_ref]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        # Same-name collision — exactly why identity is an id, never a
        # name (SPEC.md §8). Ambiguous, not resolved.
        return None

    ref_tokens = _tokenize(reference_text)
    if ref_tokens:
        fuzzy = []
        for entity_id, name in shortlist:
            name_tokens = _tokenize(name)
            if name_tokens and (ref_tokens <= name_tokens or name_tokens <= ref_tokens):
                fuzzy.append(entity_id)
        if len(fuzzy) == 1:
            return fuzzy[0]

    if registry is None:
        return None
    return _resolve_via_ai(reference_text, shortlist, registry)


def _resolve_via_ai(reference_text: str, shortlist: list[tuple[str, str]], registry: LLMRegistry) -> str | None:
    if not shortlist:
        return None

    shortlist_ids = [entity_id for entity_id, _ in shortlist]
    schema = {
        "type": "object",
        "properties": {"resolved_id": {"type": "string", "enum": [*shortlist_ids, NO_MATCH]}},
        "required": ["resolved_id"],
    }
    payload = {
        "reference_text": reference_text,
        "candidates": [{"id": entity_id, "name": name} for entity_id, name in shortlist],
    }

    try:
        data = registry.generate("entity_resolution", _SYSTEM_PROMPT, json.dumps(payload), schema)
    except (LLMProviderError, MalformedGenerationError, NoProviderConfiguredError):
        # A down provider, malformed output, or no configured role are all
        # the same outcome here: unresolved, never guessed at.
        return None

    resolved = data["resolved_id"]
    return None if resolved == NO_MATCH else resolved


def _normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _tokenize(text: str) -> frozenset[str]:
    return frozenset(word for word in _normalize(text).split() if word not in _STOPWORDS)
