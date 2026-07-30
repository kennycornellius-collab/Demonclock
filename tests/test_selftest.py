from demonclock.llm.config import GenerationConfig, ProviderSpec
from demonclock.llm.providers.mock import MockClient
from demonclock.llm.registry import LLMRegistry
from demonclock.llm.selftest import check_connectivity


def test_check_connectivity_returns_false_when_nothing_is_configured():
    config = GenerationConfig(roles={})
    registry = LLMRegistry(config)
    assert check_connectivity(registry, config) is False


def test_check_connectivity_returns_true_on_a_successful_ping():
    config = GenerationConfig(roles={"director": [ProviderSpec(provider="mock")]})
    registry = LLMRegistry(config, extra_clients={"mock": MockClient(responses=[{"ok": True}])})
    assert check_connectivity(registry, config) is True


def test_check_connectivity_returns_false_on_a_provider_error():
    config = GenerationConfig(roles={"director": [ProviderSpec(provider="mock")]})
    registry = LLMRegistry(
        config, extra_clients={"mock": MockClient(always_error=RuntimeError("down"))}
    )
    assert check_connectivity(registry, config) is False


def test_check_connectivity_returns_false_on_malformed_output():
    config = GenerationConfig(roles={"director": [ProviderSpec(provider="mock")]})
    registry = LLMRegistry(
        config, extra_clients={"mock": MockClient(responses=[{"bad": "shape"}, {"still": "wrong"}])}
    )
    assert check_connectivity(registry, config) is False


def test_check_connectivity_checks_whichever_role_is_configured_first_in_roles_order():
    # GenerationConfig.from_env()'s own default routes every role to the
    # same chain, so this only matters for a hand-built config with just
    # one role set -- confirms it doesn't blow up picking a role that
    # happens not to be "director".
    config = GenerationConfig(roles={"narrator": [ProviderSpec(provider="mock")]})
    registry = LLMRegistry(config, extra_clients={"mock": MockClient(responses=[{"ok": True}])})
    assert check_connectivity(registry, config) is True
