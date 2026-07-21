"""The one interface every provider adapter implements. Deliberately a single
method: generation in this project is always "here's a system+user prompt and
a JSON schema, give me back JSON matching it" (SPEC.md §1) -- there's no
streaming, no multi-turn chat, no tool-use loop to model, so the interface
stays this small on purpose rather than wrapping each vendor SDK's full
surface."""
from __future__ import annotations

from abc import ABC, abstractmethod


class LLMClient(ABC):
    @abstractmethod
    def generate_structured(self, system: str, user: str, schema: dict) -> dict:
        """Returns a dict matching `schema` (a JSON-Schema-subset object with
        at least "type"/"properties"/"required").

        Raises `llm.errors.LLMProviderError` on a transport/API failure, or
        `llm.errors.MalformedGenerationError` if the response can't be parsed
        as JSON matching `schema` after one retry. Never returns anything
        that hasn't been validated against `schema`."""
