from demonclock.llm.config import GenerationConfig, ProviderSpec
from demonclock.llm.providers.mock import MockClient
from demonclock.llm.registry import LLMRegistry
from demonclock.resolve import NO_MATCH, resolve_entity


def make_registry_and_client(responses: list[object]) -> tuple[LLMRegistry, MockClient]:
    config = GenerationConfig(roles={"entity_resolution": [ProviderSpec(provider="mock")]})
    client = MockClient(responses=responses)
    return LLMRegistry(config, extra_clients={"mock": client}), client


def test_exact_match_resolves():
    shortlist = [("npc_001", "Old Lord"), ("npc_002", "Merchant Guild Rep")]
    assert resolve_entity("Old Lord", shortlist) == "npc_001"


def test_exact_match_is_case_and_whitespace_insensitive():
    shortlist = [("npc_001", "Old Lord")]
    assert resolve_entity("  old   LORD  ", shortlist) == "npc_001"


def test_no_match_returns_none():
    shortlist = [("npc_001", "Old Lord")]
    assert resolve_entity("Harbor Master", shortlist) is None


def test_duplicate_exact_names_are_ambiguous_and_unresolved():
    # Exactly why identity must be an id, never a name (SPEC.md §8).
    shortlist = [("npc_001", "Old Lord"), ("npc_002", "Old Lord")]
    assert resolve_entity("Old Lord", shortlist) is None


def test_fuzzy_token_match_resolves_a_loosely_worded_reference():
    shortlist = [("npc_001", "Old Lord"), ("npc_002", "Merchant Guild Rep")]
    assert resolve_entity("the old lord", shortlist) == "npc_001"


def test_fuzzy_token_match_works_in_the_other_direction_too():
    shortlist = [("node_042", "Old North Road")]
    assert resolve_entity("road", shortlist) == "node_042"


def test_fuzzy_token_match_ignores_a_leading_stopword_the_others_lack():
    # A pure substring check would miss this ("the wilds" is not a
    # substring of "Bramblewood Wilds" and vice versa); stopword-filtered
    # token-subset matching resolves it correctly.
    shortlist = [("node_099", "Bramblewood Wilds"), ("node_100", "Millhaven Market")]
    assert resolve_entity("the wilds", shortlist) == "node_099"


def test_fuzzy_token_match_is_unresolved_when_multiple_candidates_share_a_word():
    shortlist = [("npc_001", "Old Lord"), ("npc_002", "Old Blacksmith")]
    assert resolve_entity("old", shortlist) is None


def test_fuzzy_token_match_is_unresolved_on_a_shared_partial_name():
    shortlist = [("village", "Millhaven Village"), ("market", "Millhaven Market")]
    assert resolve_entity("Millhaven", shortlist) is None


def test_never_matches_something_absent_from_the_shortlist():
    # Bounded context (SPEC.md §8): even a real, well-known name elsewhere
    # in the world must not resolve unless it's actually on the shortlist
    # the caller retrieved.
    shortlist = [("npc_002", "Merchant Guild Rep")]
    assert resolve_entity("Old Lord", shortlist) is None


def test_empty_reference_text_returns_none():
    shortlist = [("npc_001", "Old Lord")]
    assert resolve_entity("   ", shortlist) is None


def test_empty_shortlist_returns_none():
    assert resolve_entity("Old Lord", []) is None


def test_resolves_against_real_world_nodes_by_name():
    from demonclock.seed import new_default_world

    world = new_default_world()
    shortlist = [(node.id, node.name) for node in world.nodes.values()]

    assert resolve_entity("Millhaven Market", shortlist) == "market"
    assert resolve_entity("wilds", shortlist) == "wilds"
    assert resolve_entity("the wilds", shortlist) == "wilds"  # token-subset match
    assert resolve_entity("Some Unrelated Place", shortlist) is None


# -- AI fallback (Step 5 Chunk D, SPEC.md §8) ------------------------------

def test_ai_fallback_resolves_a_reference_the_deterministic_passes_could_not():
    shortlist = [("npc_001", "Old Lord"), ("npc_002", "Old Blacksmith")]
    registry, client = make_registry_and_client([{"resolved_id": "npc_001"}])

    assert resolve_entity("old", shortlist, registry) == "npc_001"
    assert client.call_count == 1


def test_ai_fallback_returns_none_on_the_no_match_sentinel():
    shortlist = [("npc_001", "Old Lord"), ("npc_002", "Old Blacksmith")]
    registry, _ = make_registry_and_client([{"resolved_id": NO_MATCH}])

    assert resolve_entity("the harbor master", shortlist, registry) is None


def test_ai_fallback_is_never_consulted_when_an_exact_match_already_resolves():
    # "Most resolutions cost zero AI calls" (SPEC.md §6/§8) -- the AI step is
    # a fallback, not a first-class check run every time.
    shortlist = [("npc_001", "Old Lord")]
    registry, client = make_registry_and_client([{"resolved_id": "npc_001"}])

    assert resolve_entity("Old Lord", shortlist, registry) == "npc_001"
    assert client.call_count == 0


def test_ai_fallback_is_never_consulted_when_a_fuzzy_match_already_resolves():
    shortlist = [("npc_001", "Old Lord"), ("npc_002", "Merchant Guild Rep")]
    registry, client = make_registry_and_client([{"resolved_id": "npc_001"}])

    assert resolve_entity("the old lord", shortlist, registry) == "npc_001"
    assert client.call_count == 0


def test_ai_fallback_degrades_to_none_on_a_provider_error():
    shortlist = [("npc_001", "Old Lord"), ("npc_002", "Old Blacksmith")]
    config = GenerationConfig(roles={"entity_resolution": [ProviderSpec(provider="mock")]})
    registry = LLMRegistry(config, extra_clients={"mock": MockClient(always_error=RuntimeError("down"))})

    assert resolve_entity("old", shortlist, registry) is None


def test_ai_fallback_never_returns_an_id_outside_the_shortlist():
    # The schema's enum only ever permits a real shortlist id or NO_MATCH --
    # an out-of-shortlist id is malformed output to the schema, not a
    # legitimate answer, so it degrades to None rather than being trusted.
    shortlist = [("npc_001", "Old Lord"), ("npc_002", "Old Blacksmith")]
    registry, _ = make_registry_and_client([
        {"resolved_id": "npc_999_not_on_the_shortlist"},
        {"resolved_id": "still_not_on_the_shortlist"},
    ])

    assert resolve_entity("old", shortlist, registry) is None


def test_ai_fallback_is_skipped_entirely_for_an_empty_shortlist():
    registry, client = make_registry_and_client([{"resolved_id": NO_MATCH}])

    assert resolve_entity("Old Lord", [], registry) is None
    assert client.call_count == 0  # never even asked -- nothing to resolve against


def test_resolve_entity_without_a_registry_is_unchanged():
    # The default (no registry) must behave exactly as it always did --
    # every pre-Chunk-D test above already proves this; this one just makes
    # the equivalence explicit for an ambiguous case that WOULD fall to AI
    # if a registry were supplied.
    shortlist = [("npc_001", "Old Lord"), ("npc_002", "Old Blacksmith")]
    assert resolve_entity("old", shortlist) is None
    assert resolve_entity("old", shortlist, registry=None) is None
