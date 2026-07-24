from demonclock.events import EventKind
from demonclock.history import record
from demonclock.models import Node
from demonclock.rumors import MAX_RUMOR_AGE_DAYS, rumors_reaching
from demonclock.world import World


def make_world(*ids: str) -> World:
    world = World()
    for node_id in ids:
        world.add_node(Node(id=node_id, name=node_id.title()))
    return world


def test_rumors_reaching_is_empty_with_no_logged_events():
    world = make_world("a", "b")
    world.add_link("a", "b", "north", travel_days=1)
    assert rumors_reaching(world, "b", current_day=10) == []


def test_a_rumor_is_not_available_before_enough_days_have_elapsed():
    world = make_world("a", "b")
    world.add_link("a", "b", "north", travel_days=1)
    record(world.event_log, day=10, node_id="a", kind=EventKind.SET_NODE_STATE, description="A falls.")

    assert rumors_reaching(world, "b", current_day=10) == []  # 0 days elapsed, needs >= 1


def test_a_rumor_reaches_a_neighbor_after_one_day():
    world = make_world("a", "b")
    world.add_link("a", "b", "north", travel_days=1)
    record(world.event_log, day=10, node_id="a", kind=EventKind.SET_NODE_STATE, description="A falls.")

    rumors = rumors_reaching(world, "b", current_day=11)

    assert len(rumors) == 1
    assert rumors[0].origin_node_id == "a"
    assert rumors[0].hops == 1
    assert rumors[0].day_originated == 10


def test_a_rumor_about_the_querying_nodes_own_event_is_excluded():
    world = make_world("a")
    record(world.event_log, day=5, node_id="a", kind=EventKind.SET_NODE_STATE, description="A falls.")

    assert rumors_reaching(world, "a", current_day=20) == []


def test_a_blocked_link_stops_rumor_propagation_no_matter_how_much_time_passes():
    world = make_world("a", "b", "c")
    world.add_link("a", "b", "north", travel_days=1)
    world.add_link("b", "c", "north", travel_days=1)
    world.block_link("b", "c", reason="enemy")
    record(world.event_log, day=0, node_id="a", kind=EventKind.SET_NODE_STATE, description="A falls.")

    assert rumors_reaching(world, "c", current_day=1000) == []


def test_a_later_link_closure_suppresses_a_rumor_even_if_it_couldve_already_arrived():
    # Documented simplification: propagation is checked against the CURRENT
    # topology, not a historical replay. A now-sealed border reads as "this
    # region went quiet" (the intended SPEC.md §10 signal) even for news
    # that, strictly, had time to slip through before the link closed.
    world = make_world("a", "b")
    world.add_link("a", "b", "north", travel_days=1)
    record(world.event_log, day=0, node_id="a", kind=EventKind.SET_NODE_STATE, description="A falls.")

    assert rumors_reaching(world, "b", current_day=5) != []  # link still open: reachable

    world.block_link("a", "b", reason="enemy")

    assert rumors_reaching(world, "b", current_day=6) == []  # now sealed: goes quiet


def test_hop_distance_ignores_travel_days_and_uses_the_shortest_hop_path():
    world = make_world("a", "b", "c")
    world.add_link("a", "b", "north", travel_days=1)
    world.add_link("b", "c", "north", travel_days=1)
    world.add_link("a", "c", "east", travel_days=100)  # direct link, but a huge travel_days
    record(world.event_log, day=0, node_id="c", kind=EventKind.SET_NODE_STATE, description="C event.")

    rumors = rumors_reaching(world, "a", current_day=1)  # only 1 day elapsed

    assert len(rumors) == 1
    assert rumors[0].hops == 1  # reached via the direct 1-hop link despite its huge travel_days


def test_an_event_older_than_the_recency_cutoff_is_excluded():
    world = make_world("a", "b")
    world.add_link("a", "b", "north", travel_days=1)
    record(world.event_log, day=0, node_id="a", kind=EventKind.SET_NODE_STATE, description="A falls.")

    just_within = rumors_reaching(world, "b", current_day=MAX_RUMOR_AGE_DAYS)
    just_beyond = rumors_reaching(world, "b", current_day=MAX_RUMOR_AGE_DAYS + 1)

    assert len(just_within) == 1  # hops=1 already satisfied ages ago; still within the recency window
    assert just_beyond == []  # same event, one day past the cutoff -- now old news


def test_recency_cutoff_does_not_exclude_a_recent_event_behind_an_older_one():
    world = make_world("a", "b")
    world.add_link("a", "b", "north", travel_days=1)
    record(world.event_log, day=0, node_id="a", kind=EventKind.SET_NODE_STATE, description="Old event.")
    record(world.event_log, day=MAX_RUMOR_AGE_DAYS + 1, node_id="a", kind=EventKind.SET_NODE_STATE, description="Recent event.")

    heard = rumors_reaching(world, "b", current_day=MAX_RUMOR_AGE_DAYS + 10)

    assert len(heard) == 1  # the old entry aged out, the recent one didn't
    assert heard[0].day_originated == MAX_RUMOR_AGE_DAYS + 1


def test_confidence_decays_with_hop_distance():
    world = make_world("a", "b", "c")
    world.add_link("a", "b", "north", travel_days=1)
    world.add_link("b", "c", "north", travel_days=1)
    record(world.event_log, day=0, node_id="a", kind=EventKind.SET_NODE_STATE, description="A falls.")

    near = rumors_reaching(world, "b", current_day=2)[0]
    far = rumors_reaching(world, "c", current_day=2)[0]

    assert far.confidence < near.confidence


def test_distortion_increases_with_hop_distance_and_is_deterministic():
    world = make_world("a", "b", "c")
    world.add_link("a", "b", "north", travel_days=1)
    world.add_link("b", "c", "north", travel_days=1)
    record(world.event_log, day=0, node_id="a", kind=EventKind.SET_NODE_STATE, description="A falls.")

    near = rumors_reaching(world, "b", current_day=2)[0]
    far = rumors_reaching(world, "c", current_day=2)[0]
    far_again = rumors_reaching(world, "c", current_day=2)[0]

    assert near.text != far.text
    assert far_again.text == far.text  # same distance, same event -> identical wording every time


def test_rumors_reaching_sorts_by_hop_distance_ascending():
    world = make_world("a", "b", "c", "d")
    world.add_link("a", "b", "north", travel_days=1)
    world.add_link("b", "c", "north", travel_days=1)
    world.add_link("c", "d", "north", travel_days=1)
    record(world.event_log, day=0, node_id="d", kind=EventKind.SET_NODE_STATE, description="D event (far).")
    record(world.event_log, day=0, node_id="b", kind=EventKind.SET_NODE_STATE, description="B event (near).")

    result = rumors_reaching(world, "a", current_day=10)

    assert [r.hops for r in result] == [1, 3]
