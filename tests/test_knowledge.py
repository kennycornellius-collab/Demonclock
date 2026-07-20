from demonclock.knowledge import NodeBelief, observe_node
from demonclock.models import Node


def test_observe_node_writes_a_snapshot_of_current_truth():
    beliefs: dict = {}
    node = Node(id="market", name="Market", state="peaceful", tags=["trade-hub"], prices={"grain": 10})

    observe_node(beliefs, node, current_day=5)

    belief = beliefs["market"]
    assert belief.state == "peaceful"
    assert belief.tags == ["trade-hub"]
    assert belief.prices == {"grain": 10}
    assert belief.last_seen_day == 5


def test_observe_node_overwrites_a_stale_belief_with_current_truth():
    beliefs = {"market": NodeBelief(state="peaceful", last_seen_day=1)}
    node = Node(id="market", name="Market", state="occupied")

    observe_node(beliefs, node, current_day=20)

    assert beliefs["market"].state == "occupied"
    assert beliefs["market"].last_seen_day == 20


def test_observe_node_only_touches_the_observed_node():
    beliefs = {"village": NodeBelief(state="peaceful", last_seen_day=1)}
    node = Node(id="market", name="Market", state="peaceful")

    observe_node(beliefs, node, current_day=2)

    assert "village" in beliefs
    assert beliefs["village"].last_seen_day == 1  # untouched


def test_node_belief_round_trips_through_to_dict_and_from_dict():
    belief = NodeBelief(state="occupied", tags=["mountain"], prices={"grain": 15}, last_seen_day=7)
    restored = NodeBelief.from_dict(belief.to_dict())
    assert restored == belief
