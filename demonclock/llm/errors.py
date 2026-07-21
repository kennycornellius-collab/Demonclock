"""The two LLM failure modes (see llm/__init__.py) -- kept as distinct
exception types, not a single generic one, because the registry (registry.py)
needs to tell them apart to decide whether to fall over to the next provider
in a role's chain."""
from __future__ import annotations


class LLMProviderError(Exception):
    """The provider/transport failed (network error, non-2xx HTTP, auth,
    timeout). Triggers fallback to the next provider in the role's chain."""


class MalformedGenerationError(Exception):
    """The provider responded, but its output isn't valid JSON matching the
    requested schema, even after one retry. Never triggers fallback -- a
    different provider facing the same prompt has no particular reason to
    do better, so this bubbles up to the caller to discard the item (SPEC.md
    §1: "malformed output gets exactly one retry, then the item is
    discarded")."""
