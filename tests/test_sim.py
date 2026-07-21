import pytest

from demonclock.clock import Clock
from demonclock.events import EventKind, ScheduledEvent
from demonclock.models import Node
from demonclock.player import new_player
from demonclock.sim import (
    INVASION_SPREAD_INTERVAL_DAYS,
    PRICE_SHIFT_INTERVAL_DAYS,
    advance_time,
    apply_event,
    tick_day,
)
from demonclock.state import GameState
from demonclock.world import World


def make_world(*ids: str) -> World:
    world = World()
    for node_id in ids:
        world.add_node(Node(id=node_id, name=node_id.title()))
    return world


def make_state(world: World | None = None, day: int = 0) -> GameState:
    world = world if world is not None else make_world("a", "b")
    player = new_player(name="Hero", location_id="a")
    return GameState(world=world, player=player, clock=Clock(current_day=day))


# -- apply_event ------------------------------------------------------------

def test_apply_event_block_link_flips_both_directional_rows():
    world = make_world("a", "b")
    world.add_link("a", "b", "north", travel_days=1)
    state = make_state(world)
    event = ScheduledEvent(due_day=0, kind=EventKind.BLOCK_LINK, payload={"from_id": "a", "to_id": "b", "reason": "snow"})

    log = apply_event(state, event)

    assert world.get_link("a", "b").status == "blocked"
    assert world.get_link("b", "a").status == "blocked"
    assert log


def test_apply_event_unblock_link_reopens_both_rows():
    world = make_world("a", "b")
    world.add_link("a", "b", "north", travel_days=1)
    world.block_link("a", "b", reason="snow")
    state = make_state(world)
    event = ScheduledEvent(due_day=0, kind=EventKind.UNBLOCK_LINK, payload={"from_id": "a", "to_id": "b"})

    apply_event(state, event)

    assert world.get_link("a", "b").status == "open"
    assert world.get_link("b", "a").status == "open"


def test_apply_event_set_node_state_flips_state():
    world = make_world("a")
    state = make_state(world)
    event = ScheduledEvent(due_day=0, kind=EventKind.SET_NODE_STATE, payload={"node_id": "a", "state": "occupied"})

    apply_event(state, event)

    assert world.nodes["a"].state == "occupied"


def test_apply_event_uses_custom_description_when_present():
    world = make_world("a")
    state = make_state(world)
    event = ScheduledEvent(
        due_day=0, kind=EventKind.SET_NODE_STATE,
        payload={"node_id": "a", "state": "ruined"}, description="A dragon razes the village.",
    )

    log = apply_event(state, event)

    assert log == ["A dragon razes the village."]


# -- tick_day -----------------------------------------------------------

def test_tick_day_fires_events_due_today_and_removes_them():
    world = make_world("a")
    state = make_state(world, day=5)
    world.schedule_event(ScheduledEvent(due_day=5, kind=EventKind.SET_NODE_STATE, payload={"node_id": "a", "state": "occupied"}))

    log = tick_day(state)

    assert world.nodes["a"].state == "occupied"
    assert world.scheduled_events == []
    assert log


def test_tick_day_does_not_fire_a_future_event():
    world = make_world("a")
    state = make_state(world, day=5)
    world.schedule_event(ScheduledEvent(due_day=6, kind=EventKind.SET_NODE_STATE, payload={"node_id": "a", "state": "occupied"}))

    log = tick_day(state)

    assert world.nodes["a"].state == "peaceful"
    assert len(world.scheduled_events) == 1
    assert log == []


def test_tick_day_fires_a_past_due_event_instead_of_stranding_it():
    world = make_world("a")
    state = make_state(world, day=10)
    world.schedule_event(ScheduledEvent(due_day=3, kind=EventKind.SET_NODE_STATE, payload={"node_id": "a", "state": "occupied"}))

    log = tick_day(state)

    assert world.nodes["a"].state == "occupied"
    assert log


def test_tick_day_preserves_schedule_order_for_same_day_events():
    world = make_world("a")
    state = make_state(world, day=1)
    world.schedule_event(ScheduledEvent(due_day=1, kind=EventKind.SET_NODE_STATE, payload={"node_id": "a", "state": "first"}))
    world.schedule_event(ScheduledEvent(due_day=1, kind=EventKind.SET_NODE_STATE, payload={"node_id": "a", "state": "second"}))

    tick_day(state)

    assert world.nodes["a"].state == "second"  # applied in order, second overwrites first


# -- advance_time ---------------------------------------------------------

def test_advance_time_ticks_once_per_day_and_advances_clock():
    world = make_world("a")
    state = make_state(world, day=0)

    advance_time(state, 3)

    assert state.clock.current_day == 3


def test_advance_time_fires_all_events_due_within_the_span():
    world = make_world("a")
    state = make_state(world, day=0)
    world.schedule_event(ScheduledEvent(due_day=2, kind=EventKind.SET_NODE_STATE, payload={"node_id": "a", "state": "occupied"}))

    log = advance_time(state, 5)

    assert world.nodes["a"].state == "occupied"
    assert log


def test_advance_time_zero_days_is_a_pure_noop():
    world = make_world("a")
    state = make_state(world, day=0)
    world.schedule_event(ScheduledEvent(due_day=0, kind=EventKind.SET_NODE_STATE, payload={"node_id": "a", "state": "occupied"}))

    log = advance_time(state, 0)

    assert log == []
    assert state.clock.current_day == 0
    assert world.nodes["a"].state == "peaceful"  # never fired — zero elapsed days ticks nothing


def test_advance_time_is_deterministic():
    def make_matchup():
        world = make_world("a")
        world.schedule_event(ScheduledEvent(due_day=2, kind=EventKind.SET_NODE_STATE, payload={"node_id": "a", "state": "occupied"}))
        return make_state(world, day=0)

    log1 = advance_time(make_matchup(), 5)
    log2 = advance_time(make_matchup(), 5)

    assert log1 == log2


def test_advance_time_calls_the_batch_placeholder_exactly_once(monkeypatch):
    import demonclock.sim as sim_module

    calls = []
    monkeypatch.setattr(sim_module, "_run_batch", lambda state: calls.append(state))

    world = make_world("a")
    state = make_state(world, day=0)
    advance_time(state, 12)  # a 12-day journey: 12 ticks, exactly 1 batch (SPEC.md §4/§13)

    assert len(calls) == 1


# -- generation pipeline wiring (Step 5 Chunk B) ---------------------------

def test_run_batch_is_a_noop_with_no_generation_registry():
    # GameState.generation defaults to None (make_state doesn't set it) --
    # must behave exactly like it did before Step 5 existed.
    world = make_world("a")
    state = make_state(world, day=0)
    assert state.generation is None

    log = advance_time(state, 3)  # must not raise

    assert state.clock.current_day == 3
    assert log is not None  # tick narration still flows normally


def test_advance_time_calls_the_director_exactly_once_across_a_multiday_span():
    from demonclock.llm.config import GenerationConfig, ProviderSpec
    from demonclock.llm.providers.mock import MockClient
    from demonclock.llm.registry import LLMRegistry

    good_intent = {
        "responsive_weight": 0.5, "world_driven_weight": 0.5,
        "pressure_level": 0, "salient_threads": [],
    }
    mock_client = MockClient(responses=[good_intent])
    config = GenerationConfig(roles={"director": [ProviderSpec(provider="mock")]})
    registry = LLMRegistry(config, extra_clients={"mock": mock_client})

    world = make_world("a")
    state = make_state(world, day=0)
    state.generation = registry

    advance_time(state, 12)  # many elapsed days -- still exactly one Director call

    assert mock_client.call_count == 1


def make_linear_world(occupied_id: str = "a") -> World:
    """a - b - c, all links open; `occupied_id` starts occupied, the rest peaceful."""
    world = make_world("a", "b", "c")
    world.add_link("a", "b", "north", travel_days=1)
    world.add_link("b", "c", "north", travel_days=1)
    world.nodes[occupied_id].state = "occupied"
    return world


# -- invasion spread (Stage 2, SPEC.md §3) ---------------------------------

def test_apply_event_block_link_appends_a_history_entry():
    world = make_world("a", "b")
    world.add_link("a", "b", "north", travel_days=1)
    state = make_state(world, day=7)
    event = ScheduledEvent(due_day=7, kind=EventKind.BLOCK_LINK, payload={"from_id": "a", "to_id": "b", "reason": "snow"})

    apply_event(state, event)

    assert len(world.event_log) == 1
    entry = world.event_log[0]
    assert entry.day == 7
    assert entry.node_id == "a"
    assert entry.kind is EventKind.BLOCK_LINK
    assert "blocked" in entry.description


def test_apply_event_set_node_state_appends_a_history_entry():
    world = make_world("a")
    state = make_state(world, day=15)
    event = ScheduledEvent(
        due_day=15, kind=EventKind.SET_NODE_STATE, payload={"node_id": "a", "state": "occupied"},
        description="The invasion overruns A.",
    )

    apply_event(state, event)

    entry = world.event_log[0]
    assert entry.day == 15
    assert entry.node_id == "a"
    assert entry.kind is EventKind.SET_NODE_STATE
    assert entry.description == "The invasion overruns A."


def test_apply_event_never_removes_earlier_history_entries():
    world = make_world("a")
    state = make_state(world)
    apply_event(state, ScheduledEvent(due_day=0, kind=EventKind.SET_NODE_STATE, payload={"node_id": "a", "state": "occupied"}))
    apply_event(state, ScheduledEvent(due_day=0, kind=EventKind.SET_NODE_STATE, payload={"node_id": "a", "state": "ruined"}))

    assert len(world.event_log) == 2
    assert [e.description for e in world.event_log] == [
        "A is now occupied.", "A is now ruined.",
    ]


def test_price_shift_does_not_append_to_the_history_log():
    # PRICE_SHIFT has no single node it's "about" — economy.apply_price_shift
    # never recurses through apply_event, so it produces no log entry at all
    # (grain prices are already directly observable via `look`, no rumor
    # needed to learn about them).
    world = make_world("a")
    world.nodes["a"].prices = {"grain": 10}
    state = make_state(world)

    apply_event(state, ScheduledEvent(due_day=0, kind=EventKind.PRICE_SHIFT))

    assert world.event_log == []


def test_apply_event_never_writes_player_belief():
    # SPEC.md §13: belief is never silently overwritten by truth — only an
    # explicit act of observation (actions.py) may write player.beliefs.
    world = make_world("a", "b")
    world.add_link("a", "b", "north", travel_days=1)
    state = make_state(world)  # player starts at "a"
    event = ScheduledEvent(due_day=0, kind=EventKind.SET_NODE_STATE, payload={"node_id": "b", "state": "occupied"})

    apply_event(state, event)

    assert "b" not in state.player.beliefs


def test_invasion_spread_occupies_open_frontier_and_blocks_crossed_link():
    world = make_linear_world()
    state = make_state(world, day=0)
    event = ScheduledEvent(due_day=0, kind=EventKind.INVASION_SPREAD)

    log = apply_event(state, event)

    assert world.nodes["b"].state == "occupied"
    assert world.nodes["c"].state == "peaceful"  # not yet reached — one hop per tick
    assert world.get_link("a", "b").status == "blocked"
    assert world.get_link("a", "b").block_reason == "enemy"
    assert world.get_link("b", "a").status == "blocked"
    assert world.get_link("b", "c").status == "open"  # not crossed yet
    assert any("overruns" in line for line in log)


def test_invasion_spread_appends_history_entries_for_the_conquered_node_and_crossed_link():
    world = make_linear_world()
    state = make_state(world, day=0)

    apply_event(state, ScheduledEvent(due_day=0, kind=EventKind.INVASION_SPREAD))

    kinds = [e.kind for e in world.event_log]
    assert EventKind.SET_NODE_STATE in kinds
    assert EventKind.BLOCK_LINK in kinds
    occupied_entry = next(e for e in world.event_log if e.kind is EventKind.SET_NODE_STATE)
    assert occupied_entry.node_id == "b"
    assert occupied_entry.day == 0
    # the top-level INVASION_SPREAD event itself never gets logged — only its
    # concrete SET_NODE_STATE/BLOCK_LINK sub-events, which actually name a node
    assert all(e.kind is not EventKind.INVASION_SPREAD for e in world.event_log)


def test_invasion_spread_reschedules_next_tick_when_nodes_remain():
    world = make_linear_world()
    state = make_state(world, day=0)

    apply_event(state, ScheduledEvent(due_day=0, kind=EventKind.INVASION_SPREAD))

    assert len(world.scheduled_events) == 1
    next_event = world.scheduled_events[0]
    assert next_event.kind is EventKind.INVASION_SPREAD
    assert next_event.due_day == INVASION_SPREAD_INTERVAL_DAYS


def test_invasion_spread_stalls_behind_a_blockage_but_still_reschedules():
    world = make_linear_world()
    world.block_link("a", "b", reason="flood")
    state = make_state(world, day=0)

    log = apply_event(state, ScheduledEvent(due_day=0, kind=EventKind.INVASION_SPREAD))

    assert log == []
    assert world.nodes["b"].state == "peaceful"
    # Stalled, not given up — SPEC.md §4 frames this as an ambient pressure
    # source, so a temporary blockage must not permanently cancel the chain.
    assert len(world.scheduled_events) == 1
    assert world.scheduled_events[0].kind is EventKind.INVASION_SPREAD


def test_invasion_spread_resumes_once_the_blockage_clears():
    world = make_linear_world()
    world.block_link("a", "b", reason="flood")
    state = make_state(world, day=0)
    apply_event(state, ScheduledEvent(due_day=0, kind=EventKind.INVASION_SPREAD))  # stalls, reschedules for day 5
    retry_day = world.scheduled_events[0].due_day

    world.unblock_link("a", "b")
    state.clock.current_day = retry_day
    log = tick_day(state)

    assert world.nodes["b"].state == "occupied"
    assert log


def test_invasion_spread_stops_rescheduling_once_the_whole_graph_falls():
    world = make_world("a", "b")
    world.add_link("a", "b", "north", travel_days=1)
    world.nodes["a"].state = "occupied"
    state = make_state(world, day=0)

    apply_event(state, ScheduledEvent(due_day=0, kind=EventKind.INVASION_SPREAD))

    assert world.nodes["b"].state == "occupied"
    assert world.scheduled_events == []  # nothing left to conquer, chain ends


def test_invasion_spread_is_deterministic():
    def make_matchup():
        return make_state(make_linear_world(), day=0)

    log1 = advance_time(make_matchup(), 20)
    log2 = advance_time(make_matchup(), 20)

    assert log1 == log2


def test_seeded_invasion_conquers_the_whole_starter_graph_on_schedule():
    from demonclock.seed import new_default_world

    world = new_default_world()
    state = make_state(world, day=0)

    advance_time(state, 26)  # past day 25, the last scheduled conquest

    assert all(node.state == "occupied" for node in world.nodes.values())
    assert world.get_link("wilds", "road").block_reason == "enemy"  # invasion re-blocked it post-blizzard
    assert world.get_link("road", "village").status == "blocked"
    assert world.get_link("village", "market").status == "blocked"
    # blizzard pair + invasion chain fully resolved — only the perpetual
    # PRICE_SHIFT chain (Stage 3) is still queued, which never stops
    assert [e.kind for e in world.scheduled_events] == [EventKind.PRICE_SHIFT]


# -- price shifts (Stage 3, SPEC.md §4/§10) --------------------------------

def test_price_shift_reschedules_indefinitely_even_when_nothing_moved():
    world = make_world("a")
    state = make_state(world, day=0)

    for _ in range(5):
        event = ScheduledEvent(due_day=state.clock.current_day, kind=EventKind.PRICE_SHIFT)
        apply_event(state, event)
        # every fire schedules exactly one more, unlike invasion's finite stop
        assert len(world.scheduled_events) == 1
        next_event = world.scheduled_events.pop()
        state.clock.current_day = next_event.due_day

    assert next_event.kind is EventKind.PRICE_SHIFT
    assert next_event.due_day == PRICE_SHIFT_INTERVAL_DAYS * 5


def test_seeded_price_shift_tracks_the_invasion_approach():
    from demonclock.seed import new_default_world

    world = new_default_world()
    state = make_state(world, day=0)

    advance_time(state, 21)
    assert world.nodes["market"].prices["grain"] == 11  # village fell day 20; first tick after is day 21

    advance_time(state, 3)  # day 24
    assert world.nodes["market"].prices["grain"] == 12

    advance_time(state, 3)  # day 27 — market itself fell day 25, target is now x2.0
    assert world.nodes["market"].prices["grain"] == 13

    advance_time(state, 21)  # day 48 — reaches the x2.0 plateau
    assert world.nodes["market"].prices["grain"] == 20

    advance_time(state, 3)  # day 51 — holds, but still actively ticking
    assert world.nodes["market"].prices["grain"] == 20
    assert any(e.kind is EventKind.PRICE_SHIFT for e in world.scheduled_events)


# -- behavior-profile decay (Stage 4, SPEC.md §5) --------------------------

def test_advance_time_decays_behavior_counters_once_per_elapsed_day():
    state = make_state(day=0)
    state.player.behavior.combat_actions = 10.0

    advance_time(state, 3)

    assert state.player.behavior.combat_actions == pytest.approx(10.0 * (0.97 ** 3))


def test_advance_time_refreshes_gold_trend_from_player_gold():
    state = make_state(day=0)
    state.player.gold = 50

    advance_time(state, 1)

    assert state.player.behavior.gold_trend == "rising"  # started at last_gold=0
    assert state.player.behavior.last_gold == 50


def test_advance_time_zero_days_does_not_decay_behavior():
    state = make_state(day=0)
    state.player.behavior.combat_actions = 5.0

    advance_time(state, 0)

    assert state.player.behavior.combat_actions == 5.0


def test_blizzard_demo_blocks_then_reopens_the_pass():
    from demonclock.seed import new_default_world

    world = new_default_world()
    state = make_state(world, day=0)
    state.player.location_id = "road"

    advance_time(state, 4)
    assert world.get_link("road", "wilds").status == "blocked"
    assert world.get_link("wilds", "road").status == "blocked"

    advance_time(state, 6)  # now day 10, past the day-9 clear
    assert world.get_link("road", "wilds").status == "open"
    assert world.get_link("wilds", "road").status == "open"
