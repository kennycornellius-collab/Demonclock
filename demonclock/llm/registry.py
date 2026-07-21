"""Builds concrete `LLMClient`s from a `GenerationConfig` and exposes the one
thing every generation-pipeline caller needs: `generate(role, ...)`, which
walks that role's provider chain -- the "static default + fallback chain,
both" decision from config.py, implemented here.

A hard `LLMProviderError` from one provider moves on to the next entry in the
chain; a `MalformedGenerationError` does NOT (see llm/__init__.py's docstring
for why) -- it propagates straight out of `generate()` so the caller can
discard the item, same as SPEC.md §1's "one retry, then discard" already does
inside a single adapter.
"""
from __future__ import annotations

from .base import LLMClient
from .config import GenerationConfig, ProviderSpec
from .errors import LLMProviderError
from .providers.gemini import GeminiClient
from .providers.mock import MockClient

# Extend alongside config.PROVIDER_API_KEY_ENV when a new provider ships.
PROVIDER_CLASSES: dict[str, type[LLMClient]] = {
    "gemini": GeminiClient,
    "mock": MockClient,
}


class NoProviderConfiguredError(Exception):
    """Raised by generate() when the role has no provider chain at all --
    kept distinct from every provider in the chain failing, so a caller can
    tell "nothing was configured for this role" apart from "everything
    configured failed"."""


class LLMRegistry:
    def __init__(
        self,
        config: GenerationConfig,
        *,
        extra_clients: dict[str, LLMClient] | None = None,
    ) -> None:
        """`extra_clients` maps a provider name directly to an already-built
        `LLMClient` -- how tests hand in specific `MockClient` instances
        (e.g. one that always errors, one with a canned response) keyed by
        whatever provider name a test's `ProviderSpec` chain uses. Looked up
        before anything is built from `config`, and takes priority over it.

        Real (config-driven) clients are cached per (provider, model) pair,
        built lazily on first use -- a known simplification is that two
        different roles both routed to the same real provider with the same
        model share one client instance, which is fine for a stateless
        request/response adapter."""
        self._config = config
        self._explicit_clients = dict(extra_clients or {})
        self._built_clients: dict[tuple[str, str | None], LLMClient] = {}

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def generate(self, role: str, system: str, user: str, schema: dict) -> dict:
        chain = self._config.roles.get(role, [])
        if not chain:
            raise NoProviderConfiguredError(f"no provider configured for role {role!r}")

        last_error: LLMProviderError | None = None
        for spec in chain:
            client = self._client_for(spec)
            try:
                return client.generate_structured(system, user, schema)
            except LLMProviderError as exc:
                last_error = exc
                continue
        raise last_error  # every provider in the chain raised LLMProviderError

    def _client_for(self, spec: ProviderSpec) -> LLMClient:
        if spec.provider in self._explicit_clients:
            return self._explicit_clients[spec.provider]

        cache_key = (spec.provider, spec.model)
        if cache_key not in self._built_clients:
            self._built_clients[cache_key] = self._build_client(spec)
        return self._built_clients[cache_key]

    def _build_client(self, spec: ProviderSpec) -> LLMClient:
        provider_class = PROVIDER_CLASSES.get(spec.provider)
        if provider_class is None:
            raise ValueError(
                f"unknown provider {spec.provider!r} -- not in PROVIDER_CLASSES "
                "and not supplied via extra_clients"
            )
        if spec.provider == "mock":
            # MockClient takes no config-driven constructor args (no api_key)
            # -- real test usage should supply a pre-built instance via
            # extra_clients instead; this bare fallback just avoids a crash
            # if "mock" ever appears in a config file.
            return provider_class()
        api_key = self._config.api_keys.get(spec.provider, "")
        kwargs = {"model": spec.model} if spec.model else {}
        return provider_class(api_key=api_key, **kwargs)
