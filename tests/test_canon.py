from demonclock.canon import (
    PreconditionManifest,
    Requirement,
    RequirementKind,
    check_manifest,
)
from demonclock.clock import Clock
from demonclock.models import Faction, Node
from demonclock.player import add_item, new_player
from demonclock.skills import BASIC_ATTACK
from demonclock.state import GameState
from demonclock.world import World


def make_state() -> GameState:
    world = World()
    world.add_node(Node(id="a", name="A", state="peaceful"))
    world.add_node(Node(id="b", name="B", state="occupied"))
    world.add_link("a", "b", "north", travel_days=1)
    # Registered so FACTION_STANDING_AT_LEAST's own existence check
    # (canon.py's dangling-reference guard) doesn't reject every test below
    # that references it -- every one of those tests is about the standing
    # COMPARISON, not about testing a hallucinated/unknown faction id (that
    # has its own dedicated test further down).
    world.add_faction(Faction(id="merchants", name="Merchants' Guild"))
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


# -- PLAYER_HAS_ITEM_QUANTITY_AT_LEAST ---------------------------------------

def test_player_has_item_quantity_at_least_passes_when_enough_on_hand():
    state = make_state()
    add_item(state.player, "grain", "Grain", 5)
    req = Requirement(RequirementKind.PLAYER_HAS_ITEM_QUANTITY_AT_LEAST, {"item_id": "grain", "amount": 5})
    assert check(state, req)


def test_player_has_item_quantity_at_least_fails_when_short():
    state = make_state()
    add_item(state.player, "grain", "Grain", 2)
    req = Requirement(RequirementKind.PLAYER_HAS_ITEM_QUANTITY_AT_LEAST, {"item_id": "grain", "amount": 5})
    assert not check(state, req)


def test_player_has_item_quantity_at_least_fails_gracefully_when_item_entirely_absent():
    state = make_state()
    req = Requirement(RequirementKind.PLAYER_HAS_ITEM_QUANTITY_AT_LEAST, {"item_id": "grain", "amount": 1})
    assert not check(state, req)


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


# -- FACTION_STANDING_AT_LEAST (Step 10 Stage 4) -----------------------------

def test_faction_standing_at_least_passes_at_the_default_neutral_tier():
    state = make_state()
    req = Requirement(RequirementKind.FACTION_STANDING_AT_LEAST, {"faction_id": "merchants", "tier": "neutral"})
    assert check(state, req)


def test_faction_standing_at_least_passes_when_recorded_standing_is_higher():
    state = make_state()
    state.player.faction_standing["merchants"] = "allied"
    req = Requirement(RequirementKind.FACTION_STANDING_AT_LEAST, {"faction_id": "merchants", "tier": "friendly"})
    assert check(state, req)


def test_faction_standing_at_least_fails_when_recorded_standing_is_lower():
    state = make_state()
    state.player.faction_standing["merchants"] = "unfriendly"
    req = Requirement(RequirementKind.FACTION_STANDING_AT_LEAST, {"faction_id": "merchants", "tier": "neutral"})
    assert not check(state, req)


def test_faction_standing_at_least_fails_gracefully_for_a_hallucinated_tier():
    # target's JSON schema has no enum to rule this out ahead of time --
    # STANDING_TIERS.index(tier) would raise ValueError uncaught otherwise.
    state = make_state()
    req = Requirement(RequirementKind.FACTION_STANDING_AT_LEAST, {"faction_id": "merchants", "tier": "beloved"})
    assert not check(state, req)


def test_faction_standing_at_least_fails_gracefully_for_a_hallucinated_faction_id():
    # Regression test: an unrecognized faction_id used to silently PASS,
    # since factions.standing_of defaults an absent Player.faction_standing
    # entry to "neutral" regardless of whether the faction exists anywhere
    # in world.factions -- a dangling reference must be rejected, same as
    # an unknown node/link id already is.
    state = make_state()
    req = Requirement(
        RequirementKind.FACTION_STANDING_AT_LEAST, {"faction_id": "smugglers_ring", "tier": "neutral"},
    )
    assert not check(state, req)


# -- Malformed target dicts (a real live bug: an LLM-authored requirement --
# unlike a hand-built one in every test above -- can omit a key the schema
# has no way to require, since `target`'s own schema is just {"type":
# "object"}). Every kind must fail gracefully, never raise. -----------------

def test_node_state_fails_gracefully_when_node_id_is_missing():
    state = make_state()
    assert not check(state, Requirement(RequirementKind.NODE_STATE, {"state": "peaceful"}))


def test_node_state_fails_gracefully_when_state_is_missing():
    state = make_state()
    assert not check(state, Requirement(RequirementKind.NODE_STATE, {"node_id": "a"}))


def test_link_status_fails_gracefully_when_a_key_is_missing():
    state = make_state()
    assert not check(state, Requirement(RequirementKind.LINK_STATUS, {"from_id": "a", "status": "open"}))


def test_player_has_item_fails_gracefully_when_a_key_is_missing():
    state = make_state()
    assert not check(state, Requirement(RequirementKind.PLAYER_HAS_ITEM, {"item_id": "amulet"}))


def test_player_has_skill_fails_gracefully_when_a_key_is_missing():
    state = make_state()
    assert not check(state, Requirement(RequirementKind.PLAYER_HAS_SKILL, {"skill_id": "firebolt"}))


def test_player_gold_at_least_fails_gracefully_when_amount_is_missing():
    state = make_state()
    assert not check(state, Requirement(RequirementKind.PLAYER_GOLD_AT_LEAST, {}))


def test_player_has_item_quantity_at_least_fails_gracefully_when_a_key_is_missing():
    state = make_state()
    assert not check(state, Requirement(RequirementKind.PLAYER_HAS_ITEM_QUANTITY_AT_LEAST, {"item_id": "grain"}))


def test_player_gold_at_least_fails_gracefully_for_a_non_numeric_amount():
    # Regression test: a present-but-non-numeric amount used to raise an
    # uncaught TypeError from the bare `>=` comparison instead of degrading
    # to a failed requirement, same as every other malformed-target case.
    state = make_state()
    assert not check(state, Requirement(RequirementKind.PLAYER_GOLD_AT_LEAST, {"amount": "a lot"}))


def test_player_gold_at_least_accepts_a_whole_number_float_amount():
    # Mirrors llm/schema.py's own whole-number-float-counts-as-integer
    # leniency (Step 8 P6) -- a provider serializing "50" as 50.0 is still
    # a valid amount.
    state = make_state()
    state.player.gold = 50
    assert check(state, Requirement(RequirementKind.PLAYER_GOLD_AT_LEAST, {"amount": 50.0}))


def test_player_has_item_quantity_at_least_fails_gracefully_for_a_non_numeric_amount():
    state = make_state()
    add_item(state.player, "grain", "Grain", quantity=5)
    req = Requirement(RequirementKind.PLAYER_HAS_ITEM_QUANTITY_AT_LEAST, {"item_id": "grain", "amount": "five"})
    assert not check(state, req)


def test_faction_standing_at_least_fails_gracefully_when_faction_id_is_missing():
    state = make_state()
    assert not check(state, Requirement(RequirementKind.FACTION_STANDING_AT_LEAST, {"tier": "neutral"}))


def test_malformed_requirement_does_not_take_down_the_rest_of_the_manifest():
    # The exact real-world shape of the reported crash: one bad requirement
    # (missing node_id) alongside an otherwise-fine one, inside one
    # check_manifest call reached via a real generated quest's manifest.
    state = make_state()
    manifest = PreconditionManifest([
        Requirement(RequirementKind.NODE_STATE, {"state": "occupied"}),  # malformed -- no node_id
        Requirement(RequirementKind.PLAYER_NOT_CAPTURED, {}),  # fine, passes
    ])
    result = check_manifest(state, manifest)
    assert not result.passed
    assert len(result.failures) == 1
    assert "malformed" in result.failures[0].reason


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
