"""Step 6 Chunk A: the push newspaper. Reuses rumors.rumors_reaching (Step 3
Stage 4) unchanged -- these tests only exercise the before/after diff and
formatting this module adds on top."""
from demonclock.events import EventKind
from demonclock.history import record
from demonclock.models import Node
from demonclock.newspaper import format_newspaper, leaked_since
from demonclock.world import World


def make_world(*ids: str) -> World:
    world = World()
    for node_id in ids:
        world.add_node(Node(id=node_id, name=node_id.title()))
    return world


def test_leaked_since_is_empty_when_nothing_newly_reaches():
    world = make_world("a", "b")
    world.add_link("a", "b", "north", travel_days=1)
    # Already reaching by day 5 -- resting from day 10 to day 11 shouldn't
    # "re-announce" old news.
    record(world.event_log, day=0, node_id="a", kind=EventKind.SET_NODE_STATE, description="A falls.")

    assert leaked_since(world, "b", day_before=10, day_after=11) == []


def test_leaked_since_returns_exactly_the_newly_reachable_rumor():
    world = make_world("a", "b")
    world.add_link("a", "b", "north", travel_days=1)
    record(world.event_log, day=10, node_id="a", kind=EventKind.SET_NODE_STATE, description="A falls.")

    # Not yet reaching at day 10 (0 elapsed, needs >= 1 hop's worth); resting
    # one day crosses the threshold.
    leaked = leaked_since(world, "b", day_before=10, day_after=11)

    assert len(leaked) == 1
    assert leaked[0].origin_node_id == "a"
    assert leaked[0].day_originated == 10


def test_leaked_since_excludes_a_rumor_already_reaching_before_resting():
    world = make_world("a", "b")
    world.add_link("a", "b", "north", travel_days=1)
    record(world.event_log, day=0, node_id="a", kind=EventKind.SET_NODE_STATE, description="A falls.")

    # Already well within reach at day 10 -- resting to day 11 shouldn't
    # re-surface it as "new."
    assert leaked_since(world, "b", day_before=10, day_after=11) == []


def test_leaked_since_can_surface_multiple_newly_reachable_rumors_in_one_rest():
    world = make_world("a", "b", "c")
    world.add_link("a", "b", "north", travel_days=1)
    world.add_link("b", "c", "north", travel_days=1)
    record(world.event_log, day=10, node_id="b", kind=EventKind.SET_NODE_STATE, description="B event (near).")
    record(world.event_log, day=10, node_id="c", kind=EventKind.SET_NODE_STATE, description="C event (far).")

    # From "a": b is 1 hop, c is 2 hops. Resting from day 10 to day 12 crosses
    # both thresholds in a single rest.
    leaked = leaked_since(world, "a", day_before=10, day_after=12)

    assert {rumor.origin_node_id for rumor in leaked} == {"b", "c"}


def test_leaked_since_excludes_a_rumor_about_the_players_own_node():
    world = make_world("a")
    record(world.event_log, day=5, node_id="a", kind=EventKind.SET_NODE_STATE, description="A falls.")

    assert leaked_since(world, "a", day_before=5, day_after=100) == []


def test_format_newspaper_is_none_for_an_empty_list():
    assert format_newspaper([]) is None


def test_format_newspaper_includes_confidence_and_text_for_each_rumor():
    world = make_world("a", "b")
    world.add_link("a", "b", "north", travel_days=1)
    record(world.event_log, day=0, node_id="a", kind=EventKind.SET_NODE_STATE, description="A falls.")
    leaked = leaked_since(world, "b", day_before=0, day_after=1)

    text = format_newspaper(leaked)

    assert text is not None
    assert "A falls." in text
    assert "%" in text  # confidence rendered as a percentage
