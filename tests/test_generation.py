"""Step 5 Chunk B: bounded batch context + Director agent + orchestrator.
Entirely offline (MockClient only)."""
from demonclock.clock import Clock
from demonclock.events import EventKind, ScheduledEvent
from demonclock.generation.context import build_batch_context
from demonclock.generation.director import INTENT_SCHEMA, DirectorIntent, run_director
from demonclock.generation.pipeline import run_batch
from demonclock.llm.config import GenerationConfig, ProviderSpec
from demonclock.llm.providers.mock import MockClient
from demonclock.llm.registry import LLMRegistry
from demonclock.models import Node
from demonclock.player import new_player
from demonclock.state import GameState
from demonclock.world import World

GOOD_INTENT = {
    "responsive_weight": 0.6,
    "world_driven_weight": 0.4,
    "pressure_level": 1,
    "salient_threads": ["a rival caravan undercutting grain prices"],
}


def make_world() -> World:
    world = World()
    world.add_node(Node(id="village", name="Millhaven Village"))
    world.add_node(Node(id="market", name="Millhaven Market"))
    world.add_node(Node(id="far_away", name="Somewhere Distant"))
    world.add_link("village", "market", "east", travel_days=1)
    # "far_away" is deliberately NOT linked to "village" -- proves the bounded
    # slice doesn't just dump the whole graph.
    return world


def make_state(registry: LLMRegistry | None = None) -> GameState:
    world = make_world()
    player = new_player(name="Hero", location_id="village")
    return GameState(world=world, player=player, clock=Clock(current_day=10), generation=registry)


def make_registry(responses: list[object]) -> LLMRegistry:
    config = GenerationConfig(roles={"director": [ProviderSpec(provider="mock")]})
    return LLMRegistry(config, extra_clients={"mock": MockClient(responses=responses)})


# -- build_batch_context: the bounded-retrieval invariant ------------------

def test_batch_context_includes_current_node_and_day():
    state = make_state()
    context = build_batch_context(state)

    assert context["day"] == 10
    assert context["current_node"]["id"] == "village"
    assert context["player"]["location_id"] == "village"


def test_batch_context_includes_only_immediate_neighbors_not_the_whole_graph():
    state = make_state()
    context = build_batch_context(state)

    neighbor_ids = {node["id"] for node in context["neighbor_nodes"]}
    assert neighbor_ids == {"market"}
    assert "far_away" not in neighbor_ids  # unreachable in one hop -- must not leak in


def test_batch_context_includes_only_the_most_recent_events_not_the_whole_log():
    from demonclock import history

    state = make_state()
    for i in range(10):
        history.record(state.world.event_log, i, "village", EventKind.SET_NODE_STATE, f"event {i}")

    context = build_batch_context(state)

    assert len(context["recent_events"]) == 5  # RECENT_EVENT_LIMIT, not all 10
    assert context["recent_events"][-1]["description"] == "event 9"


def test_batch_context_reflects_derived_role_hint():
    state = make_state()
    state.player.behavior.combat_actions = 10.0
    context = build_batch_context(state)
    assert "combat-focused" in context["player"]["derived_role_hint"]


# -- Director agent ----------------------------------------------------

def test_run_director_parses_a_well_formed_intent():
    registry = make_registry([GOOD_INTENT])
    state = make_state(registry)
    context = build_batch_context(state)

    intent = run_director(registry, context)

    assert intent == DirectorIntent.from_dict(GOOD_INTENT)
    assert intent.pressure_level == 1
    assert intent.salient_threads == ["a rival caravan undercutting grain prices"]


def test_director_intent_schema_requires_all_four_fields():
    assert set(INTENT_SCHEMA["required"]) == {
        "responsive_weight", "world_driven_weight", "pressure_level", "salient_threads",
    }


# -- pipeline.run_batch: graceful degradation --------------------------

def test_run_batch_returns_none_when_registry_is_disabled():
    registry = LLMRegistry(GenerationConfig(roles={}))
    state = make_state(registry)

    assert run_batch(state, registry) is None


def test_run_batch_returns_the_director_intent_when_configured():
    registry = make_registry([GOOD_INTENT])
    state = make_state(registry)

    intent = run_batch(state, registry)

    assert intent == DirectorIntent.from_dict(GOOD_INTENT)


def test_run_batch_degrades_to_none_on_a_provider_error_rather_than_raising():
    config = GenerationConfig(roles={"director": [ProviderSpec(provider="mock")]})
    registry = LLMRegistry(config, extra_clients={"mock": MockClient(always_error=RuntimeError("down"))})
    state = make_state(registry)

    assert run_batch(state, registry) is None


def test_run_batch_degrades_to_none_on_malformed_output_rather_than_raising():
    registry = make_registry([{"pressure_level": "not an int"}, {"pressure_level": "still not"}])
    state = make_state(registry)

    assert run_batch(state, registry) is None
