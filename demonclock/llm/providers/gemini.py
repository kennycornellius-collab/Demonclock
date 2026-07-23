"""The first real provider adapter (Step 5 Chunk A) -- chosen over Anthropic/
OpenAI because the user has a Gemini key on hand and wants the easiest path
to a live batch first. Talks to Gemini's REST `generateContent` endpoint via
stdlib `urllib` only (no `google-genai`/`anthropic`/`openai` SDK dependency --
the project is deliberately zero third-party dependencies).

Structured output is requested via `generationConfig.responseMimeType =
"application/json"` + `responseSchema = <schema>` (Gemini's OpenAPI-3.0-subset
schema format, which the flat object/string/integer/array shapes this project
uses already matches) -- never "please reply in JSON" prose prompting
(SPEC.md §1).

Adding a second real provider later (Anthropic/OpenAI) means a new file here
implementing `LLMClient` the same way, plus one line in
`llm/registry.py`'s `PROVIDER_CLASSES` -- nothing else changes.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from ..base import LLMClient
from ..errors import LLMProviderError, MalformedGenerationError
from ..schema import matches_schema

# Placeholder default, same "start rough, calibrate by feel" status as every
# other tuning constant in this codebase (combat.py's DOT_DURATION, skills.py's
# fair-cost constants, ...) -- swap freely via GenerationConfig, no code change
# needed.
DEFAULT_MODEL = "gemini-2.5-flash-lite"
API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
REQUEST_TIMEOUT_SECONDS = 30


class GeminiClient(LLMClient):
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        if not api_key:
            raise ValueError("GeminiClient requires a non-empty api_key")
        self.api_key = api_key
        self.model = model

    def generate_structured(self, system: str, user: str, schema: dict) -> dict:
        candidate = self._request(system, user, schema)
        if matches_schema(candidate, schema):
            return candidate

        # One retry on malformed output (SPEC.md §1) -- a genuine API/network
        # failure raises LLMProviderError immediately from _request and is
        # NOT retried here; that's the registry's job (try the next provider).
        candidate = self._request(system, user, schema)
        if matches_schema(candidate, schema):
            return candidate
        raise MalformedGenerationError(
            "gemini: response did not match the requested schema after one retry"
        )

    def _request(self, system: str, user: str, schema: dict) -> object:
        body = {
            "contents": [{"parts": [{"text": user}]}],
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": schema,
            },
        }
        request = urllib.request.Request(
            f"{API_BASE}/{self.model}:generateContent",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                raw = response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            raise LLMProviderError(f"gemini request failed: {exc}") from exc

        try:
            envelope = json.loads(raw)
            text = envelope["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            # An unexpected response shape is treated the same as "didn't
            # match schema" -- generate_structured's matches_schema check
            # will fail it and trigger the one retry, rather than this
            # method needing its own separate error path.
            return None
