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


def make_linear_world(occupied_id: str = "a") -> World:
    """a - b - c, all links open; `occupied_id` starts occupied, the rest peaceful."""
    world = make_world("a", "b", "c")
    world.add_link("a", "b", "north", travel_days=1)
    world.add_link("b", "c", "north", travel_days=1)
    world.nodes[occupied_id].state = "occupied"
    return world


# -- invasion spread (Stage 2, SPEC.md §3) ---------------------------------

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
