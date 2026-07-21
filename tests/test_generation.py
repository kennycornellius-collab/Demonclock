"""Step 5 Chunks B+C: bounded batch context, Director/Story/Quest agents,
and the orchestrator that commits their output to the content pool. Entirely
offline (MockClient only)."""
from demonclock.canon import RequirementKind
from demonclock.clock import Clock
from demonclock.events import EventKind, ScheduledEvent
from demonclock.generation.context import build_batch_context
from demonclock.generation.director import INTENT_SCHEMA, DirectorIntent, run_director
from demonclock.generation.pipeline import run_batch
from demonclock.generation.places import NEW_PLACE_SCHEMA, NewPlace, materialize, run_places
from demonclock.generation.quest import QUEST_SCHEMA, run_quest, run_quest_repair
from demonclock.generation.story import SITUATION_SCHEMA, Situation, run_story
from demonclock.llm.config import GenerationConfig, ProviderSpec
from demonclock.llm.providers.mock import MockClient
from demonclock.llm.registry import LLMRegistry
from demonclock.models import Node
from demonclock.pool import GeneratedItem
from demonclock.player import new_player
from demonclock.state import GameState
from demonclock.world import World

GOOD_INTENT = {
    "responsive_weight": 0.6,
    "world_driven_weight": 0.4,
    "pressure_level": 1,
    "salient_threads": ["a rival caravan undercutting grain prices"],
}


def situation_dict(situation_id: str = "sit1", node_id: str = "village") -> dict:
    return {
        "id": situation_id,
        "title": "Trouble brews",
        "description": "Something is wrong in the village.",
        "node_id": node_id,
    }


def quest_dict(quest_id: str = "quest1", node_id: str = "village", required_state: str = "peaceful") -> dict:
    return {
        "id": quest_id,
        "title": "Set things right",
        "description": "Go fix the thing.",
        "reward_gold": 10,
        "manifest": {
            "requirements": [
                {"kind": RequirementKind.NODE_STATE.value, "target": {"node_id": node_id, "state": required_state}},
            ],
        },
    }


def quest_dict_needing_new_place(quest_id: str = "quest1", place_hint: str = "an abandoned mine") -> dict:
    data = quest_dict(quest_id)
    data["needs_new_place"] = True
    data["place_hint"] = place_hint
    return data


def new_place_dict(place_id: str = "abandoned_mine", direction: str = "east", travel_days: int = 2) -> dict:
    return {
        "id": place_id, "name": "Abandoned Mine", "type": "wilds",
        "direction": direction, "travel_days": travel_days,
    }


def make_full_registry(
    director_responses: list[object],
    story_responses: list[object],
    quest_responses: list[object],
    places_responses: list[object] | None = None,
) -> LLMRegistry:
    """Director/Story/Quest/Places each get their OWN mock client (distinct
    provider names) so a test can queue exactly the sequence of responses
    each role's calls should consume, in call order. `places_responses` is
    only wired in (as a configured "places" role) when given -- omitting it
    matches a registry with no places provider configured at all, which
    Chunk C's tests already rely on to prove Chunk D is purely additive."""
    roles = {
        "director": [ProviderSpec(provider="director_mock")],
        "story": [ProviderSpec(provider="story_mock")],
        "quest": [ProviderSpec(provider="quest_mock")],
    }
    extra_clients = {
        "director_mock": MockClient(responses=director_responses, name="director_mock"),
        "story_mock": MockClient(responses=story_responses, name="story_mock"),
        "quest_mock": MockClient(responses=quest_responses, name="quest_mock"),
    }
    if places_responses is not None:
        roles["places"] = [ProviderSpec(provider="places_mock")]
        extra_clients["places_mock"] = MockClient(responses=places_responses, name="places_mock")
    return LLMRegistry(GenerationConfig(roles=roles), extra_clients=extra_clients)


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


# -- Story agent (Chunk C) -------------------------------------------------

def test_run_story_parses_a_well_formed_situation_and_tags_its_stream():
    registry = make_full_registry([GOOD_INTENT], [situation_dict("sit1")], [])
    state = make_state(registry)
    intent = DirectorIntent.from_dict(GOOD_INTENT)

    situation = run_story(registry, build_batch_context(state), intent, "responsive")

    assert situation == Situation(
        id="sit1", title="Trouble brews", description="Something is wrong in the village.",
        node_id="village", stream="responsive",
    )


def test_situation_schema_requires_all_four_fields():
    assert set(SITUATION_SCHEMA["required"]) == {"id", "title", "description", "node_id"}


# -- Quest agent (Chunk C) --------------------------------------------------

def test_run_quest_builds_a_generated_item_with_a_real_manifest():
    registry = make_full_registry([], [], [quest_dict("quest1")])
    state = make_state(registry)
    situation = Situation(id="sit1", title="t", description="d", node_id="village", stream="responsive")

    item = run_quest(registry, build_batch_context(state), situation)

    assert isinstance(item, GeneratedItem)
    assert item.id == "quest1"
    assert item.payload["title"] == "Set things right"
    assert item.manifest.requirements[0].kind is RequirementKind.NODE_STATE
    assert item.manifest.requirements[0].target == {"node_id": "village", "state": "peaceful"}


def test_run_quest_repair_reprompts_with_the_failing_requirements():
    registry = make_full_registry([], [], [quest_dict("quest1", required_state="peaceful")])
    state = make_state(registry)
    situation = Situation(id="sit1", title="t", description="d", node_id="village", stream="responsive")
    original = GeneratedItem(id="quest1", payload={"title": "broken"}, manifest=None)
    from demonclock.canon import Requirement, RequirementResult
    failure = RequirementResult(
        requirement=Requirement(RequirementKind.NODE_STATE, {"node_id": "village", "state": "occupied"}),
        passed=False, reason="node state is 'peaceful', expected 'occupied'",
    )

    repaired = run_quest_repair(registry, build_batch_context(state), situation, original, [failure])

    assert repaired.manifest.requirements[0].target["state"] == "peaceful"


def test_quest_schema_requires_kind_to_be_a_real_requirement_kind():
    manifest_item_schema = QUEST_SCHEMA["properties"]["manifest"]["properties"]["requirements"]["items"]
    assert set(manifest_item_schema["properties"]["kind"]["enum"]) == {k.value for k in RequirementKind}


# -- pipeline.run_batch: Story + Quest -> content pool (Chunk C) -----------

def test_run_batch_commits_both_streams_when_everything_succeeds():
    registry = make_full_registry(
        [GOOD_INTENT],
        [situation_dict("sit_responsive"), situation_dict("sit_world")],
        [quest_dict("quest_responsive"), quest_dict("quest_world")],
    )
    state = make_state(registry)

    intent = run_batch(state, registry)

    assert intent == DirectorIntent.from_dict(GOOD_INTENT)
    committed_ids = {item.id for item in state.world.content_pool}
    assert committed_ids == {"quest_responsive", "quest_world"}


def test_run_batch_repairs_a_failing_manifest_before_committing():
    failing_quest = quest_dict("quest_responsive", required_state="occupied")  # village is actually peaceful
    repaired_quest = quest_dict("quest_responsive", required_state="peaceful")
    good_quest = quest_dict("quest_world")
    registry = make_full_registry(
        [GOOD_INTENT],
        [situation_dict("sit_responsive"), situation_dict("sit_world")],
        [failing_quest, repaired_quest, good_quest],
    )
    state = make_state(registry)

    run_batch(state, registry)

    assert len(state.world.content_pool) == 2
    responsive_item = next(item for item in state.world.content_pool if item.id == "quest_responsive")
    assert responsive_item.manifest.requirements[0].target["state"] == "peaceful"  # the repaired version


def test_run_batch_one_stream_failing_does_not_cancel_the_other():
    # Only ONE story response queued -- the second stream's run_story call
    # exhausts the mock's response queue and raises MalformedGenerationError,
    # which must not take down the first stream's already-committed item or
    # the returned intent.
    registry = make_full_registry(
        [GOOD_INTENT],
        [situation_dict("sit_responsive")],  # only one -- second stream's story call fails
        [quest_dict("quest_responsive")],
    )
    state = make_state(registry)

    intent = run_batch(state, registry)

    assert intent == DirectorIntent.from_dict(GOOD_INTENT)
    assert [item.id for item in state.world.content_pool] == ["quest_responsive"]


def test_run_batch_still_returns_intent_when_quest_role_is_unconfigured():
    # A registry with only "director" configured (Chunk B's original
    # make_registry) must keep working exactly as it did before Chunk C --
    # story/quest simply have no provider chain, NoProviderConfiguredError
    # is swallowed per-stream, pool stays empty, intent still returned.
    registry = make_registry([GOOD_INTENT])
    state = make_state(registry)

    intent = run_batch(state, registry)

    assert intent == DirectorIntent.from_dict(GOOD_INTENT)
    assert state.world.content_pool == []


# -- Places agent (Chunk D) -------------------------------------------------

def test_run_places_parses_a_well_formed_new_place():
    registry = make_full_registry([], [], [], places_responses=[new_place_dict()])
    state = make_state(registry)
    situation = Situation(id="sit1", title="t", description="d", node_id="village", stream="responsive")

    new_place = run_places(registry, build_batch_context(state), situation, "an abandoned mine")

    assert new_place == NewPlace(id="abandoned_mine", name="Abandoned Mine", type="wilds", direction="east", travel_days=2)


def test_new_place_schema_requires_all_five_fields():
    assert set(NEW_PLACE_SCHEMA["required"]) == {"id", "name", "type", "direction", "travel_days"}


def test_materialize_adds_a_bidirectional_link_with_the_proposed_travel_days():
    state = make_state()
    new_place = NewPlace(id="abandoned_mine", name="Abandoned Mine", type="wilds", direction="east", travel_days=2)

    ok = materialize(state, "village", new_place)

    assert ok is True
    assert state.world.nodes["abandoned_mine"].name == "Abandoned Mine"
    forward = state.world.get_link("village", "abandoned_mine")
    reverse = state.world.get_link("abandoned_mine", "village")
    assert forward.travel_days == 2
    assert reverse is not None  # bidirectional-by-construction (SPEC.md §3)
    assert reverse.direction == "west"  # the known opposite of "east"


def test_materialize_rejects_an_unrecognized_direction_and_rolls_back_the_node():
    state = make_state()
    new_place = NewPlace(id="floating_isle", name="Floating Isle", type="wilds", direction="northeast", travel_days=2)

    ok = materialize(state, "village", new_place)

    assert ok is False
    assert "floating_isle" not in state.world.nodes  # rolled back, not left orphaned


def test_materialize_rejects_a_travel_days_of_zero():
    state = make_state()
    new_place = NewPlace(id="too_close", name="Too Close", type="wilds", direction="east", travel_days=0)

    ok = materialize(state, "village", new_place)

    assert ok is False
    assert "too_close" not in state.world.nodes


def test_materialize_refuses_to_overwrite_an_existing_node_id():
    state = make_state()
    new_place = NewPlace(id="market", name="A Different Market", type="wilds", direction="east", travel_days=1)

    ok = materialize(state, "village", new_place)

    assert ok is False
    assert state.world.nodes["market"].name == "Millhaven Market"  # untouched


# -- pipeline.run_batch: Places extends the graph only when asked (Chunk D) -

def test_run_batch_materializes_a_new_place_when_a_quest_asks_for_one():
    registry = make_full_registry(
        [GOOD_INTENT],
        [situation_dict("sit_responsive"), situation_dict("sit_world")],
        [quest_dict_needing_new_place("quest_responsive"), quest_dict("quest_world")],
        places_responses=[new_place_dict()],
    )
    state = make_state(registry)

    run_batch(state, registry)

    assert "abandoned_mine" in state.world.nodes
    assert state.world.get_link("village", "abandoned_mine") is not None
    # the quest itself still commits regardless of the new place
    assert {item.id for item in state.world.content_pool} == {"quest_responsive", "quest_world"}


def test_run_batch_never_calls_places_for_an_ordinary_quest():
    registry = make_full_registry(
        [GOOD_INTENT],
        [situation_dict("sit_responsive"), situation_dict("sit_world")],
        [quest_dict("quest_responsive"), quest_dict("quest_world")],
        places_responses=[new_place_dict()],
    )
    state = make_state(registry)

    run_batch(state, registry)

    places_client = registry._explicit_clients["places_mock"]
    assert places_client.call_count == 0  # never asked -- neither quest needed a new place


def test_run_batch_commits_the_quest_even_when_places_generation_fails():
    registry = make_full_registry(
        [GOOD_INTENT],
        [situation_dict("sit_responsive"), situation_dict("sit_world")],
        [quest_dict_needing_new_place("quest_responsive"), quest_dict("quest_world")],
        places_responses=[],  # empty queue -- the places call fails
    )
    state = make_state(registry)

    run_batch(state, registry)

    assert "abandoned_mine" not in state.world.nodes  # not created
    # but the quest itself is not held hostage by the missing place
    assert {item.id for item in state.world.content_pool} == {"quest_responsive", "quest_world"}
