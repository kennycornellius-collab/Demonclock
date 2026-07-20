"""Entity resolution (SPEC.md §8, third of Step 4's three chunks): mapping
a text reference (e.g. "the old lord") to an existing entity's ID against
a small, caller-retrieved shortlist — NEVER the whole DB (SPEC.md §8's
"bounded context" invariant, reused here: "the checker loads only the
handful of entities the manifest names — never 500").

Deterministic matching runs first — an exact pass, then a stopword-filtered
TOKEN-SUBSET pass (e.g. "the wilds" -> {wilds}, a subset of "Bramblewood
Wilds" -> {bramblewood, wilds}, so it resolves even though neither string
contains the other character-for-character). A reference that's still
ambiguous after both passes is a marked TODO for a small AI call, the
exact two-tier "deterministic match first, LLM fallback only on genuine
ambiguity" shape `parser.py` already established for player input (SPEC.md
§6) — most resolutions should cost zero AI calls, same as most turns.

Identity is always an id, never a name (SPEC.md §8) — `resolve_entity`
returns an id or `None`, and NEVER fabricates a new entity for a reference
it can't confidently place: "if the entity resolver finds no confident
match on the shortlist, the item goes to repair or is rejected... It must
NEVER implicitly create a new entity to satisfy a dangling reference."

This module has zero knowledge of `World`/`Node`/any concrete entity type
— the shortlist shape (`list[(id, name)]`) is entity-type-agnostic on
purpose, so NPCs (Step 5) can reuse this completely unchanged. Narrowing
the shortlist (never handing the whole DB) is the CALLER's job.
"""
from __future__ import annotations

# Small, closed list — same "start small, extend deliberately" posture as
# every other enumerated/fixed vocabulary in this codebase. These carry no
# identifying content on their own, so stripping them before a token-subset
# comparison only removes noise, never a candidate's real distinguishing word.
_STOPWORDS = frozenset({"the", "a", "an", "of", "to", "in", "at", "on"})


def resolve_entity(reference_text: str, shortlist: list[tuple[str, str]]) -> str | None:
    """Returns the matched id, or None on no match / genuine ambiguity —
    never guesses, never creates. `shortlist` must already be a small,
    retrieved set of (id, name) candidates."""
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

    # TODO(later part): a small LLM call resolves a genuinely ambiguous or
    # loosely-worded reference against this same shortlist (SPEC.md §8).
    # Until that's wired, anything this deterministic pass can't
    # confidently place is simply unresolved — never guessed at, never
    # used to fabricate a new entity.
    ref_tokens = _tokenize(reference_text)
    if not ref_tokens:
        return None

    fuzzy = []
    for entity_id, name in shortlist:
        name_tokens = _tokenize(name)
        if name_tokens and (ref_tokens <= name_tokens or name_tokens <= ref_tokens):
            fuzzy.append(entity_id)
    if len(fuzzy) == 1:
        return fuzzy[0]
    return None


def _normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _tokenize(text: str) -> frozenset[str]:
    return frozenset(word for word in _normalize(text).split() if word not in _STOPWORDS)
