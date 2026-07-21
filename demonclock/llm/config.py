"""Per-role provider routing (SPEC.md §7's agent roles) -- Step 5 Chunk A.

Two decisions locked with the user, encoded here:
  - **"Both" routing**: `GenerationConfig.roles` maps each role to an ORDERED
    list of `ProviderSpec` -- the first entry is that role's static default
    provider, the rest are an optional fallback chain tried in order only on
    a hard `LLMProviderError` (see registry.py). A role with an empty/missing
    chain has generation disabled for that role specifically.
  - **Gemini is the only real provider shipped this chunk.** Adding a second
    (Anthropic/OpenAI) later means: one adapter file in `llm/providers/`, one
    entry in `registry.PROVIDER_CLASSES`, and one entry in
    `PROVIDER_API_KEY_ENV` below -- nothing else in this module changes.

`GenerationConfig.enabled` is False whenever no role has any configured
provider (e.g. `GEMINI_API_KEY` isn't set) -- this is what lets
`sim._run_batch` degrade to today's exact no-op behavior in an unconfigured
environment, rather than every caller needing its own "is there a key" check.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

# Every generation role in SPEC.md §7's pipeline, plus the entity-resolution
# AI fallback (SPEC.md §8) resolve.py wires in at Chunk D. Rumor wording
# (SPEC.md §10) belongs to a later step, not this pipeline.
ROLES = ("director", "story", "quest", "places", "entity_resolution")

# Extend alongside registry.PROVIDER_CLASSES when a new provider ships.
PROVIDER_API_KEY_ENV = {"gemini": "GEMINI_API_KEY"}

CONFIG_FILE_ENV_VAR = "DEMONCLOCK_LLM_CONFIG"


@dataclass(frozen=True)
class ProviderSpec:
    provider: str  # must match a registry.PROVIDER_CLASSES key (or a test's extra_clients key)
    model: str | None = None  # None = that provider adapter's own default

    @staticmethod
    def from_dict(data: dict) -> ProviderSpec:
        return ProviderSpec(provider=data["provider"], model=data.get("model"))


@dataclass
class GenerationConfig:
    roles: dict[str, list[ProviderSpec]] = field(default_factory=dict)
    api_keys: dict[str, str] = field(default_factory=dict)  # provider name -> key

    @property
    def enabled(self) -> bool:
        return any(self.roles.get(role) for role in ROLES)

    @staticmethod
    def from_env() -> GenerationConfig:
        """The default: every role routed to Gemini alone, if (and only if)
        GEMINI_API_KEY is set -- an unconfigured environment gets an empty,
        disabled config, identical to today's no-provider behavior. A
        DEMONCLOCK_LLM_CONFIG JSON file, if set, overrides the per-role
        provider chains (e.g. to route "story" to a different provider/model
        once one exists) without any code change; format is
        `{"director": [{"provider": "gemini", "model": "..."}], ...}`."""
        api_keys = {
            provider: os.environ[env_var]
            for provider, env_var in PROVIDER_API_KEY_ENV.items()
            if os.environ.get(env_var)
        }

        config_path = os.environ.get(CONFIG_FILE_ENV_VAR)
        if config_path:
            roles = _load_roles_from_file(config_path)
        elif "gemini" in api_keys:
            roles = {role: [ProviderSpec(provider="gemini")] for role in ROLES}
        else:
            roles = {}

        return GenerationConfig(roles=roles, api_keys=api_keys)


def _load_roles_from_file(path: str) -> dict[str, list[ProviderSpec]]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {
        role: [ProviderSpec.from_dict(entry) for entry in chain]
        for role, chain in raw.items()
        if role in ROLES
    }
