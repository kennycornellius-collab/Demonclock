"""Step 5 Chunk A: the provider-agnostic LLM client layer. Entirely offline --
every test uses MockClient, never a real network call (Gemini's request/
response shaping is exercised separately by monkeypatching urllib)."""
import json
import os
from unittest.mock import patch

import pytest

from demonclock.llm.config import GenerationConfig, ProviderSpec
from demonclock.llm.errors import LLMProviderError, MalformedGenerationError
from demonclock.llm.providers.gemini import GeminiClient
from demonclock.llm.providers.mock import MockClient
from demonclock.llm.registry import LLMRegistry, NoProviderConfiguredError
from demonclock.llm.schema import matches_schema

SCHEMA = {
    "type": "object",
    "properties": {"pressure": {"type": "integer"}},
    "required": ["pressure"],
}


def make_config(role: str, chain: list[ProviderSpec]) -> GenerationConfig:
    return GenerationConfig(roles={role: chain})


# -- schema.matches_schema ------------------------------------------------

def test_matches_schema_accepts_a_matching_object():
    assert matches_schema({"pressure": 2}, SCHEMA)


def test_matches_schema_rejects_a_missing_required_key():
    assert not matches_schema({}, SCHEMA)


def test_matches_schema_rejects_wrong_type():
    assert not matches_schema({"pressure": "high"}, SCHEMA)


def test_matches_schema_never_raises_on_garbage_input():
    assert not matches_schema("not even a dict", SCHEMA)
    assert not matches_schema(None, {"type": "object", "properties": None})


# -- MockClient's one-retry-then-discard contract --------------------------

def test_mock_client_returns_a_matching_first_response():
    client = MockClient(responses=[{"pressure": 1}])
    assert client.generate_structured("sys", "usr", SCHEMA) == {"pressure": 1}
    assert client.call_count == 1


def test_mock_client_retries_once_on_malformed_output_then_succeeds():
    client = MockClient(responses=[{"pressure": "bad"}, {"pressure": 3}])
    assert client.generate_structured("sys", "usr", SCHEMA) == {"pressure": 3}


def test_mock_client_raises_malformed_after_the_retry_also_fails():
    client = MockClient(responses=[{"pressure": "bad"}, {"pressure": "still bad"}])
    with pytest.raises(MalformedGenerationError):
        client.generate_structured("sys", "usr", SCHEMA)


def test_mock_client_always_error_raises_provider_error_every_call():
    client = MockClient(always_error=RuntimeError("down"))
    with pytest.raises(LLMProviderError):
        client.generate_structured("sys", "usr", SCHEMA)
    with pytest.raises(LLMProviderError):
        client.generate_structured("sys", "usr", SCHEMA)


def test_mock_client_queued_exception_raises_provider_error_without_retry():
    client = MockClient(responses=[RuntimeError("network blip")])
    with pytest.raises(LLMProviderError):
        client.generate_structured("sys", "usr", SCHEMA)
    assert client.call_count == 1  # a hard error is not internally retried


# -- LLMRegistry: static default + fallback chain ("both", per user) -------

def test_registry_uses_the_static_default_provider():
    good = MockClient(responses=[{"pressure": 1}])
    config = make_config("director", [ProviderSpec(provider="primary")])
    registry = LLMRegistry(config, extra_clients={"primary": good})

    result = registry.generate("director", "sys", "usr", SCHEMA)

    assert result == {"pressure": 1}
    assert good.call_count == 1


def test_registry_falls_back_to_the_next_provider_on_provider_error():
    bad = MockClient(always_error=RuntimeError("outage"))
    good = MockClient(responses=[{"pressure": 5}])
    config = make_config("director", [ProviderSpec(provider="bad"), ProviderSpec(provider="good")])
    registry = LLMRegistry(config, extra_clients={"bad": bad, "good": good})

    result = registry.generate("director", "sys", "usr", SCHEMA)

    assert result == {"pressure": 5}
    assert bad.call_count == 1
    assert good.call_count == 1


def test_registry_does_not_fall_back_on_malformed_generation():
    # A different provider has no particular reason to do better against the
    # same prompt, so malformed output bubbles up rather than trying "good".
    malformed = MockClient(responses=[{"pressure": "bad"}, {"pressure": "still bad"}])
    good = MockClient(responses=[{"pressure": 9}])
    config = make_config("director", [ProviderSpec(provider="malformed"), ProviderSpec(provider="good")])
    registry = LLMRegistry(config, extra_clients={"malformed": malformed, "good": good})

    with pytest.raises(MalformedGenerationError):
        registry.generate("director", "sys", "usr", SCHEMA)

    assert good.call_count == 0


def test_registry_raises_the_last_provider_error_when_the_whole_chain_fails():
    first = MockClient(always_error=RuntimeError("first down"))
    second = MockClient(always_error=RuntimeError("second down"))
    config = make_config("director", [ProviderSpec(provider="first"), ProviderSpec(provider="second")])
    registry = LLMRegistry(config, extra_clients={"first": first, "second": second})

    with pytest.raises(LLMProviderError):
        registry.generate("director", "sys", "usr", SCHEMA)


def test_registry_raises_no_provider_configured_for_an_unconfigured_role():
    config = GenerationConfig(roles={})
    registry = LLMRegistry(config)

    with pytest.raises(NoProviderConfiguredError):
        registry.generate("director", "sys", "usr", SCHEMA)


def test_registry_enabled_reflects_whether_any_role_has_a_provider():
    assert not LLMRegistry(GenerationConfig(roles={})).enabled
    assert LLMRegistry(make_config("director", [ProviderSpec(provider="mock")])).enabled


# -- GenerationConfig.from_env ---------------------------------------------

def test_from_env_is_disabled_with_no_key_and_no_config_file():
    with patch.dict(os.environ, {}, clear=True):
        config = GenerationConfig.from_env()
    assert not config.enabled
    assert config.roles == {}


def test_from_env_routes_every_role_to_gemini_when_the_key_is_set():
    with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True):
        config = GenerationConfig.from_env()
    assert config.enabled
    assert config.api_keys["gemini"] == "test-key"
    for role in ("director", "story", "quest", "places", "entity_resolution"):
        assert config.roles[role] == [ProviderSpec(provider="gemini")]


def test_from_env_config_file_overrides_the_default_routing(tmp_path):
    config_file = tmp_path / "llm_config.json"
    config_file.write_text(json.dumps({"director": [{"provider": "gemini", "model": "custom-model"}]}))
    with patch.dict(
        os.environ,
        {"GEMINI_API_KEY": "test-key", "DEMONCLOCK_LLM_CONFIG": str(config_file)},
        clear=True,
    ):
        config = GenerationConfig.from_env()
    assert config.roles == {"director": [ProviderSpec(provider="gemini", model="custom-model")]}
    assert "story" not in config.roles


# -- GeminiClient: request/response shaping, no real network ---------------

class _FakeHTTPResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _gemini_envelope(inner_json: dict) -> bytes:
    return json.dumps({
        "candidates": [{"content": {"parts": [{"text": json.dumps(inner_json)}]}}]
    }).encode("utf-8")


def test_gemini_client_returns_parsed_structured_output():
    client = GeminiClient(api_key="fake-key")
    with patch("urllib.request.urlopen", return_value=_FakeHTTPResponse(_gemini_envelope({"pressure": 2}))) as mock_urlopen:
        result = client.generate_structured("sys", "usr", SCHEMA)

    assert result == {"pressure": 2}
    request = mock_urlopen.call_args[0][0]
    assert request.headers["X-goog-api-key"] == "fake-key"
    body = json.loads(request.data)
    assert body["generationConfig"]["responseSchema"] == SCHEMA
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["contents"][0]["parts"][0]["text"] == "usr"
    assert body["systemInstruction"]["parts"][0]["text"] == "sys"


def test_gemini_client_retries_once_on_malformed_response_then_succeeds():
    responses = [
        _FakeHTTPResponse(_gemini_envelope({"pressure": "not an int"})),
        _FakeHTTPResponse(_gemini_envelope({"pressure": 7})),
    ]
    client = GeminiClient(api_key="fake-key")
    with patch("urllib.request.urlopen", side_effect=responses):
        result = client.generate_structured("sys", "usr", SCHEMA)
    assert result == {"pressure": 7}


def test_gemini_client_raises_malformed_after_retry_also_fails():
    responses = [
        _FakeHTTPResponse(_gemini_envelope({"pressure": "bad"})),
        _FakeHTTPResponse(_gemini_envelope({"pressure": "still bad"})),
    ]
    client = GeminiClient(api_key="fake-key")
    with patch("urllib.request.urlopen", side_effect=responses):
        with pytest.raises(MalformedGenerationError):
            client.generate_structured("sys", "usr", SCHEMA)


def test_gemini_client_wraps_a_transport_failure_as_provider_error():
    import urllib.error

    client = GeminiClient(api_key="fake-key")
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("boom")):
        with pytest.raises(LLMProviderError):
            client.generate_structured("sys", "usr", SCHEMA)


def test_gemini_client_rejects_an_empty_api_key():
    with pytest.raises(ValueError):
        GeminiClient(api_key="")
