from demonclock.actions import resolve
from demonclock.clock import Clock
from demonclock.combat import run_combat
from demonclock.enemies import make_enemy
from demonclock.events import EventKind, ScheduledEvent
from demonclock.parser import parse
from demonclock.player import new_player
from demonclock.seed import new_default_world
from demonclock.skills import BASIC_ATTACK
from demonclock.state import GameState


def make_state() -> GameState:
    world = new_default_world()
    player = new_player(name="Hero", location_id="village")
    return GameState(world=world, player=player, clock=Clock())


def test_move_updates_location_and_advances_clock():
    state = make_state()
    outcome = resolve(parse("go east"), state)
    assert outcome.ok
    assert state.player.location_id == "market"
    assert state.clock.current_day == 1


def test_move_blocked_direction_gives_reason():
    state = make_state()
    state.world.block_link("village", "market", reason="flooded")

    outcome = resolve(parse("go east"), state)

    assert not outcome.ok
    assert "flooded" in outcome.message
    assert state.player.location_id == "village"


def test_move_unknown_direction():
    outcome = resolve(parse("go south"), make_state())
    assert not outcome.ok


def test_rest_advances_clock_and_heals():
    state = make_state()
    state.player.hp = 10
    outcome = resolve(parse("rest"), state)
    assert state.clock.current_day == 1
    assert state.player.hp > 10
    assert outcome.ok


def test_look_lists_open_exits():
    outcome = resolve(parse("look"), make_state())
    assert "Millhaven Village" in outcome.message
    assert "east" in outcome.message


def test_look_shows_prices_at_a_node_that_has_them():
    state = make_state()
    state.player.location_id = "market"

    outcome = resolve(parse("look"), state)

    assert "Prices:" in outcome.message
    assert "grain 10g" in outcome.message


def test_look_omits_prices_segment_where_none_are_tracked():
    outcome = resolve(parse("look"), make_state())  # village has no tracked prices
    assert "Prices:" not in outcome.message


def test_unrecognized_action_is_not_ok():
    outcome = resolve(parse("xyzzy"), make_state())
    assert not outcome.ok


def test_resting_across_a_scheduled_event_fires_it_and_surfaces_narration():
    state = make_state()
    state.world.schedule_event(ScheduledEvent(
        due_day=1, kind=EventKind.BLOCK_LINK,
        payload={"from_id": "village", "to_id": "market", "reason": "flooded"},
        description="The river floods the market road.",
    ))

    outcome = resolve(parse("rest"), state)

    assert "The river floods the market road." in outcome.message
    assert state.world.get_link("village", "market").status == "blocked"


def test_move_across_the_seeded_blizzard_blocks_the_pass():
    state = make_state()
    state.player.location_id = "road"

    outcome = resolve(parse("go north"), state)  # road -> wilds, 2 days, crosses day-4 due date... not yet

    # A single 2-day hop from day 0 only reaches day 2; blizzard is due day 4.
    assert state.clock.current_day == 2
    assert state.world.get_link("road", "wilds").status == "open"
    assert outcome.ok


def test_move_records_the_destination_in_recent_locations():
    state = make_state()
    resolve(parse("go east"), state)
    assert state.player.behavior.recent_locations == ["market"]


def test_inventory_shows_a_derived_role_hint():
    outcome = resolve(parse("inventory"), make_state())
    assert "You seem: still finding their way." in outcome.message


def test_combat_does_not_tick_the_sim():
    state = make_state()
    events_before = len(state.world.scheduled_events)
    state.world.schedule_event(ScheduledEvent(
        due_day=0, kind=EventKind.SET_NODE_STATE,
        payload={"node_id": "village", "state": "occupied"},
    ))

    run_combat(state.player, make_enemy("bramblewood_wolf"), choose_action=lambda *_: BASIC_ATTACK)

    assert state.clock.current_day == 0
    assert state.world.nodes["village"].state == "peaceful"
    assert len(state.world.scheduled_events) == events_before + 1  # never fired
