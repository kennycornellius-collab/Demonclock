"""Step 5 Chunks B+C: bounded batch context, Director/Story/Quest agents,
and the orchestrator that commits their output to the content pool. Entirely
offline (MockClient only)."""
import json

from demonclock.canon import RequirementKind
from demonclock.clock import Clock
from demonclock.events import EventKind, ScheduledEvent
from demonclock.generation.context import build_batch_context
from demonclock.generation.director import INTENT_SCHEMA, DirectorIntent, run_director
from demonclock.generation.flavor import FLAVOR_SCHEMA, SYSTEM_PROMPT as FLAVOR_SYSTEM_PROMPT, run_flavor
from demonclock.generation.npc import NEW_NPC_SCHEMA, NewNPC, materialize as materialize_npc, run_npc
from demonclock.generation.pipeline import STREAM_SKIP_THRESHOLD, _should_run_stream, run_batch
from demonclock.generation.places import NEW_PLACE_SCHEMA, NewPlace, materialize, run_places
from demonclock.generation.quest import QUEST_SCHEMA, SYSTEM_PROMPT as QUEST_SYSTEM_PROMPT, run_quest, run_quest_repair
from demonclock.generation.story import SITUATION_SCHEMA, SYSTEM_PROMPT as STORY_SYSTEM_PROMPT, Situation, run_story
from demonclock.llm.config import GenerationConfig, ProviderSpec
from demonclock.llm.providers.mock import MockClient
from demonclock.llm.registry import LLMRegistry
from demonclock.models import NPC, Faction, Node
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

# Step 7 Chunk D: weights lopsided enough to fall below STREAM_SKIP_THRESHOLD
# on one side.
RESPONSIVE_SKIPPED_INTENT = {
    "responsive_weight": 0.05,
    "world_driven_weight": 0.95,
    "pressure_level": 3,
    "salient_threads": ["the invasion is nearly complete"],
}
WORLD_DRIVEN_SKIPPED_INTENT = {
    "responsive_weight": 0.95,
    "world_driven_weight": 0.05,
    "pressure_level": 0,
    "salient_threads": [],
}


class SpyClient:
    """A minimal duck-typed LLMClient that just remembers the last `user`
    JSON string it was sent, so a test can assert what a caller actually
    put in the payload -- MockClient (every other test in this file) never
    records that, only the canned response it returns."""

    def __init__(self, response: dict) -> None:
        self._response = response
        self.last_user: str | None = None

    def generate_structured(self, system: str, user: str, schema: dict) -> dict:
        self.last_user = user
        return self._response


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
        # Step 10 Stage 2: completion is a second, separately-checked
        # manifest -- an arbitrary but schema-valid objective, distinct from
        # the precondition above (never asserted on by these Step 5 tests,
        # which only care about the precondition/pool-commit machinery).
        "completion": {
            "requirements": [
                {"kind": RequirementKind.PLAYER_GOLD_AT_LEAST.value, "target": {"amount": 0}},
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


def quest_dict_needing_new_npc(quest_id: str = "quest1", npc_hint: str = "a retired guard captain") -> dict:
    data = quest_dict(quest_id)
    data["needs_new_npc"] = True
    data["npc_hint"] = npc_hint
    return data


def new_npc_dict(npc_id: str = "old_miller") -> dict:
    return {
        "id": npc_id, "name": "Old Miller", "description": "A weathered veteran of the northern watch.",
        "tags": ["retired", "guard"],
    }


def make_full_registry(
    director_responses: list[object],
    story_responses: list[object],
    quest_responses: list[object],
    places_responses: list[object] | None = None,
    flavor_responses: list[object] | None = None,
    npc_responses: list[object] | None = None,
) -> LLMRegistry:
    """Director/Story/Quest/Places each get their OWN mock client (distinct
    provider names) so a test can queue exactly the sequence of responses
    each role's calls should consume, in call order. `places_responses`/
    `flavor_responses`/`npc_responses` are only wired in (as a configured
    "places"/"flavor"/"npc" role) when given -- omitting any matches a
    registry with no provider configured for it at all, which Chunk C's
    (Step 5) tests already rely on to prove Chunk D was purely additive, and
    Step 7 Chunk C's / Step 10 Stage 3's tests reuse the same pattern for
    "flavor"/"npc"."""
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
    if flavor_responses is not None:
        roles["flavor"] = [ProviderSpec(provider="flavor_mock")]
        extra_clients["flavor_mock"] = MockClient(responses=flavor_responses, name="flavor_mock")
    if npc_responses is not None:
        roles["npc"] = [ProviderSpec(provider="npc_mock")]
        extra_clients["npc_mock"] = MockClient(responses=npc_responses, name="npc_mock")
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


def test_batch_context_includes_known_factions():
    # Step 10 Stage 4 follow-up: without this, the Quest agent had no
    # legitimate faction id to ever reference for FACTION_STANDING_AT_LEAST
    # or faction_standing_delta other than hallucinating one.
    state = make_state()
    state.world.add_faction(Faction(id="merchants", name="The Merchants' Guild"))
    context = build_batch_context(state)

    assert context["known_factions"] == [
        {"id": "merchants", "name": "The Merchants' Guild", "description": ""}
    ]


def test_batch_context_known_factions_is_empty_when_none_are_seeded():
    state = make_state()
    context = build_batch_context(state)
    assert context["known_factions"] == []


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
    # Step 10 Stage 2: the completion manifest rides along in the payload as
    # a raw dict (unlike `manifest`, it's never lifted into a
    # PreconditionManifest object here -- quests.check_completion does that
    # itself, only once the quest is accepted and later checked at turn-in).
    assert item.payload["completion"]["requirements"][0]["kind"] == RequirementKind.PLAYER_GOLD_AT_LEAST.value


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


def test_quest_schema_requires_both_manifest_and_completion():
    assert "manifest" in QUEST_SCHEMA["required"]
    assert "completion" in QUEST_SCHEMA["required"]


def test_quest_schema_declares_needs_new_npc_and_npc_hint_as_optional():
    # Optional, same as needs_new_place/place_hint -- an ordinary quest
    # omits both entirely, so they must NOT be in "required".
    assert "needs_new_npc" in QUEST_SCHEMA["properties"]
    assert "npc_hint" in QUEST_SCHEMA["properties"]
    assert "needs_new_npc" not in QUEST_SCHEMA["required"]


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
    # "north" (not "east") -- make_world already gives "village" an
    # outgoing "east" link to "market", which add_link now rejects a
    # second outgoing link in the same direction from
    new_place = NewPlace(id="abandoned_mine", name="Abandoned Mine", type="wilds", direction="north", travel_days=2)

    ok = materialize(state, "village", new_place)

    assert ok is True
    assert state.world.nodes["abandoned_mine"].name == "Abandoned Mine"
    forward = state.world.get_link("village", "abandoned_mine")
    reverse = state.world.get_link("abandoned_mine", "village")
    assert forward.travel_days == 2
    assert reverse is not None  # bidirectional-by-construction (SPEC.md §3)
    assert reverse.direction == "south"  # the known opposite of "north"


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


def test_materialize_rejects_a_direction_collision_and_rolls_back_the_node():
    # make_world already links "village" -> "market" via "east"
    state = make_state()
    new_place = NewPlace(id="second_place", name="Second Place", type="wilds", direction="east", travel_days=1)

    ok = materialize(state, "village", new_place)

    assert ok is False
    assert "second_place" not in state.world.nodes  # rolled back, not left orphaned
    assert state.world.get_link("village", "market").travel_days == 1  # original link untouched


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
        # "north" -- "village" already has an outgoing "east" link (to
        # "market") in make_world, which add_link now rejects colliding into
        places_responses=[new_place_dict(direction="north")],
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


def test_run_batch_does_not_orphan_a_new_place_when_the_rejected_quest_never_commits():
    # Regression test: _maybe_extend_world used to run BEFORE commit_or_repair,
    # so a quest that fails canon check (and whose repair attempt also fails)
    # still left a new node/link permanently in World state with nothing --
    # no quest, no manifest -- ever referencing it.
    from demonclock.generation.director import DirectorIntent
    from demonclock.generation.pipeline import _generate_and_commit

    failing_quest = quest_dict_needing_new_place("quest_responsive", place_hint="an abandoned mine")
    failing_quest["manifest"]["requirements"][0]["target"]["state"] = "occupied"  # village is actually peaceful
    registry = make_full_registry(
        [GOOD_INTENT],
        [situation_dict("sit_responsive")],
        [failing_quest],  # only ONE response queued -- the repair attempt's own call also fails
        places_responses=[new_place_dict(direction="north")],
    )
    state = make_state(registry)
    context = build_batch_context(state)
    intent = DirectorIntent.from_dict(GOOD_INTENT)

    _generate_and_commit(state, registry, context, intent, "responsive")

    assert state.world.content_pool == []  # the quest never committed
    assert "abandoned_mine" not in state.world.nodes  # and nothing was orphaned into World state
    places_client = registry._explicit_clients["places_mock"]
    assert places_client.call_count == 0  # Places was never even asked


# -- NPC agent (Step 10 Stage 3) ---------------------------------------------

def test_run_npc_parses_a_well_formed_new_npc():
    registry = make_full_registry([], [], [], npc_responses=[new_npc_dict()])
    state = make_state(registry)
    situation = Situation(id="sit1", title="t", description="d", node_id="village", stream="responsive")

    new_npc = run_npc(registry, build_batch_context(state), situation, "a retired guard captain")

    assert new_npc == NewNPC(
        id="old_miller", name="Old Miller",
        description="A weathered veteran of the northern watch.", tags=["retired", "guard"],
    )


def test_new_npc_schema_requires_all_four_fields():
    assert set(NEW_NPC_SCHEMA["required"]) == {"id", "name", "description", "tags"}


def test_materialize_npc_adds_it_to_the_named_node():
    state = make_state()
    new_npc = NewNPC(id="old_miller", name="Old Miller", description="A veteran.", tags=["guard"])

    ok = materialize_npc(state, "village", new_npc)

    assert ok is True
    assert state.world.npcs["old_miller"].location_id == "village"
    assert state.world.npcs["old_miller"].name == "Old Miller"


def test_materialize_npc_refuses_to_overwrite_an_existing_npc_id():
    state = make_state()
    state.world.add_npc(NPC(id="old_miller", name="Original", location_id="village"))
    new_npc = NewNPC(id="old_miller", name="Impostor", description="", tags=[])

    ok = materialize_npc(state, "village", new_npc)

    assert ok is False
    assert state.world.npcs["old_miller"].name == "Original"  # untouched


def test_materialize_npc_refuses_an_unknown_anchor_node():
    state = make_state()
    new_npc = NewNPC(id="old_miller", name="Old Miller", description="", tags=[])

    ok = materialize_npc(state, "nowhere", new_npc)

    assert ok is False
    assert "old_miller" not in state.world.npcs


# -- pipeline.run_batch: NPC extends the world only when asked (Step 10 Stage 3)

def test_run_batch_materializes_a_new_npc_when_a_quest_asks_for_one():
    registry = make_full_registry(
        [GOOD_INTENT],
        [situation_dict("sit_responsive"), situation_dict("sit_world")],
        [quest_dict_needing_new_npc("quest_responsive"), quest_dict("quest_world")],
        npc_responses=[new_npc_dict()],
    )
    state = make_state(registry)

    run_batch(state, registry)

    assert "old_miller" in state.world.npcs
    assert state.world.npcs["old_miller"].location_id == "village"
    # the quest itself still commits regardless of the new NPC
    assert {item.id for item in state.world.content_pool} == {"quest_responsive", "quest_world"}


def test_run_batch_never_calls_npc_for_an_ordinary_quest():
    registry = make_full_registry(
        [GOOD_INTENT],
        [situation_dict("sit_responsive"), situation_dict("sit_world")],
        [quest_dict("quest_responsive"), quest_dict("quest_world")],
        npc_responses=[new_npc_dict()],
    )
    state = make_state(registry)

    run_batch(state, registry)

    npc_client = registry._explicit_clients["npc_mock"]
    assert npc_client.call_count == 0  # never asked -- neither quest needed a new NPC


def test_run_batch_commits_the_quest_even_when_npc_generation_fails():
    registry = make_full_registry(
        [GOOD_INTENT],
        [situation_dict("sit_responsive"), situation_dict("sit_world")],
        [quest_dict_needing_new_npc("quest_responsive"), quest_dict("quest_world")],
        npc_responses=[],  # empty queue -- the npc call fails
    )
    state = make_state(registry)

    run_batch(state, registry)

    assert "old_miller" not in state.world.npcs  # not created
    # but the quest itself is not held hostage by the missing NPC
    assert {item.id for item in state.world.content_pool} == {"quest_responsive", "quest_world"}


# -- Flavor agent (Step 7 Chunk C) -------------------------------------------

def flavor_response(*lines: tuple[str, str]) -> dict:
    return {"lines": [{"node_id": node_id, "text": text} for node_id, text in lines]}


def test_run_flavor_returns_a_line_per_known_node():
    registry = make_full_registry([], [], [], flavor_responses=[
        flavor_response(
            ("village", "Woodsmoke drifts over the rooftops."),
            ("market", "Stalls creak under the weight of the harvest."),
        ),
    ])
    state = make_state(registry)

    lines = run_flavor(registry, build_batch_context(state))

    assert lines == {
        "village": "Woodsmoke drifts over the rooftops.",
        "market": "Stalls creak under the weight of the harvest.",
    }


def test_run_flavor_drops_a_line_for_an_id_outside_the_bounded_context():
    # "far_away" is a real node in make_world() but NOT linked to "village"
    # (deliberately, so build_batch_context's bounded slice excludes it) --
    # a reply naming it anyway must not leak into the result.
    registry = make_full_registry([], [], [], flavor_responses=[
        flavor_response(
            ("village", "Woodsmoke drifts over the rooftops."),
            ("far_away", "should never appear -- not in the bounded context"),
        ),
    ])
    state = make_state(registry)

    lines = run_flavor(registry, build_batch_context(state))

    assert lines == {"village": "Woodsmoke drifts over the rooftops."}


def test_run_flavor_drops_an_empty_text_line():
    registry = make_full_registry([], [], [], flavor_responses=[flavor_response(("village", "   "))])
    state = make_state(registry)

    lines = run_flavor(registry, build_batch_context(state))

    assert lines == {}


def test_flavor_schema_requires_lines():
    assert FLAVOR_SCHEMA["required"] == ["lines"]


# -- pipeline.run_batch: ambient flavor (Chunk C) ---------------------------

def test_run_batch_populates_node_flavor():
    registry = make_full_registry(
        [GOOD_INTENT],
        [situation_dict("sit_responsive"), situation_dict("sit_world")],
        [quest_dict("quest_responsive"), quest_dict("quest_world")],
        flavor_responses=[flavor_response(("village", "Woodsmoke drifts over the rooftops."))],
    )
    state = make_state(registry)

    run_batch(state, registry)

    assert state.world.node_flavor == {"village": "Woodsmoke drifts over the rooftops."}


def test_run_batch_leaves_node_flavor_untouched_when_flavor_role_is_unconfigured():
    registry = make_full_registry(
        [GOOD_INTENT],
        [situation_dict("sit_responsive"), situation_dict("sit_world")],
        [quest_dict("quest_responsive"), quest_dict("quest_world")],
    )
    state = make_state(registry)

    run_batch(state, registry)

    assert state.world.node_flavor == {}


def test_run_batch_still_commits_quests_when_flavor_generation_fails():
    registry = make_full_registry(
        [GOOD_INTENT],
        [situation_dict("sit_responsive"), situation_dict("sit_world")],
        [quest_dict("quest_responsive"), quest_dict("quest_world")],
        flavor_responses=[],  # empty queue -- the flavor call fails
    )
    state = make_state(registry)

    intent = run_batch(state, registry)

    assert intent == DirectorIntent.from_dict(GOOD_INTENT)
    assert {item.id for item in state.world.content_pool} == {"quest_responsive", "quest_world"}
    assert state.world.node_flavor == {}


def test_run_batch_updates_rather_than_replaces_existing_node_flavor():
    registry = make_full_registry(
        [GOOD_INTENT],
        [situation_dict("sit_responsive"), situation_dict("sit_world")],
        [quest_dict("quest_responsive"), quest_dict("quest_world")],
        flavor_responses=[flavor_response(("market", "Stalls creak under the weight of the harvest."))],
    )
    state = make_state(registry)
    state.world.node_flavor["village"] = "An older line from a previous batch."

    run_batch(state, registry)

    assert state.world.node_flavor == {
        "village": "An older line from a previous batch.",
        "market": "Stalls creak under the weight of the harvest.",
    }


# -- Emergent-role biasing: stream-skip frequency (Step 7 Chunk D) ----------

def test_should_run_stream_true_at_or_above_the_threshold():
    intent = DirectorIntent(
        responsive_weight=STREAM_SKIP_THRESHOLD, world_driven_weight=1.0,
        pressure_level=0, salient_threads=[],
    )
    assert _should_run_stream(intent, "responsive") is True


def test_should_run_stream_false_below_the_threshold():
    intent = DirectorIntent(
        responsive_weight=STREAM_SKIP_THRESHOLD - 0.01, world_driven_weight=1.0,
        pressure_level=0, salient_threads=[],
    )
    assert _should_run_stream(intent, "responsive") is False


def test_run_batch_skips_the_responsive_stream_when_its_weight_is_lopsidedly_low():
    registry = make_full_registry(
        [RESPONSIVE_SKIPPED_INTENT],
        [situation_dict("sit_world")],  # only ONE queued -- responsive must never be attempted
        [quest_dict("quest_world")],
    )
    state = make_state(registry)

    intent = run_batch(state, registry)

    assert intent == DirectorIntent.from_dict(RESPONSIVE_SKIPPED_INTENT)
    assert {item.id for item in state.world.content_pool} == {"quest_world"}
    story_client = registry._explicit_clients["story_mock"]
    assert story_client.call_count == 1  # only world_driven's call happened


def test_run_batch_skips_the_world_driven_stream_when_its_weight_is_lopsidedly_low():
    registry = make_full_registry(
        [WORLD_DRIVEN_SKIPPED_INTENT],
        [situation_dict("sit_responsive")],  # only ONE queued -- world_driven must never be attempted
        [quest_dict("quest_responsive")],
    )
    state = make_state(registry)

    run_batch(state, registry)

    assert {item.id for item in state.world.content_pool} == {"quest_responsive"}
    story_client = registry._explicit_clients["story_mock"]
    assert story_client.call_count == 1  # only responsive's call happened


def test_run_batch_still_runs_both_streams_when_neither_weight_is_lopsided():
    # GOOD_INTENT (0.6/0.4) -- regression guard: Chunk D must not have
    # changed the balanced-weights case any of the pre-existing tests rely
    # on, so this is a direct, explicit assertion of that in one place.
    registry = make_full_registry(
        [GOOD_INTENT],
        [situation_dict("sit_responsive"), situation_dict("sit_world")],
        [quest_dict("quest_responsive"), quest_dict("quest_world")],
    )
    state = make_state(registry)

    run_batch(state, registry)

    assert {item.id for item in state.world.content_pool} == {"quest_responsive", "quest_world"}


# -- Emergent-role biasing: tone (Step 7 Chunk D) ---------------------------

def test_story_system_prompt_mentions_derived_role_hint():
    assert "derived_role_hint" in STORY_SYSTEM_PROMPT


def test_quest_system_prompt_mentions_derived_role_hint():
    assert "derived_role_hint" in QUEST_SYSTEM_PROMPT


def test_flavor_system_prompt_mentions_derived_role_hint():
    assert "derived_role_hint" in FLAVOR_SYSTEM_PROMPT


# -- Quest prompt documents each RequirementKind's target shape ------------
# Regression coverage for the fix noted in updates.md's "Open TODOs": Gemini
# kept emitting malformed requirement targets (e.g. NODE_STATE with no
# node_id) because the prompt only ever named the legal `kind` values, never
# each kind's required `target` keys.

def test_quest_system_prompt_mentions_faction_standing_delta():
    assert "faction_standing_delta" in QUEST_SYSTEM_PROMPT
    assert "known_factions" in QUEST_SYSTEM_PROMPT


def test_quest_schema_declares_faction_standing_delta_as_optional():
    assert "faction_standing_delta" not in QUEST_SCHEMA["required"]
    assert QUEST_SCHEMA["properties"]["faction_standing_delta"]["properties"]["tiers"] == {"type": "integer"}


def test_quest_system_prompt_documents_every_requirement_kinds_target_shape():
    for kind in RequirementKind:
        assert kind.value in QUEST_SYSTEM_PROMPT

    # Spot-check a couple of the actual key names, not just the kind names,
    # so this can't pass by accident just because _REQUIREMENT_KINDS already
    # lists every kind.value elsewhere in the prompt.
    assert "node_id" in QUEST_SYSTEM_PROMPT
    assert "faction_id" in QUEST_SYSTEM_PROMPT
    assert "tier" in QUEST_SYSTEM_PROMPT


def test_run_flavor_includes_the_player_role_hint_in_its_payload():
    state = make_state()
    state.player.behavior.trade_actions = 10.0
    context = build_batch_context(state)
    spy = SpyClient({"lines": []})
    registry = LLMRegistry(GenerationConfig(roles={"flavor": [ProviderSpec(provider="spy")]}), extra_clients={"spy": spy})

    run_flavor(registry, context)

    sent = json.loads(spy.last_user)
    assert sent["player_role_hint"] == context["player"]["derived_role_hint"]
