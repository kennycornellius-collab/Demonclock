"""A deterministic, offline stand-in for a real provider -- what every test
in this project uses, and what real play falls back to when no provider is
configured (see config.py's GenerationConfig.enabled). Also the vehicle for
proving the registry's fallback-chain behavior (one MockClient configured to
always error, a second configured to succeed).

Honors the same one-retry-then-discard contract every real adapter must
(SPEC.md §1): a canned response that doesn't match the requested schema is
"malformed," and generate_structured tries exactly one more queued response
before raising MalformedGenerationError -- the same shape GeminiClient
implements against a real API, just driven by a pre-loaded queue instead of
network calls.
"""
from __future__ import annotations

from ..base import LLMClient
from ..errors import LLMProviderError, MalformedGenerationError
from ..schema import matches_schema


class MockClient(LLMClient):
    def __init__(
        self,
        responses: list[object] | None = None,
        *,
        always_error: Exception | None = None,
        name: str = "mock",
    ) -> None:
        """`responses` is a queue of canned answers consumed one per attempt,
        in order: each entry is either a dict (checked against the caller's
        schema) or an Exception instance (raised as LLMProviderError
        immediately -- a hard failure is never internally retried, only
        malformed output is). `always_error`, if set, makes every single call
        raise unconditionally regardless of `responses` -- the simplest way
        to build the "always-down" half of a fallback-chain test."""
        self.name = name
        self._responses = list(responses) if responses is not None else []
        self._always_error = always_error
        self.call_count = 0

    def generate_structured(self, system: str, user: str, schema: dict) -> dict:
        self.call_count += 1
        if self._always_error is not None:
            raise LLMProviderError(f"{self.name}: {self._always_error}") from self._always_error

        candidate = self._pop()
        if matches_schema(candidate, schema):
            return candidate

        # One retry on malformed output, same contract every real adapter follows.
        retry_candidate = self._pop()
        if matches_schema(retry_candidate, schema):
            return retry_candidate
        raise MalformedGenerationError(
            f"{self.name}: response did not match schema after one retry"
        )

    def _pop(self) -> object:
        if not self._responses:
            raise MalformedGenerationError(f"{self.name}: no more canned responses queued")
        candidate = self._responses.pop(0)
        if isinstance(candidate, Exception):
            raise LLMProviderError(f"{self.name}: {candidate}") from candidate
        return candidate
