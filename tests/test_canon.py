from demonclock.canon import (
    PreconditionManifest,
    Requirement,
    RequirementKind,
    check_manifest,
)
from demonclock.clock import Clock
from demonclock.models import Node
from demonclock.player import add_item, new_player
from demonclock.skills import BASIC_ATTACK
from demonclock.state import GameState
from demonclock.world import World


def make_state() -> GameState:
    world = World()
    world.add_node(Node(id="a", name="A", state="peaceful"))
    world.add_node(Node(id="b", name="B", state="occupied"))
    world.add_link("a", "b", "north", travel_days=1)
    player = new_player(name="Hero", location_id="a")
    return GameState(world=world, player=player, clock=Clock())


def check(state: GameState, req: Requirement) -> bool:
    return check_manifest(state, PreconditionManifest([req])).passed


# -- NODE_STATE ---------------------------------------------------------

def test_node_state_passes_when_matching():
    state = make_state()
    assert check(state, Requirement(RequirementKind.NODE_STATE, {"node_id": "a", "state": "peaceful"}))


def test_node_state_fails_when_mismatched():
    state = make_state()
    assert not check(state, Requirement(RequirementKind.NODE_STATE, {"node_id": "a", "state": "occupied"}))


def test_node_state_fails_gracefully_for_an_unknown_node():
    state = make_state()
    result = check_manifest(state, PreconditionManifest(
        [Requirement(RequirementKind.NODE_STATE, {"node_id": "nowhere", "state": "peaceful"})]
    ))
    assert not result.passed
    assert "unknown node" in result.failures[0].reason


# -- LINK_STATUS ----------------------------------------------------------

def test_link_status_passes_when_matching():
    state = make_state()
    assert check(state, Requirement(RequirementKind.LINK_STATUS, {"from_id": "a", "to_id": "b", "status": "open"}))


def test_link_status_fails_when_mismatched():
    state = make_state()
    state.world.block_link("a", "b", reason="snow")
    assert not check(state, Requirement(RequirementKind.LINK_STATUS, {"from_id": "a", "to_id": "b", "status": "open"}))


def test_link_status_fails_gracefully_for_an_unknown_link():
    state = make_state()
    state.world.add_node(Node(id="c", name="C"))  # unlinked to anything
    result = check_manifest(state, PreconditionManifest(
        [Requirement(RequirementKind.LINK_STATUS, {"from_id": "a", "to_id": "c", "status": "open"})]
    ))
    assert not result.passed
    assert "unknown link" in result.failures[0].reason


# -- PLAYER_HAS_ITEM ------------------------------------------------------

def test_player_has_item_passes_when_expected_true_and_item_present():
    state = make_state()
    add_item(state.player, "amulet", "Tarnished Amulet")
    assert check(state, Requirement(RequirementKind.PLAYER_HAS_ITEM, {"item_id": "amulet", "expected": True}))


def test_player_has_item_passes_when_expected_false_and_item_absent():
    state = make_state()
    assert check(state, Requirement(RequirementKind.PLAYER_HAS_ITEM, {"item_id": "amulet", "expected": False}))


def test_player_has_item_fails_when_expected_false_but_item_present():
    state = make_state()
    add_item(state.player, "amulet", "Tarnished Amulet")
    assert not check(state, Requirement(RequirementKind.PLAYER_HAS_ITEM, {"item_id": "amulet", "expected": False}))


# -- PLAYER_HAS_SKILL -------------------------------------------------------

def test_player_has_skill_passes_for_a_starter_skill():
    state = make_state()
    known_id = state.player.skills[0].id
    assert check(state, Requirement(RequirementKind.PLAYER_HAS_SKILL, {"skill_id": known_id, "expected": True}))


def test_player_has_skill_fails_for_an_unlearned_skill():
    state = make_state()
    assert not check(state, Requirement(RequirementKind.PLAYER_HAS_SKILL, {"skill_id": BASIC_ATTACK.id, "expected": True}))


# -- PLAYER_GOLD_AT_LEAST -----------------------------------------------

def test_player_gold_at_least_passes_when_sufficient():
    state = make_state()
    state.player.gold = 50
    assert check(state, Requirement(RequirementKind.PLAYER_GOLD_AT_LEAST, {"amount": 50}))


def test_player_gold_at_least_fails_when_insufficient():
    state = make_state()
    state.player.gold = 10
    assert not check(state, Requirement(RequirementKind.PLAYER_GOLD_AT_LEAST, {"amount": 50}))


# -- PLAYER_NOT_CAPTURED --------------------------------------------------

def test_player_not_captured_passes_by_default():
    state = make_state()
    assert check(state, Requirement(RequirementKind.PLAYER_NOT_CAPTURED, {}))


def test_player_not_captured_fails_while_captured():
    state = make_state()
    state.player.captured = True
    assert not check(state, Requirement(RequirementKind.PLAYER_NOT_CAPTURED, {}))


# -- CheckResult / check_manifest ------------------------------------------

def test_check_manifest_passes_only_when_every_requirement_passes():
    state = make_state()
    manifest = PreconditionManifest([
        Requirement(RequirementKind.NODE_STATE, {"node_id": "a", "state": "peaceful"}),
        Requirement(RequirementKind.PLAYER_NOT_CAPTURED, {}),
    ])
    assert check_manifest(state, manifest).passed


def test_check_manifest_failures_lists_only_the_failed_requirements():
    state = make_state()
    manifest = PreconditionManifest([
        Requirement(RequirementKind.NODE_STATE, {"node_id": "a", "state": "peaceful"}),  # passes
        Requirement(RequirementKind.NODE_STATE, {"node_id": "b", "state": "peaceful"}),  # fails, b is occupied
    ])
    result = check_manifest(state, manifest)
    assert not result.passed
    assert len(result.failures) == 1
    assert result.failures[0].requirement.target["node_id"] == "b"


def test_check_manifest_with_no_requirements_trivially_passes():
    state = make_state()
    assert check_manifest(state, PreconditionManifest([])).passed


# -- serialization ----------------------------------------------------------

def test_requirement_round_trips_through_to_dict_and_from_dict():
    req = Requirement(RequirementKind.PLAYER_HAS_ITEM, {"item_id": "amulet", "expected": True})
    assert Requirement.from_dict(req.to_dict()) == req


def test_manifest_round_trips_through_to_dict_and_from_dict():
    manifest = PreconditionManifest([
        Requirement(RequirementKind.NODE_STATE, {"node_id": "a", "state": "peaceful"}),
        Requirement(RequirementKind.PLAYER_GOLD_AT_LEAST, {"amount": 10}),
    ])
    assert PreconditionManifest.from_dict(manifest.to_dict()) == manifest
