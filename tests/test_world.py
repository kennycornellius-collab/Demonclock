import pytest

from demonclock.models import Node
from demonclock.world import World, WorldError


def make_world(*ids: str) -> World:
    world = World()
    for node_id in ids:
        world.add_node(Node(id=node_id, name=node_id.title()))
    return world


def test_add_link_creates_reverse_row_automatically():
    world = make_world("village", "market")
    world.add_link("village", "market", "north", travel_days=2)

    forward = world.get_link("village", "market")
    reverse = world.get_link("market", "village")

    assert forward is not None and forward.direction == "north" and forward.travel_days == 2
    assert reverse is not None and reverse.direction == "south" and reverse.travel_days == 2


def test_one_way_link_suppresses_reverse():
    world = make_world("cliff_top", "ravine_floor")
    world.add_link("cliff_top", "ravine_floor", "down", travel_days=1, one_way=True)

    assert world.get_link("cliff_top", "ravine_floor") is not None
    assert world.get_link("ravine_floor", "cliff_top") is None


def test_add_link_unknown_direction_requires_one_way():
    world = make_world("a", "b")
    with pytest.raises(WorldError):
        world.add_link("a", "b", "sideways", travel_days=1)

    # explicit one_way is allowed for a direction with no known opposite
    world.add_link("a", "b", "sideways", travel_days=1, one_way=True)
    assert world.get_link("a", "b") is not None


def test_block_link_flips_both_rows_by_default():
    world = make_world("village", "market")
    world.add_link("village", "market", "north", travel_days=1)

    world.block_link("village", "market", reason="burned_bridge")

    assert world.get_link("village", "market").status == "blocked"
    assert world.get_link("village", "market").block_reason == "burned_bridge"
    assert world.get_link("market", "village").status == "blocked"
    assert world.get_link("market", "village").block_reason == "burned_bridge"


def test_block_link_directional_only_flips_one_row():
    world = make_world("ridge", "valley")
    world.add_link("ridge", "valley", "down", travel_days=1)

    world.block_link("valley", "ridge", reason="rockslide", directional_block=True)

    assert world.get_link("valley", "ridge").status == "blocked"
    assert world.get_link("ridge", "valley").status == "open"


def test_unblock_link_flips_both_rows_by_default():
    world = make_world("village", "market")
    world.add_link("village", "market", "north", travel_days=1)
    world.block_link("village", "market", reason="snow")

    world.unblock_link("village", "market")

    assert world.get_link("village", "market").status == "open"
    assert world.get_link("market", "village").status == "open"


def test_shortest_path_sums_travel_days_not_hops():
    world = make_world("a", "b", "c", "d")
    world.add_link("a", "b", "north", travel_days=1)
    world.add_link("b", "d", "east", travel_days=1)
    world.add_link("a", "c", "east", travel_days=1)
    world.add_link("c", "d", "north", travel_days=1)
    # a->b->d costs 2, a->c->d costs 2 too; add a slow direct-ish detour to disambiguate
    world.add_link("a", "d", "up", travel_days=10, one_way=True)

    route = world.shortest_path("a", "d")

    assert route is not None
    assert route.total_days == 2
    assert [link.to_id for link in route.links] in (["b", "d"], ["c", "d"])


def test_shortest_path_routes_around_blocked_link():
    world = make_world("a", "b", "c")
    world.add_link("a", "b", "north", travel_days=1)
    world.add_link("a", "c", "east", travel_days=5)
    world.add_link("c", "b", "north", travel_days=1)

    world.block_link("a", "b", reason="invasion")

    route = world.shortest_path("a", "b")

    assert route is not None
    assert route.total_days == 6
    assert [link.to_id for link in route.links] == ["c", "b"]


def test_shortest_path_returns_none_when_unreachable():
    world = make_world("a", "b")
    route = world.shortest_path("a", "b")
    assert route is None


def test_shortest_path_same_node_is_free():
    world = make_world("a")
    route = world.shortest_path("a", "a")
    assert route is not None
    assert route.total_days == 0
    assert route.links == []
