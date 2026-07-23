"""Step 7 Chunk A: the Narrator agent's one job -- rewording an already-
decided rumor string, never inventing a fact. Entirely offline (MockClient
only), same posture as every other generation-role test."""
from demonclock.generation.narrator import REWORD_RUMOR_SCHEMA, reword_rumor
from demonclock.llm.config import GenerationConfig, ProviderSpec
from demonclock.llm.providers.mock import MockClient
from demonclock.llm.registry import LLMRegistry


def make_registry(responses: list[object]) -> LLMRegistry:
    config = GenerationConfig(roles={"narrator": [ProviderSpec(provider="mock")]})
    return LLMRegistry(config, extra_clients={"mock": MockClient(responses=responses)})


def test_reword_rumor_returns_the_original_text_when_registry_is_none():
    assert reword_rumor(None, "A falls.", 0.8) == "A falls."


def test_reword_rumor_returns_the_original_text_when_registry_is_disabled():
    registry = LLMRegistry(GenerationConfig(roles={}))
    assert reword_rumor(registry, "A falls.", 0.8) == "A falls."


def test_reword_rumor_returns_the_original_text_when_narrator_role_is_unconfigured():
    # Some other role (director) is configured, but not narrator specifically
    # -- registry.enabled is True, but generate("narrator", ...) raises
    # NoProviderConfiguredError, which must still degrade gracefully.
    config = GenerationConfig(roles={"director": [ProviderSpec(provider="mock")]})
    registry = LLMRegistry(config, extra_clients={"mock": MockClient(responses=[])})

    assert reword_rumor(registry, "A falls.", 0.8) == "A falls."


def test_reword_rumor_uses_the_ai_response_when_the_call_succeeds():
    registry = make_registry([{"text": "They say the town of A has fallen..."}])

    assert reword_rumor(registry, "A falls.", 0.8) == "They say the town of A has fallen..."


def test_reword_rumor_falls_back_to_original_text_on_a_provider_error():
    config = GenerationConfig(roles={"narrator": [ProviderSpec(provider="mock")]})
    registry = LLMRegistry(config, extra_clients={"mock": MockClient(always_error=RuntimeError("down"))})

    assert reword_rumor(registry, "A falls.", 0.8) == "A falls."


def test_reword_rumor_falls_back_to_original_text_on_malformed_output():
    registry = make_registry([{"not_text": "oops"}, {"still": "wrong"}])

    assert reword_rumor(registry, "A falls.", 0.8) == "A falls."


def test_reword_rumor_falls_back_when_the_ai_returns_an_empty_string():
    registry = make_registry([{"text": "   "}])

    assert reword_rumor(registry, "A falls.", 0.8) == "A falls."


def test_reword_rumor_schema_requires_text():
    assert REWORD_RUMOR_SCHEMA["required"] == ["text"]
