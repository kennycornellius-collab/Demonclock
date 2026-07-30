"""A startup API-connectivity self-test (updates.md, surfaced 2026-07-28
directly from the Gemini DEFAULT_MODEL 404 bug -- see update_progress.md's
2026-07-28 entry -- where every generation call was silently failing with
zero indication anything was even configured). Runs once at startup
(game.run), never blocks or fails startup either way -- the game must run
fully with AI unconfigured OR unreachable; this is purely a "tell the
player which mode they're in" UX addition, never a new hard dependency on
AI being reachable.

One cheap ping call against whichever role happens to be configured first
(SPEC.md §1's per-role routing means different roles COULD point at
different providers, but GenerationConfig.from_env()'s own default routes
every role to the same chain, so any one role is representative of the
whole configured setup in the common case) -- exercises the exact same
client-construction/request path a real generation call would use (real
auth header, real endpoint), so a genuine connectivity/auth problem
surfaces here instead of silently degrading every later batch.
"""
from __future__ import annotations

import json

from .config import ROLES, GenerationConfig
from .errors import LLMProviderError, MalformedGenerationError
from .registry import LLMRegistry, NoProviderConfiguredError

_DEGRADE_ON = (LLMProviderError, MalformedGenerationError, NoProviderConfiguredError)

_PING_SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
_PING_SYSTEM_PROMPT = 'Respond with exactly one JSON object: {"ok": true}. Nothing else.'


def check_connectivity(registry: LLMRegistry, config: GenerationConfig) -> bool:
    """True if at least one configured role's provider chain answered a
    trivial ping successfully; False on any failure (including a hard
    provider/transport error, malformed output, or nothing configured at
    all for the role checked). Never raises -- every generation-role
    failure mode this codebase already recognizes is caught and degrades
    to False, same posture as every other generation call site."""
    role = next((r for r in ROLES if config.roles.get(r)), None)
    if role is None:
        return False
    try:
        registry.generate(role, _PING_SYSTEM_PROMPT, json.dumps({}), _PING_SCHEMA)
        return True
    except _DEGRADE_ON:
        return False
