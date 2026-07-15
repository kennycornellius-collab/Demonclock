from demonclock.actions import resolve
from demonclock.clock import Clock
from demonclock.parser import parse
from demonclock.player import new_player
from demonclock.seed import new_default_world
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


def test_unrecognized_action_is_not_ok():
    outcome = resolve(parse("xyzzy"), make_state())
    assert not outcome.ok
