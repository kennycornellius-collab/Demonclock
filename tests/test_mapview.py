from demonclock.clock import Clock
from demonclock.knowledge import observe_node
from demonclock.mapview import render
from demonclock.models import Node
from demonclock.player import new_player
from demonclock.state import GameState
from demonclock.world import World


def make_state(location_id: str = "village") -> GameState:
    world = World()
    player = new_player(name="Hero", location_id=location_id)
    return GameState(world=world, player=player, clock=Clock())


def observe_all(state: GameState) -> None:
    for node in state.world.nodes.values():
        observe_node(state.player.beliefs, node, state.clock.current_day)


def test_render_returns_none_with_no_known_nodes_at_all():
    state = make_state()
    assert render(state, {}) is None


def test_render_returns_none_with_only_one_known_node():
    state = make_state()
    state.world.add_node(Node(id="village", name="Village"))
    observe_all(state)
    assert render(state, {"village": "1"}) is None


def test_render_draws_an_l_shaped_layout_matching_the_seeded_starter_graph():
    state = make_state()
    state.world.add_node(Node(id="village", name="Village"))
    state.world.add_node(Node(id="market", name="Market"))
    state.world.add_node(Node(id="road", name="Road"))
    state.world.add_node(Node(id="wilds", name="Wilds"))
    state.world.add_link("village", "market", "east", travel_days=1)
    state.world.add_link("village", "road", "north", travel_days=1)
    state.world.add_link("road", "wilds", "north", travel_days=2)
    observe_all(state)

    out = render(state, {"village": "1", "market": "2", "road": "3", "wilds": "4"})

    assert out == (
        " 4\n"
        " |\n"
        " 3\n"
        " |\n"
        " 1   --  2"
    )


def test_render_draws_a_horizontal_connector_only_when_a_real_link_exists():
    state = make_state()
    state.world.add_node(Node(id="village", name="Village"))
    state.world.add_node(Node(id="market", name="Market"))
    state.world.add_link("village", "market", "east", travel_days=1)
    observe_all(state)

    out = render(state, {"village": "1", "market": "2"})

    assert out == " 1   --  2"


def test_render_lists_a_node_only_reachable_via_a_non_compass_direction_as_a_footnote():
    state = make_state()
    state.world.add_node(Node(id="village", name="Village"))
    state.world.add_node(Node(id="market", name="Market"))
    state.world.add_node(Node(id="tower", name="Sky Tower"))
    state.world.add_link("village", "market", "east", travel_days=1)
    state.world.add_link("village", "tower", "up", travel_days=1)
    observe_all(state)

    out = render(state, {"village": "1", "market": "2", "tower": "3"})

    assert "Sky Tower" in out
    assert "no direct compass route shown" in out
    assert "3" not in out.splitlines()[0]  # not placed on the grid itself


def test_render_only_shows_nodes_the_player_actually_believes_in():
    state = make_state()
    state.world.add_node(Node(id="village", name="Village"))
    state.world.add_node(Node(id="market", name="Market"))
    state.world.add_node(Node(id="secret", name="Undiscovered Place"))
    state.world.add_link("village", "market", "east", travel_days=1)
    state.world.add_link("market", "secret", "east", travel_days=1)
    # Only observe village/market -- "secret" is real world content the
    # player has never actually seen.
    observe_node(state.player.beliefs, state.world.nodes["village"], 0)
    observe_node(state.player.beliefs, state.world.nodes["market"], 0)

    out = render(state, {"village": "1", "market": "2"})

    assert "Undiscovered Place" not in out


def test_render_starts_from_the_players_current_location():
    state = make_state(location_id="market")
    state.world.add_node(Node(id="village", name="Village"))
    state.world.add_node(Node(id="market", name="Market"))
    state.world.add_link("village", "market", "east", travel_days=1)
    observe_all(state)

    # Regardless of which node BFS starts from, both should still place
    # relative to each other and produce the same connected shape.
    out = render(state, {"village": "1", "market": "2"})
    assert out == " 1   --  2"
