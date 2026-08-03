"""Per-role provider routing (the generation pipeline's agent roles) -- Step 5 Chunk A.

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

**API keys are never hardcoded or committed.** `from_env()` reads them from
the real process environment first; a `.env` file (git-ignored, stdlib-only
parsing, no `python-dotenv` dependency) is an optional convenience fallback
for keys the real environment doesn't already have set -- so a real
`GEMINI_API_KEY` env var always wins over whatever a `.env` file says.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

# Every generation role in the pipeline, plus the entity-resolution
# AI fallback resolve.py wires in at Chunk D, plus the Narrator
# (rumor wording + combat-outcome summaries, Step 7 Chunks
# A/B) that touches presentation text rather than world content, plus
# "flavor" (Step 7 Chunk C) -- a batch-time content-generation role like
# director/story/quest/places, just for ambient per-node atmosphere rather
# than manifest-carrying content. Step 10 Stage 3 added "npc" -- a
# batch-time content-generation role like places, triggered by a quest's
# needs_new_npc flag -- and "dialogue", a live (never batch/pooled)
# per-conversation role, same non-batch precedent as "narrator". The
# free-text parser fallback (generation/free_text.py) added "parser" --
# another live, non-batch role, same family as "narrator"/"dialogue": only
# ever called once parser.py's own deterministic VERB_TABLE has already
# failed to match, an even rarer path within the already-rare free-text box.
ROLES = (
    "director", "story", "quest", "places", "entity_resolution", "narrator", "flavor",
    "npc", "dialogue", "parser",
)

# Extend alongside registry.PROVIDER_CLASSES when a new provider ships.
PROVIDER_API_KEY_ENV = {"gemini": "GEMINI_API_KEY"}

CONFIG_FILE_ENV_VAR = "DEMONCLOCK_LLM_CONFIG"
DEFAULT_DOTENV_PATH = ".env"

# 2026-07-29: the plain single-entry `gemini.DEFAULT_MODEL` chain was hitting
# real rate limits during play -- "gemini-flash-latest"'s free tier is only
# 5 RPM / 20 RPD, and a single elapsed-time batch (Director + 2x Story +
# 2x Quest + optional Places/NPC + Flavor) can fire up to ~8 calls back to
# back. Live-tested (real API calls against the user's own key, not just
# docs) alternatives that also correctly honor systemInstruction +
# responseMimeType/responseSchema: "gemini-3.5-flash-lite" and
# "gemini-3.1-flash-lite" (15 RPM / 500 RPD / 250K TPM each), and
# "gemma-4-26b-a4b-it" (30 RPM / 14.4K RPD but a much tighter 16K TPM, plus
# hidden "thinking" tokens that eat into it) as a last-resort third tier.
# This is every role's DEFAULT chain -- still fully overridable per role via
# DEMONCLOCK_LLM_CONFIG with no code change.
DEFAULT_GEMINI_MODEL_CHAIN = (
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemma-4-26b-a4b-it",
)


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
    def from_env(dotenv_path: str | None = DEFAULT_DOTENV_PATH) -> GenerationConfig:
        """The default: every role routed to Gemini alone, if (and only if)
        a key is available. Looked up per provider as: real process
        environment variable first, then (only if unset) the matching key in
        a `.env` file at `dotenv_path` -- so a real env var always wins and a
        missing/absent `.env` file is simply skipped, never an error. Pass
        `dotenv_path=None` to skip `.env` lookup entirely (e.g. in tests that
        need to be independent of whatever `.env` a working directory
        happens to have).

        A DEMONCLOCK_LLM_CONFIG JSON file, if set, overrides the per-role
        provider chains (e.g. to route "story" to a different provider/model
        once one exists) without any code change; format is
        `{"director": [{"provider": "gemini", "model": "..."}], ...}`."""
        dotenv_values = _load_dotenv(dotenv_path) if dotenv_path else {}
        api_keys = {
            provider: os.environ.get(env_var) or dotenv_values.get(env_var)
            for provider, env_var in PROVIDER_API_KEY_ENV.items()
            if os.environ.get(env_var) or dotenv_values.get(env_var)
        }

        config_path = os.environ.get(CONFIG_FILE_ENV_VAR)
        if config_path:
            roles = _load_roles_from_file(config_path)
        elif "gemini" in api_keys:
            roles = {
                role: [
                    ProviderSpec(provider="gemini", model=model)
                    for model in DEFAULT_GEMINI_MODEL_CHAIN
                ]
                for role in ROLES
            }
        else:
            roles = {}

        return GenerationConfig(roles=roles, api_keys=api_keys)


def _load_dotenv(path: str) -> dict[str, str]:
    """A minimal, stdlib-only `.env` parser (no `python-dotenv` dependency --
    the project stays zero third-party dependencies). Supports `KEY=VALUE`
    lines, blank lines, `#` comments, and optionally-quoted values. Returns
    `{}` (never raises) if the file doesn't exist -- a missing `.env` is a
    perfectly normal, unconfigured state, same as a missing env var."""
    if not os.path.isfile(path):
        return {}

    values: dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                values[key] = value
    return values


def _load_roles_from_file(path: str) -> dict[str, list[ProviderSpec]]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {
        role: [ProviderSpec.from_dict(entry) for entry in chain]
        for role, chain in raw.items()
        if role in ROLES
    }
