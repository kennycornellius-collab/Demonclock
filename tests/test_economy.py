from demonclock.clock import Clock
from demonclock.economy import BASE_PRICE, apply_price_shift
from demonclock.models import Node
from demonclock.player import new_player
from demonclock.state import GameState
from demonclock.world import World


def make_world(*ids: str) -> World:
    world = World()
    for node_id in ids:
        world.add_node(Node(id=node_id, name=node_id.title()))
    return world


def make_state(world: World) -> GameState:
    player = new_player(name="Hero", location_id="a")
    return GameState(world=world, player=player, clock=Clock())


def test_price_holds_steady_while_safe():
    world = make_world("a", "b")
    world.add_link("a", "b", "north", travel_days=1)
    world.nodes["b"].prices = {"grain": BASE_PRICE["grain"]}
    state = make_state(world)

    log = apply_price_shift(state)

    assert world.nodes["b"].prices["grain"] == BASE_PRICE["grain"]
    assert log == []


def test_price_steps_toward_near_danger_target_when_a_neighbor_is_occupied():
    world = make_world("a", "b")
    world.add_link("a", "b", "north", travel_days=1)
    world.nodes["a"].state = "occupied"
    world.nodes["b"].prices = {"grain": BASE_PRICE["grain"]}
    state = make_state(world)

    log = apply_price_shift(state)

    assert world.nodes["b"].prices["grain"] == BASE_PRICE["grain"] + 1  # one PRICE_STEP toward x1.5, not a jump
    assert any("rise" in line for line in log)


def test_price_steps_toward_occupied_target_when_the_node_itself_is_occupied():
    world = make_world("a")
    world.nodes["a"].state = "occupied"
    world.nodes["a"].prices = {"grain": BASE_PRICE["grain"]}
    state = make_state(world)

    apply_price_shift(state)

    assert world.nodes["a"].prices["grain"] == BASE_PRICE["grain"] + 1  # toward x2.0


def test_price_never_jumps_straight_to_target_it_steps_one_tick_at_a_time():
    world = make_world("a")
    world.nodes["a"].state = "occupied"
    world.nodes["a"].prices = {"grain": BASE_PRICE["grain"]}
    state = make_state(world)

    for _ in range(3):
        apply_price_shift(state)

    assert world.nodes["a"].prices["grain"] == BASE_PRICE["grain"] + 3
    assert world.nodes["a"].prices["grain"] < round(BASE_PRICE["grain"] * 2.0)


def test_price_holds_once_it_reaches_its_target():
    world = make_world("a")
    world.nodes["a"].state = "occupied"
    world.nodes["a"].prices = {"grain": round(BASE_PRICE["grain"] * 2.0)}  # already at target
    state = make_state(world)

    log = apply_price_shift(state)

    assert world.nodes["a"].prices["grain"] == round(BASE_PRICE["grain"] * 2.0)
    assert log == []


def test_nodes_without_tracked_prices_are_untouched():
    world = make_world("a")
    world.nodes["a"].state = "occupied"
    state = make_state(world)

    log = apply_price_shift(state)

    assert world.nodes["a"].prices == {}
    assert log == []


def test_apply_price_shift_is_deterministic():
    def make_matchup():
        world = make_world("a", "b")
        world.add_link("a", "b", "north", travel_days=1)
        world.nodes["a"].state = "occupied"
        world.nodes["b"].prices = {"grain": BASE_PRICE["grain"]}
        return make_state(world)

    log1 = apply_price_shift(make_matchup())
    log2 = apply_price_shift(make_matchup())

    assert log1 == log2
